"""Testes das funções puras de bot_telegram.py (formatação de mensagem).

Isolado de propósito: importar bot_telegram.py não abre rede nem fala com o
Telegram (isso só acontece dentro de main(), nunca no nível do módulo).
Essas funções recebem o JSON que a API devolveria e só formatam texto —
zero HTTP aqui.
"""
from datetime import datetime, timedelta

import bot_telegram as bt


class TestTextoMaquinas:
    def test_sem_maquinas(self):
        assert 'Nenhuma' in bt.texto_maquinas([])

    def test_disponivel_sem_hora_de_quebra(self):
        texto = bt.texto_maquinas([{'nome': 'Torno Horizontal', 'status': 'DISPONIVEL'}])
        assert '🟢 Torno Horizontal' in texto
        assert 'parada' not in texto

    def test_quebrada_mostra_tempo_parada(self):
        quebrada_em = (datetime.now() - timedelta(hours=2, minutes=15)).isoformat()
        texto = bt.texto_maquinas([{'nome': 'Serra de Fita', 'status': 'QUEBRADA', 'quebrada_em': quebrada_em}])
        assert '🔴 Serra de Fita' in texto
        assert 'parada há 2h15min' in texto

    def test_quebrada_menos_de_uma_hora_nao_mostra_h(self):
        quebrada_em = (datetime.now() - timedelta(minutes=40)).isoformat()
        texto = bt.texto_maquinas([{'nome': 'Serra de Fita', 'status': 'QUEBRADA', 'quebrada_em': quebrada_em}])
        assert 'parada há 40min' in texto
        assert 'h' not in texto.split('parada há')[1].split('min')[0]

    def test_quebrada_sem_quebrada_em_nao_quebra_a_formatacao(self):
        texto = bt.texto_maquinas([{'nome': 'Mandrilhadora', 'status': 'QUEBRADA'}])
        assert texto == '🏭 Máquinas:\n🔴 Mandrilhadora'

    def test_quebrada_em_invalido_nao_derruba_o_bot(self):
        texto = bt.texto_maquinas([{'nome': 'X', 'status': 'QUEBRADA', 'quebrada_em': 'lixo-nao-e-data'}])
        assert '🔴 X' in texto


class TestTextoOrdens:
    def test_sem_pendentes(self):
        assert 'Nenhuma' in bt.texto_ordens([{'numero': 'OS-1', 'status': 'CONCLUIDA'}])

    def test_urgente_marcada(self):
        texto = bt.texto_ordens([{'numero': 'OS-1', 'status': 'PLANEJAMENTO', 'prioridade': 'URGENTE',
                                  'peca_nome': 'Placa'}])
        assert '🚨 OS-1' in texto

    def test_normal_nao_marcada_com_sirene(self):
        texto = bt.texto_ordens([{'numero': 'OS-2', 'status': 'USINANDO', 'prioridade': 'NORMAL',
                                  'peca_nome': 'Eixo'}])
        assert '🚨' not in texto
        assert '• OS-2' in texto

    def test_limite_trunca_e_avisa_quanto_falta(self):
        ordens = [{'numero': f'OS-{i}', 'status': 'PLANEJAMENTO', 'prioridade': 'NORMAL'} for i in range(15)]
        texto = bt.texto_ordens(ordens, limite=10)
        assert texto.count('OS-') == 10
        assert 'mais 5' in texto


ORDEM = {'id': 7, 'numero': 'OS-2026-0007', 'prioridade': 'NORMAL', 'peca_codigo': '40-091799'}


def _op(id_, seq, status, maquina='Torno Horizontal', planejado=120, maquina_status='DISPONIVEL'):
    return {'id': id_, 'sequencia': seq, 'status': status, 'maquina_nome': maquina,
            'maquina_status': maquina_status, 'tempo_planejado_min': planejado}


