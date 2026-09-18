# =============================================================================
# FASE 1 — FECHAR O CICLO DE EXECUÇÃO
#
# Sistema de Automação de Usinagem — Grand Prix SENAI / Pentágono Mecânico
#
# Hoje o sistema grava inicio_real apenas da sequência 1 e nunca grava
# fim_real. Sem fim_real não existe tempo realizado, e sem tempo realizado
# não existe aderência, MTTR de fabricação, tempo médio histórico nem
# Dossiê da Peça com dado medido.
#
# Esta fase resolve isso com 4 blocos. Aplique NA ORDEM.
# Nada aqui apaga dado existente.
# =============================================================================


# =============================================================================
# BLOCO 1 — MIGRAÇÃO
#
# ONDE: em init_db(), logo depois do trecho que já faz ALTER TABLE em
# "maquinas" (por volta da linha 251, depois do laço com 'localizacao',
# 'foto_url', 'manual_url', ...).
#
# O padrão de PRAGMA + ALTER é o mesmo que você já usa. Rodar duas vezes
# não causa erro.
# =============================================================================

    # --- Fase 1: hora da quebra, para calcular MTTR de manutenção ------------
    c.execute("PRAGMA table_info(maquinas)")
    colunas_maquinas = {row[1] for row in c.fetchall()}
    if 'quebrada_em' not in colunas_maquinas:
        c.execute('ALTER TABLE maquinas ADD COLUMN quebrada_em TIMESTAMP')

    # --- Fase 1: execução real das operações ---------------------------------
    c.execute("PRAGMA table_info(alocacao_maquinas)")
    colunas_alocacao = {row[1] for row in c.fetchall()}
    for coluna, tipo_sql in [
        ('tempo_realizado_min', 'INTEGER'),   # medido: fim_real - inicio_real
        ('operador', 'TEXT'),                 # quem executou
        ('observacao', 'TEXT'),               # o que o operador registrou
    ]:
        if coluna not in colunas_alocacao:
            c.execute(f'ALTER TABLE alocacao_maquinas ADD COLUMN {coluna} {tipo_sql}')

    # --- Fase 1: duração de cada intervenção de manutenção -------------------
    c.execute("PRAGMA table_info(relatorios_manutencao)")
    colunas_relatorio = {row[1] for row in c.fetchall()}
    for coluna, tipo_sql in [
        ('quebrada_em', 'TIMESTAMP'),
        ('tempo_reparo_min', 'INTEGER'),
    ]:
        if coluna not in colunas_relatorio:
            c.execute(f'ALTER TABLE relatorios_manutencao ADD COLUMN {coluna} {tipo_sql}')


# =============================================================================
# BLOCO 2 — GRAVAR A HORA DA QUEBRA
#
# ONDE: na função marcar_maquina_quebrada().
#
# SUBSTITUA esta linha:
#     c.execute("UPDATE maquinas SET status = 'QUEBRADA' WHERE id = ?", (maquina_id,))
# por:
# =============================================================================

    momento_quebra = datetime.now().isoformat()
    c.execute("UPDATE maquinas SET status = 'QUEBRADA', quebrada_em = ? WHERE id = ?",
              (momento_quebra, maquina_id))


# =============================================================================
# BLOCO 3 — FECHAR A INTERVENÇÃO COM DURAÇÃO MEDIDA
#
# ONDE: na função marcar_maquina_consertada().
#
# SUBSTITUA este par de linhas:
#     c.execute("UPDATE maquinas SET status = 'DISPONIVEL', ultimo_conserto = CURRENT_TIMESTAMP WHERE id = ?", (maquina_id,))
#     c.execute('INSERT INTO relatorios_manutencao (maquina_id, usuario, descricao) VALUES (?, ?, ?)', (maquina_id, email, relatorio))
# por:
# =============================================================================

    agora = datetime.now()

    # tempo de reparo = agora - quebrada_em. Só calcula se a quebra foi
    # registrada; máquinas que quebraram antes desta versão têm quebrada_em
    # nulo, e aí o tempo fica nulo em vez de virar um número inventado.
    tempo_reparo = None
    if maquina['quebrada_em']:
        try:
            inicio_parada = datetime.fromisoformat(maquina['quebrada_em'])
            tempo_reparo = int((agora - inicio_parada).total_seconds() / 60)
        except (ValueError, TypeError):
            tempo_reparo = None

    c.execute('''UPDATE maquinas
                 SET status = 'DISPONIVEL', ultimo_conserto = ?, quebrada_em = NULL
                 WHERE id = ?''',
              (agora.isoformat(), maquina_id))

    c.execute('''INSERT INTO relatorios_manutencao
                 (maquina_id, usuario, descricao, quebrada_em, tempo_reparo_min)
                 VALUES (?, ?, ?, ?, ?)''',
              (maquina_id, email, relatorio,
               maquina['quebrada_em'], tempo_reparo))