class TestOperacoesDaFila:
    def test_executando_e_liberada_entram_concluida_e_planejada_nao(self):
        ops = [_op(1, 1, 'CONCLUIDO'), _op(2, 2, 'LIBERADO'), _op(3, 3, 'PLANEJADO')]
        itens = bt.operacoes_da_fila(ORDEM, ops)
        assert [i['alocacao_id'] for i in itens] == [2]

    def test_so_liberada_e_executando_entram_planejada_nao_mesmo_sendo_a_primeira(self):
        assert bt.operacoes_da_fila(ORDEM, [_op(1, 1, 'PLANEJADO'), _op(2, 2, 'PLANEJADO')]) == []
        itens = bt.operacoes_da_fila(ORDEM, [_op(1, 1, 'LIBERADO'), _op(2, 2, 'PLANEJADO')])
        assert [i['alocacao_id'] for i in itens] == [1]

    def test_executando_entra(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op(1, 1, 'EXECUTANDO')])
        assert itens[0]['status'] == 'EXECUTANDO' and itens[0]['os_id'] == 7

    def test_carrega_maquina_parada_e_total_de_operacoes(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op(1, 1, 'LIBERADO', maquina_status='QUEBRADA'), _op(2, 2, 'PLANEJADO')])
        assert itens[0]['maquina_parada'] is True and itens[0]['total_operacoes'] == 2


class TestTextoFilaOperacoes:
    def test_vazia(self):
        assert 'vazia' in bt.texto_fila_operacoes([])

    def test_linha_tem_os_sequencia_maquina_e_tempo(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op(1, 1, 'EXECUTANDO', planejado=150), _op(2, 2, 'PLANEJADO')])
        texto = bt.texto_fila_operacoes(itens)
        assert 'OS-2026-0007' in texto and 'OP 1/2' in texto
        assert 'Torno Horizontal' in texto and '2h30min estimados' in texto and 'EXECUTANDO' in texto

    def test_maquina_parada_e_sinalizada(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op(1, 1, 'LIBERADO', maquina_status='QUEBRADA')])
        assert 'máquina parada' in bt.texto_fila_operacoes(itens)

    def test_papel_que_nao_executa_recebe_aviso(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op(1, 1, 'LIBERADO')])
        assert 'Só operador e coordenador' in bt.texto_fila_operacoes(itens, pode_executar=False)


class TestTecladoFila:
    def _botoes(self, teclado):
        return [(b.text, b.callback_data) for linha in teclado.inline_keyboard for b in linha]

    def test_iniciar_para_liberada_e_concluir_para_executando(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op(1, 1, 'CONCLUIDO'), _op(2, 2, 'EXECUTANDO')]) + \
            bt.operacoes_da_fila({**ORDEM, 'id': 8, 'numero': 'OS-8'}, [_op(9, 1, 'LIBERADO')])
        botoes = self._botoes(bt.teclado_fila(itens, 'operador'))
        assert ('✅ Concluir OS-2026-0007 · OP 2', 'op:c:2:7') in botoes
        assert ('▶️ Iniciar OS-8 · OP 1', 'op:i:9:8') in botoes

    def test_operador_e_coordenador_veem_botoes(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op(1, 1, 'LIBERADO')])
        assert bt.teclado_fila(itens, 'operador') and bt.teclado_fila(itens, 'coordenador')

    def test_gestor_e_diretor_nao_veem_botoes(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op(1, 1, 'LIBERADO')])
        assert bt.teclado_fila(itens, 'gestor') is None and bt.teclado_fila(itens, 'diretor') is None

    def test_callback_data_cabe_no_limite_do_telegram(self):
        itens = bt.operacoes_da_fila({**ORDEM, 'id': 999999}, [_op(999999, 1, 'LIBERADO')])
        assert all(len(d.encode()) <= 64 for _, d in self._botoes(bt.teclado_fila(itens, 'operador')))


class TestTraduzirErroAcao:
    def test_maquina_parada_vira_mensagem_legivel(self):
        texto = bt.traduzir_erro_acao('Máquina Serra de Fita está parada')
        assert 'Serra de Fita' in texto and 'conserto' in texto and 'Erro' not in texto

    def test_permissao_negada(self):
        assert 'papel não permite' in bt.traduzir_erro_acao('Permissão negada para este papel')

    def test_ja_iniciada_e_ja_concluida(self):
        assert 'já foi iniciada' in bt.traduzir_erro_acao('Operação já iniciada')
        assert 'já foi concluída' in bt.traduzir_erro_acao('Operação já concluída')

    def test_operacao_anterior_pendente(self):
        texto = bt.traduzir_erro_acao('A operação anterior (OP 1) da OS-1 ainda não foi concluída. Conclua-a antes de iniciar a OP 2')
        assert 'OP 1' in texto and 'Erro' not in texto

    def test_erro_desconhecido_nao_e_engolido(self):
        assert 'algo inesperado' in bt.traduzir_erro_acao('algo inesperado')


class TestTextoConclusao:
    def test_informa_realizado_planejado_e_proxima(self):
        ops = [_op(1, 1, 'CONCLUIDO', planejado=120), _op(2, 2, 'LIBERADO', 'Fresadora Universal', 90)]
        texto = bt.texto_conclusao({'tempo_realizado_min': 130, 'os_concluida': False}, ops, 1)
        assert 'Realizado: 2h10min' in texto and 'Planejado: 2h00min' in texto
        assert '10min acima' in texto
        assert 'OP 2 na Fresadora Universal' in texto

    def test_abaixo_do_planejado(self):
        texto = bt.texto_conclusao({'tempo_realizado_min': 100, 'os_concluida': False},
                                   [_op(1, 1, 'CONCLUIDO', planejado=120)], 1)
        assert '20min abaixo' in texto

    def test_ultima_operacao_conclui_a_os(self):
        texto = bt.texto_conclusao({'tempo_realizado_min': 60, 'os_concluida': True},
                                   [_op(1, 1, 'CONCLUIDO', planejado=60)], 1)
        assert 'OS está concluída' in texto and 'Liberada em seguida' not in texto

    def test_sem_lista_de_operacoes_nao_quebra(self):
        assert 'concluída' in bt.texto_conclusao({'tempo_realizado_min': 5, 'os_concluida': False}, [], 1)


class TestTextoIndicadores:
    def test_campos_principais(self):
        texto = bt.texto_indicadores(
            {'disponibilidade_percentual': 75.0, 'paradas': 2, 'total': 8, 'maquinas': []}, None)
        assert '75.0%' in texto and '2 de 8' in texto

    def test_mttr_por_maquina_so_quando_medido(self):
        texto = bt.texto_indicadores({
            'disponibilidade_percentual': 100, 'paradas': 0, 'total': 8,
            'maquinas': [
                {'nome': 'Serra de Fita', 'mttr_min': 90, 'intervencoes_medidas': 2},
                {'nome': 'Torno Horizontal', 'mttr_min': None, 'intervencoes_medidas': 0},
            ],
        }, None)
        assert 'Serra de Fita' in texto
        assert 'Torno Horizontal' not in texto

    def test_avisa_quando_ha_dado_de_demonstracao(self):
        texto = bt.texto_indicadores(
            {'disponibilidade_percentual': 100, 'paradas': 0, 'total': 8, 'maquinas': []},
            {'origem_dados': {'real': 3, 'demonstracao': 7}})
        assert 'demonstração' in texto and '7' in texto and '3' in texto

    def test_sem_dado_de_demonstracao_nao_avisa(self):
        texto = bt.texto_indicadores(
            {'disponibilidade_percentual': 100, 'paradas': 0, 'total': 8, 'maquinas': []},
            {'origem_dados': {'real': 10, 'demonstracao': 0}})
        assert 'demonstração' not in texto

    def test_estatisticas_none_nao_derruba_o_bot(self):
        texto = bt.texto_indicadores(
            {'disponibilidade_percentual': 100, 'paradas': 0, 'total': 8, 'maquinas': []}, None)
        assert 'Disponibilidade' in texto


class TestDesenhoEFichaNoBot:
    def _botoes(self, teclado):
        return [(b.text, b.callback_data) for linha in teclado.inline_keyboard for b in linha]

    def test_botao_desenho_ao_lado_da_operacao_quando_a_peca_tem_pdf(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op(1, 1, 'LIBERADO')])
        botoes = self._botoes(bt.teclado_fila(itens, 'operador', com_desenho=frozenset({'40-091799'})))
        assert ('📄 Desenho', 'dw:40-091799') in botoes

    def test_sem_pdf_nao_aparece_botao_de_desenho(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op(1, 1, 'LIBERADO')])
        assert not [b for b in self._botoes(bt.teclado_fila(itens, 'operador')) if 'Desenho' in b[0]]
        assert not [b for b in self._botoes(bt.teclado_fila(itens, 'operador', frozenset({'OUTRA'}))) if 'Desenho' in b[0]]

    def test_codigo_que_nao_cabe_no_callback_nao_gera_botao(self):
        assert bt.botao_desenho('X' * 80) is None
        assert bt.botao_desenho('') is None

    def test_ficha_curta_mostra_so_material_dimensoes_e_aplicacao_existentes(self):
        peca = {'ficha': {'material': 'Aço 1045', 'aplicacao': 'Prensa P-12', 'tolerancia': 'H7'}}
        texto = bt.texto_ficha_curta(peca)
        assert texto == 'Material: Aço 1045\nAplicação: Prensa P-12'   # tolerância fica de fora, dimensões vazia some

    def test_ficha_vazia_ou_peca_ausente_nao_gera_texto_nem_placeholder(self):
        assert bt.texto_ficha_curta({'ficha': {}}) == ''
        assert bt.texto_ficha_curta(None) == ''
        assert 'informad' not in bt.texto_ficha_curta({'ficha': {'material': 'Aço'}})