# =============================================================================
# BLOCO 4 — O CICLO DE EXECUÇÃO DAS OPERAÇÕES
#
# ONDE: cole os três endpoints abaixo junto dos outros endpoints de OS,
# logo depois de iniciar_ordem().
#
# Fluxo que isto implementa:
#
#   iniciar_ordem  -> operação 1 fica EXECUTANDO (código que já existe)
#   concluir       -> grava fim_real + tempo medido; operação 2 fica LIBERADO
#   iniciar        -> operação 2 fica EXECUTANDO, grava inicio_real
#   concluir       -> ... e assim até a última, que conclui a OS
#
# A operação seguinte fica LIBERADO em vez de já começar sozinha porque na
# oficina real a peça espera a máquina ficar livre. Esse intervalo entre
# LIBERADO e EXECUTANDO é tempo de fila — e é um dado que vale medir.
# =============================================================================

@app.route('/api/ordens-servico/<int:os_id>/operacoes', methods=['GET'])
def get_operacoes_os(os_id):
    """Operações de uma OS com planejado x realizado."""
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT am.id, am.sequencia, am.status,
                        am.inicio_planejado, am.fim_planejado,
                        am.inicio_real, am.fim_real,
                        am.tempo_realizado_min, am.operador, am.observacao,
                        m.nome AS maquina_nome, m.status AS maquina_status
                 FROM alocacao_maquinas am
                 JOIN maquinas m ON m.id = am.maquina_id
                 WHERE am.ordem_servico_id = ?
                 ORDER BY am.sequencia''', (os_id,))
    operacoes = []
    for row in c.fetchall():
        op = dict(row)

        # tempo planejado sai do intervalo planejado; o realizado só existe
        # se a operação foi de fato concluída. Os dois campos vão separados
        # de propósito: a tela precisa poder dizer qual é medido.
        planejado = None
        if op['inicio_planejado'] and op['fim_planejado']:
            try:
                ini = datetime.fromisoformat(op['inicio_planejado'])
                fim = datetime.fromisoformat(op['fim_planejado'])
                planejado = int((fim - ini).total_seconds() / 60)
            except (ValueError, TypeError):
                planejado = None

        op['tempo_planejado_min'] = planejado
        op['desvio_min'] = (
            op['tempo_realizado_min'] - planejado
            if planejado is not None and op['tempo_realizado_min'] is not None
            else None
        )
        operacoes.append(op)

    conn.close()
    return jsonify(operacoes)


@app.route('/api/alocacoes/<int:alocacao_id>/iniciar', methods=['POST'])
@jwt_required()
def iniciar_alocacao(alocacao_id):
    """Operador assume uma operação liberada e começa a executá-la."""
    email = get_jwt_identity()
    conn = get_db()
    c = conn.cursor()

    try:
        c.execute('''SELECT am.*, m.nome AS maquina_nome, m.status AS maquina_status,
                            os.numero AS os_numero
                     FROM alocacao_maquinas am
                     JOIN maquinas m ON m.id = am.maquina_id
                     JOIN ordens_servico os ON os.id = am.ordem_servico_id
                     WHERE am.id = ?''', (alocacao_id,))
        aloc = c.fetchone()

        if not aloc:
            return jsonify({'erro': 'Operação não encontrada'}), 404
        if aloc['inicio_real']:
            return jsonify({'erro': 'Operação já iniciada'}), 400
        if aloc['maquina_status'] == 'QUEBRADA':
            return jsonify({
                'erro': f"Máquina {aloc['maquina_nome']} está parada"
            }), 409

        agora = datetime.now().isoformat()
        c.execute('''UPDATE alocacao_maquinas
                     SET status = 'EXECUTANDO', inicio_real = ?, operador = ?
                     WHERE id = ?''', (agora, email, alocacao_id))
        conn.commit()

        registrar_auditoria(
            'OPERACAO_INICIADA', 'ALOCACAO', alocacao_id,
            f"OP {aloc['sequencia']} da {aloc['os_numero']} iniciada por {email} "
            f"na {aloc['maquina_nome']}"
        )

        socketio.emit('operacao_iniciada', {
            'alocacao_id': alocacao_id,
            'os_numero': aloc['os_numero'],
            'sequencia': aloc['sequencia'],
            'maquina': aloc['maquina_nome'],
            'operador': email,
        })

        return jsonify({'status': 'ok', 'inicio_real': agora}), 200

    except Exception as e:
        conn.rollback()
        logger.error(f'Erro ao iniciar operação {alocacao_id}: {e}')
        return jsonify({'erro': str(e)}), 400
    finally:
        conn.close()


@app.route('/api/alocacoes/<int:alocacao_id>/concluir', methods=['POST'])
@jwt_required()
def concluir_alocacao(alocacao_id):
    """Conclui uma operação, mede o tempo gasto e libera a seguinte.

    É aqui que fim_real passa a existir. Todo indicador de tempo realizado
    do sistema depende deste endpoint ser chamado.
    """
    email = get_jwt_identity()
    dados = request.json or {}
    observacao = (dados.get('observacao') or '').strip()

    conn = get_db()
    c = conn.cursor()

    try:
        c.execute('''SELECT am.*, m.nome AS maquina_nome,
                            os.numero AS os_numero, os.id AS os_id,
                            n.peca_codigo
                     FROM alocacao_maquinas am
                     JOIN maquinas m ON m.id = am.maquina_id
                     JOIN ordens_servico os ON os.id = am.ordem_servico_id
                     JOIN notas n ON n.id = os.nota_id
                     WHERE am.id = ?''', (alocacao_id,))
        aloc = c.fetchone()

        if not aloc:
            return jsonify({'erro': 'Operação não encontrada'}), 404
        if aloc['fim_real']:
            return jsonify({'erro': 'Operação já concluída'}), 400
        if not aloc['inicio_real']:
            return jsonify({'erro': 'Operação ainda não foi iniciada'}), 400

        agora = datetime.now()

        realizado = None
        try:
            inicio = datetime.fromisoformat(aloc['inicio_real'])
            realizado = int((agora - inicio).total_seconds() / 60)
        except (ValueError, TypeError):
            realizado = None

        c.execute('''UPDATE alocacao_maquinas
                     SET status = 'CONCLUIDO', fim_real = ?,
                         tempo_realizado_min = ?, observacao = ?,
                         operador = COALESCE(operador, ?)
                     WHERE id = ?''',
                  (agora.isoformat(), realizado, observacao or None,
                   email, alocacao_id))

        # A próxima operação da mesma OS fica disponível para ser assumida.
        c.execute('''SELECT id, sequencia, maquina_id
                     FROM alocacao_maquinas
                     WHERE ordem_servico_id = ? AND sequencia = ?''',
                  (aloc['ordem_servico_id'], aloc['sequencia'] + 1))
        proxima = c.fetchone()

        os_concluida = False
        if proxima:
            c.execute('''UPDATE alocacao_maquinas SET status = 'LIBERADO'
                         WHERE id = ?''', (proxima['id'],))
        else:
            # Era a última operação: a OS terminou.
            c.execute('''UPDATE ordens_servico
                         SET status = 'CONCLUIDA', tempo_fim = ?, concluida_em = ?
                         WHERE id = ?''',
                      (agora.isoformat(), agora.isoformat(),
                       aloc['ordem_servico_id']))
            c.execute('''UPDATE notas SET status = 'CONCLUIDA'
                         WHERE id = (SELECT nota_id FROM ordens_servico WHERE id = ?)''',
                      (aloc['ordem_servico_id'],))
            os_concluida = True

        conn.commit()

        registrar_auditoria(
            'OPERACAO_CONCLUIDA', 'ALOCACAO', alocacao_id,
            f"OP {aloc['sequencia']} da {aloc['os_numero']} concluída por {email} "
            f"em {realizado if realizado is not None else '?'} min"
            + (f". Observação: {observacao}" if observacao else '')
        )

        if os_concluida:
            registrar_auditoria(
                'OS_CONCLUIDA', 'ORDEM_SERVICO', aloc['ordem_servico_id'],
                f"{aloc['os_numero']} concluída — peça {aloc['peca_codigo']}"
            )

        socketio.emit('operacao_concluida', {
            'alocacao_id': alocacao_id,
            'os_id': aloc['ordem_servico_id'],
            'os_numero': aloc['os_numero'],
            'sequencia': aloc['sequencia'],
            'maquina': aloc['maquina_nome'],
            'tempo_realizado_min': realizado,
            'os_concluida': os_concluida,
            'proxima_liberada': dict(proxima)['sequencia'] if proxima else None,
        })

        return jsonify({
            'status': 'ok',
            'tempo_realizado_min': realizado,
            'os_concluida': os_concluida,
        }), 200

    except Exception as e:
        conn.rollback()
        logger.error(f'Erro ao concluir operação {alocacao_id}: {e}')
        return jsonify({'erro': str(e)}), 400
    finally:
        conn.close()


# =============================================================================
# BLOCO 5 — CORRIGIR O INDICADOR QUE HOJE MENTE
#
# ONDE: na função de /api/estatisticas.
#
# A consulta atual calcula "tempo_medio_min" a partir de
# (fim_planejado - inicio_planejado). Isso é o PLANO, não o realizado.
# A tela diz "tempo médio" e mostra tempo estimado.
#
# SUBSTITUA a consulta de desempenho_por_maquina por esta, que separa os
# dois e informa em quantas operações cada média se baseia.
# =============================================================================

    c.execute('''SELECT m.nome AS maquina,
                        COUNT(am.id) AS operacoes,
                        SUM(CASE WHEN am.fim_real IS NOT NULL THEN 1 ELSE 0 END)
                            AS operacoes_medidas,
                        ROUND(AVG((julianday(am.fim_planejado)
                                   - julianday(am.inicio_planejado)) * 24 * 60), 1)
                            AS tempo_planejado_medio_min,
                        ROUND(AVG(am.tempo_realizado_min), 1)
                            AS tempo_realizado_medio_min
                 FROM alocacao_maquinas am
                 JOIN maquinas m ON m.id = am.maquina_id
                 GROUP BY m.id, m.nome
                 ORDER BY m.nome''')

# Na tela, mostre as duas colunas e a contagem de operacoes_medidas.
# Quando operacoes_medidas = 0, o tempo realizado é nulo — mostre "—",
# não zero. Zero parece medição; travessão parece ausência, que é a verdade.


# =============================================================================
# BLOCO 6 — MTTR DE MANUTENÇÃO (indicador novo, agora possível)
#
# ONDE: endpoint novo, junto dos outros de manutenção.
# =============================================================================

@app.route('/api/indicadores/manutencao', methods=['GET'])
def indicadores_manutencao():
    """MTTR por máquina, a partir das intervenções com duração medida."""
    conn = get_db()
    c = conn.cursor()

    c.execute('''SELECT m.id, m.nome, m.status, m.quebrada_em,
                        COUNT(r.id) AS intervencoes,
                        SUM(CASE WHEN r.tempo_reparo_min IS NOT NULL THEN 1 ELSE 0 END)
                            AS intervencoes_medidas,
                        ROUND(AVG(r.tempo_reparo_min), 1) AS mttr_min
                 FROM maquinas m
                 LEFT JOIN relatorios_manutencao r ON r.maquina_id = m.id
                 GROUP BY m.id, m.nome, m.status, m.quebrada_em
                 ORDER BY m.nome''')

    agora = datetime.now()
    resultado = []
    for row in c.fetchall():
        item = dict(row)

        # Se está parada agora, há quanto tempo. Dado medido, não estimado.
        parada_ha_min = None
        if item['status'] == 'QUEBRADA' and item['quebrada_em']:
            try:
                parada_ha_min = int(
                    (agora - datetime.fromisoformat(item['quebrada_em'])).total_seconds() / 60
                )
            except (ValueError, TypeError):
                parada_ha_min = None

        item['parada_ha_min'] = parada_ha_min
        resultado.append(item)

    total = len(resultado)
    paradas = sum(1 for m in resultado if m['status'] == 'QUEBRADA')

    conn.close()
    return jsonify({
        'maquinas': resultado,
        'total': total,
        'paradas': paradas,
        'disponibilidade_percentual': round((total - paradas) / total * 100, 1) if total else None,
    })


# =============================================================================
# COMO TESTAR, NESTA ORDEM
#
# 1. python app.py            -> deve subir sem erro e criar as colunas novas
# 2. Criar uma nota pela aba "Criar Nota" (peça 40-091799, que tem 2 operações)
# 3. Aba Operador -> Iniciar na OS criada
# 4. POST /api/ordens-servico/<id>/operacoes  -> OP 1 EXECUTANDO, OP 2 PLANEJADO
# 5. POST /api/alocacoes/<id_op1>/concluir    -> OP 1 com fim_real e tempo medido,
#                                                OP 2 vira LIBERADO
# 6. POST /api/alocacoes/<id_op2>/iniciar
# 7. POST /api/alocacoes/<id_op2>/concluir    -> OS inteira vira CONCLUIDA
# 8. GET /api/indicadores/manutencao          -> disponibilidade e MTTR
# 9. pytest                                   -> os 24 testes devem continuar passando
#
# ATENÇÃO no passo 9: test_api.py usa o usinagem.db vivo, não um banco
# isolado. Rode "python clean_sap.py" antes, como você já faz.
# =============================================================================