class TestTextoBuscaOS:
    def test_sem_resultado(self):
        assert 'Nenhuma OS' in bt.texto_busca_os({'itens': [], 'total': 0})

    def test_linha_da_os(self):
        texto = bt.texto_busca_os({'total': 1, 'itens': [{
            'numero': 'OS-2026-0042', 'peca_nome': 'Placa Bronze A', 'status': 'USINANDO', 'prioridade': 'URGENTE',
            'maquina_atual': 'Torno Horizontal', 'planejado_min': 210, 'realizado_min': None, 'em_atraso': False}]})
        assert '🚨 OS-2026-0042' in texto and 'Placa Bronze A' in texto
        assert 'Em usinagem' in texto and 'na Torno Horizontal' in texto and 'planejado 3h30min' in texto
        assert 'realizado' not in texto and 'atraso' not in texto

    def test_realizado_e_atraso_aparecem_quando_existem(self):
        texto = bt.texto_busca_os({'total': 1, 'itens': [{
            'numero': 'OS-1', 'peca_nome': 'X', 'status': 'USINANDO', 'prioridade': 'NORMAL',
            'planejado_min': 60, 'realizado_min': 75, 'em_atraso': True, 'atraso_min': 125}]})
        assert 'realizado 1h15min' in texto and 'em atraso há 2h05min' in texto
        assert 'em atraso há 3d 5h' in bt.texto_busca_os({'total': 1, 'itens': [{
            'numero': 'OS-2', 'peca_nome': 'X', 'status': 'USINANDO', 'prioridade': 'NORMAL',
            'em_atraso': True, 'atraso_min': 3 * 1440 + 5 * 60 + 7}]})

    def test_avisa_quando_ha_mais_do_que_o_mostrado(self):
        itens = [{'numero': f'OS-{i}', 'peca_nome': 'X', 'status': 'CONCLUIDA', 'prioridade': 'NORMAL'} for i in range(5)]
        assert 'mostrando 5 de 12' in bt.texto_busca_os({'total': 12, 'itens': itens})


class TestDesenhoProvisorioNoBot:
    def _botoes(self, teclado):
        return [(b.text, b.callback_data) for linha in teclado.inline_keyboard for b in linha]

    def test_botao_provisorio_tem_rotulo_de_aviso_e_callback_proprio(self):
        b = bt.botao_desenho('40-091799', provisorio=True)
        assert (b.text, b.callback_data) == ('📄 Desenho (provisório)', 'dp:40-091799')
        assert bt.botao_desenho('40-091799').callback_data == 'dw:40-091799'

    def test_fila_usa_o_botao_provisorio_so_para_as_pecas_marcadas(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op(1, 1, 'LIBERADO')]) + \
            bt.operacoes_da_fila({**ORDEM, 'id': 8, 'numero': 'OS-8', 'peca_codigo': 'OUTRA'}, [_op(9, 1, 'LIBERADO')])
        botoes = self._botoes(bt.teclado_fila(itens, 'operador', com_desenho=frozenset({'40-091799', 'OUTRA'}),
                                              provisorios=frozenset({'40-091799'})))
        assert ('📄 Desenho (provisório)', 'dp:40-091799') in botoes
        assert ('📄 Desenho', 'dw:OUTRA') in botoes

    def test_aviso_curto_e_claro(self):
        assert 'provisório' in bt.AVISO_PROVISORIO and 'oficial' in bt.AVISO_PROVISORIO
        assert len(bt.AVISO_PROVISORIO) < 120

def _op_ext(id_, seq, status, inicio_real=None, acumulado=0, **kw):
    return {**_op(id_, seq, status, **kw), 'inicio_real': inicio_real, 'tempo_acumulado_min': acumulado}


class TestOperacaoInterrompidaNoBot:
    def _botoes(self, teclado):
        return [(b.text, b.callback_data) for linha in teclado.inline_keyboard for b in linha] if teclado else []

    def test_interrompida_aparece_na_fila_com_maquina_parada(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op_ext(1, 1, 'INTERROMPIDA', '2031-03-10T09:00:00', 42,
                                                     maquina_status='QUEBRADA')])
        texto = bt.texto_fila_operacoes(itens)
        assert 'INTERROMPIDA' in texto and '42min já feitos' in texto and 'máquina parada' in texto

    def test_interrompida_mesmo_sem_o_status_da_maquina_indica_parada(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op_ext(1, 1, 'INTERROMPIDA', '2031-03-10T09:00:00', 5)])
        assert 'máquina parada' in bt.texto_fila_operacoes(itens)

    def test_interrompida_nao_oferece_iniciar_nem_concluir(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op_ext(1, 1, 'INTERROMPIDA', '2031-03-10T09:00:00', 5)])
        assert self._botoes(bt.teclado_fila(itens, 'operador')) == []

    def test_interrompida_mantem_o_botao_de_desenho(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op_ext(1, 1, 'INTERROMPIDA', '2031-03-10T09:00:00', 5)])
        botoes = self._botoes(bt.teclado_fila(itens, 'operador', com_desenho=frozenset({'40-091799'})))
        assert botoes == [('📄 Desenho', 'dw:40-091799')]

    def test_liberada_apos_conserto_vira_retomar(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op_ext(1, 1, 'LIBERADO', '2031-03-10T09:00:00', 42)])
        assert itens[0]['retomada'] is True
        assert 'liberada para retomar' in bt.texto_fila_operacoes(itens).lower() or 'LIBERADA para retomar' in bt.texto_fila_operacoes(itens)
        assert self._botoes(bt.teclado_fila(itens, 'operador')) == [('▶️ Retomar OS-2026-0007 · OP 1', 'op:i:1:7')]

    def test_liberada_de_primeira_execucao_continua_sendo_iniciar(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op_ext(1, 1, 'LIBERADO')])
        assert itens[0]['retomada'] is False
        assert self._botoes(bt.teclado_fila(itens, 'operador'))[0][0].startswith('▶️ Iniciar')

    def test_executando_continua_com_concluir(self):
        itens = bt.operacoes_da_fila(ORDEM, [_op_ext(1, 1, 'EXECUTANDO', '2031-03-10T09:00:00')])
        assert self._botoes(bt.teclado_fila(itens, 'operador'))[0][0].startswith('✅ Concluir')

    def test_erro_de_operacao_interrompida_e_legivel(self):
        texto = bt.traduzir_erro_acao('Operação interrompida: a máquina Torno Horizontal está parada. '
                                      'Aguarde o conserto para retomar')
        assert 'Torno Horizontal' in texto and 'conserto' in texto and 'Erro' not in texto

    def test_erro_de_concluir_sem_retomar_e_legivel(self):
        texto = bt.traduzir_erro_acao('Operação ainda não foi retomada. Inicie-a de novo antes de concluir')
        assert 'retom' in texto.lower()

    def test_indicadores_mostram_producao_perdida_quando_ha(self):
        texto = bt.texto_indicadores({
            'disponibilidade_percentual': 87.5, 'paradas': 1, 'total': 8, 'maquinas': [],
            'producao_perdida_min': {'total': 135, 'por_maquina': [
                {'nome': 'Torno Horizontal', 'minutos': 135}, {'nome': 'Serra de Fita', 'minutos': 0}]},
            'operacoes_interrompidas': 2}, None)
        assert 'Produção perdida' in texto and '2h15min' in texto and '2 operação(ões) interrompida(s)' in texto
        assert 'Torno Horizontal: 2h15min' in texto and 'Serra de Fita' not in texto

    def test_indicadores_sem_producao_perdida_nao_poluem_a_mensagem(self):
        texto = bt.texto_indicadores({
            'disponibilidade_percentual': 100, 'paradas': 0, 'total': 8, 'maquinas': [],
            'producao_perdida_min': {'total': 0, 'por_maquina': []}, 'operacoes_interrompidas': 0}, None)
        assert 'Produção perdida' not in texto


class TestConclusaoForaDoExpedienteNoBot:
    def test_avisa_quando_a_execucao_ficou_fora_do_expediente(self):
        texto = bt.texto_conclusao({'tempo_realizado_min': 90, 'tempo_realizado_corrido_min': 930,
                                    'fora_do_expediente': True, 'os_concluida': False},
                                   [_op(1, 1, 'CONCLUIDO', planejado=120)], 1)
        assert 'Execução fora do expediente' in texto and '15h30min corridos' in texto and '1h30min de expediente' in texto

    def test_sem_aviso_quando_dentro_do_expediente(self):
        texto = bt.texto_conclusao({'tempo_realizado_min': 45, 'tempo_realizado_corrido_min': 45,
                                    'fora_do_expediente': False, 'os_concluida': False},
                                   [_op(1, 1, 'CONCLUIDO', planejado=120)], 1)
        assert 'fora do expediente' not in texto

class TestEsquecidaNoBot:
    def test_fila_marca_a_operacao_possivelmente_esquecida(self):
        op = {**_op(1, 1, 'EXECUTANDO', planejado=150), 'possivelmente_esquecida': True,
              'tempo_usinagem_min': 1711}
        texto = bt.texto_fila_operacoes(bt.operacoes_da_fila(ORDEM, [op]))
        assert 'possivelmente esquecida em aberto' in texto
        assert '28h31min de usinagem para 2h30min planejados' in texto

    def test_executando_normal_nao_e_marcada(self):
        op = {**_op(1, 1, 'EXECUTANDO'), 'possivelmente_esquecida': False, 'tempo_usinagem_min': 30}
        texto = bt.texto_fila_operacoes(bt.operacoes_da_fila(ORDEM, [op]))
        assert 'esquecida' not in texto and 'EXECUTANDO' in texto

    def test_marcada_continua_com_o_botao_concluir(self):
        op = {**_op(1, 1, 'EXECUTANDO'), 'possivelmente_esquecida': True, 'tempo_usinagem_min': 900}
        teclado = bt.teclado_fila(bt.operacoes_da_fila(ORDEM, [op]), 'operador')
        assert [b.text for linha in teclado.inline_keyboard for b in linha][0].startswith('✅ Concluir')

    def test_indicadores_informam_as_operacoes_fora_do_calculo(self):
        texto = bt.texto_indicadores(
            {'disponibilidade_percentual': 100, 'paradas': 0, 'total': 8, 'maquinas': []},
            {'operacoes_fora_do_calculo': {'total': 2}})
        assert '2 operação(ões) ficaram fora do tempo médio e do desvio' in texto

    def test_indicadores_sem_exclusao_nao_avisam(self):
        texto = bt.texto_indicadores(
            {'disponibilidade_percentual': 100, 'paradas': 0, 'total': 8, 'maquinas': []},
            {'operacoes_fora_do_calculo': {'total': 0}})
        assert 'fora do tempo médio' not in texto


class TestIndicadoresDistinguemOsMotivosNoBot:
    BASE = {'disponibilidade_percentual': 100, 'paradas': 0, 'total': 8, 'maquinas': []}

    def test_mostra_a_quebra_por_motivo(self):
        texto = bt.texto_indicadores(self.BASE, {'operacoes_fora_do_calculo': {
            'total': 3, 'por_motivo': {'fora_do_expediente': 2, 'muito_acima_do_planejado': 2}}})
        assert '3 operação(ões) ficaram fora do tempo médio e do desvio' in texto
        assert '2 por execução fora do expediente' in texto and '2 por tempo muito acima do planejado' in texto

    def test_so_o_motivo_que_existe(self):
        texto = bt.texto_indicadores(self.BASE, {'operacoes_fora_do_calculo': {
            'total': 1, 'por_motivo': {'fora_do_expediente': 0, 'muito_acima_do_planejado': 1}}})
        assert 'por tempo muito acima do planejado' in texto and 'por execução fora do expediente' not in texto
