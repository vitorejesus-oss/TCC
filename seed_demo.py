"""Gerador de histórico de demonstração.

Popula o banco com fabricações concluídas e ciclos de quebra/conserto para
validar Dossiê da Peça, tempo médio histórico e MTTR antes de existirem dados
medidos de verdade.

NADA aqui é medição. Tudo o que o script grava fica marcado
origem='DEMONSTRACAO' (notas e relatorios_manutencao; OS e alocações herdam
pela nota) e todo e-mail de pessoa leva ".demo". Não escreve na auditoria:
um log de auditoria com eventos inventados seria pior do que ausência de log.

Uso:
    python seed_demo.py                   # 40 fabricações
    python seed_demo.py --n 60 --seed 7   # outra quantidade / sequência fixa
    python seed_demo.py --limpar          # apaga só origem='DEMONSTRACAO'
"""
import argparse
import math
import random
import sys
from collections import defaultdict
from datetime import datetime, time, timedelta

from app import FOLGA_MAQUINA_PARADA_MIN, _parse_ts, _proximo_numero, get_db

ORIGEM = 'DEMONSTRACAO'

SEMANAS = 8
ABRE, FECHA = time(7, 0), time(17, 0)
JORNADA_MIN = 600
# Feriados nacionais de data fixa (mês, dia). Os móveis (Carnaval, Sexta-feira
# Santa, Corpus Christi) não estão aqui: dependem da Páscoa.
FERIADOS_FIXOS = {(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (12, 25)}

FAIXA_MIN, FAIXA_MAX = 0.70, 1.40
FRACAO_FORA_DA_FAIXA = 0.10
FRACAO_FORA_ABAIXO = 0.30          # dos casos fora da faixa; o resto estoura para cima
PRIORIDADE_URGENTE = 0.15
MAX_TENTATIVAS = 50

SOLICITANTES = ['pcp.demo@fabrica.com', 'coordenador.demo@fabrica.com']
MECANICOS = ['mecanico.demo1@fabrica.com', 'mecanico.demo2@fabrica.com']
QUANTIDADES = [1, 1, 1, 2, 2, 3, 5, 10]

OBS_GERAL = {
    'normal': [
        'Sem intercorrências.',
        'Operação concluída conforme desenho.',
        'Medidas conferidas com paquímetro, dentro da tolerância.',
        'Peça liberada para a próxima etapa sem retrabalho.',
    ],
    'rapida': [
        'Setup reaproveitado da peça anterior.',
        'Ferramenta nova, sem paradas para ajuste.',
        'Material com sobremetal menor que o previsto.',
    ],
    'lenta': [
        'Troca de ferramenta por desgaste durante a operação.',
        'Rebarba removida manualmente antes da conferência.',
        'Parada para reajuste da fixação da peça.',
        'Aguardando ponte rolante para movimentar a peça.',
        'Medida fora de tolerância, refeita a passada de acabamento.',
    ],
    'sobre': [
        'Medida fora de tolerância; peça reposicionada e operação refeita.',
        'Quebra de ferramenta; substituída e operação retomada.',
        'Material com dureza acima do esperado, avanço reduzido.',
        'Parada aguardando liberação de desenho revisado.',
    ],
    'sob': [
        'Sobremetal menor que o previsto; menos passadas.',
        'Peça já vinha próxima da cota; operação simplificada.',
    ],
}
OBS_POR_MAQUINA = {
    'torno': {
        'lenta': ['Ajuste de castanha para melhorar a centragem da peça.',
                  'Vibração na ferramenta; rotação reduzida.'],
        'sobre': ['Peça recentrada na castanha após excentricidade acima do admissível.'],
        'rapida': ['Ferramenta de desbaste nova permitiu passadas mais profundas.'],
    },
    'fresadora': {
        'lenta': ['Fixação na morsa reajustada.', 'Troca de fresa por desgaste.',
                  'Rebarba nos cantos removida com lima.'],
        'sobre': ['Fresa quebrada; troca e novo zeramento da peça.'],
    },
    'retificadora': {
        'lenta': ['Dressagem do rebolo antes do acabamento.',
                  'Retificada em duas passadas para atingir a rugosidade.'],
        'sobre': ['Rebolo trocado durante a operação; nova dressagem e conferência.'],
    },
}

REPAROS = {
    'curta': [
        'Substituição de correia de transmissão desgastada.',
        'Sensor de fim de curso substituído.',
        'Contator do painel elétrico substituído.',
        'Lubrificação do sistema de guias e ajuste de folga do carro.',
    ],
    'media': [
        'Troca de rolamento do eixo-árvore com ruído anormal.',
        'Vazamento na mangueira hidráulica; mangueira substituída.',
        'Bomba de refrigeração trocada; nível de fluido reposto.',
        'Reaperto e realinhamento do cabeçote.',
    ],
    'longa': [
        'Aguardando peça de reposição do fornecedor; substituída na chegada.',
        'Motor de acionamento enviado para rebobinamento; reinstalado e testado.',
    ],
}


class _Recomecar(Exception):
    """O plano sorteado não fecha (termina no futuro, sem janela livre...)."""


# ---------------------------------------------------------------------------
# Calendário: dias úteis, expediente 7h-17h
# ---------------------------------------------------------------------------

def eh_util(d):
    return d.weekday() < 5 and (d.month, d.day) not in FERIADOS_FIXOS


def proximo_util(d):
    d += timedelta(days=1)
    while not eh_util(d):
        d += timedelta(days=1)
    return d


def abre(d):
    return datetime.combine(d, ABRE)


def fecha(d):
    return datetime.combine(d, FECHA)


def alinhar(t):
    """Primeiro instante >= t que cai dentro do expediente."""
    d = t.date()
    if not eh_util(d):
        return abre(proximo_util(d))
    if t < abre(d):
        return abre(d)
    if t >= fecha(d):
        return abre(proximo_util(d))
    return t


def somar_expediente(inicio, minutos):
    """Avança `minutos` de trabalho a partir de `inicio`, pulando noites e folgas."""
    t, restante = alinhar(inicio), float(minutos)
    while True:
        disponivel = (fecha(t.date()) - t).total_seconds() / 60
        if restante <= disponivel:
            return t + timedelta(minutes=restante)
        restante -= disponivel
        t = abre(proximo_util(t.date()))


def instante_conserto(inicio, trabalho, tipo):
    """Reparo curto/médio corre em relógio corrido (a equipe fica até resolver),
    a menos que passasse das 20h: aí retoma no expediente seguinte. Reparo
    longo espera peça de fornecedor e só avança em expediente."""
    if tipo != 'longa':
        fim = inicio + timedelta(minutes=trabalho)
        if fim.date() == inicio.date() and fim.time() <= time(20, 0):
            return fim
    return somar_expediente(inicio, trabalho)


def sortear_instante(rng, dias):
    return abre(rng.choice(dias)) + timedelta(seconds=rng.randint(0, JORNADA_MIN * 60 - 1))


def latencia(rng):
    """Tempo entre a máquina/peça ficar pronta e o operador apertar Iniciar."""
    return timedelta(minutes=rng.randint(3, 25), seconds=rng.randint(0, 59))


def achar_slot(rng, bloqueios, a_partir_de, duracao):
    """Primeiro início >= a_partir_de em que a operação cabe inteira num
    expediente e não cruza nenhum bloqueio (parada de máquina ou execução real
    já gravada)."""
    t = alinhar(a_partir_de)
    while True:
        fim = t + duracao
        if fim > fecha(t.date()):
            t = abre(proximo_util(t.date())) + timedelta(
                minutes=rng.randint(0, 20), seconds=rng.randint(0, 59))
            continue
        conflito = next((b for b in bloqueios if b[0] < fim and t < b[1]), None)
        if conflito is None:
            return t
        t = alinhar(conflito[1] + latencia(rng))


# ---------------------------------------------------------------------------
# Leitura do que já existe no banco
# ---------------------------------------------------------------------------

def carregar_contexto(c):
    maquinas = {r['nome']: r['id'] for r in c.execute('SELECT id, nome FROM maquinas')}

    roteiros = defaultdict(list)
    for r in c.execute('''SELECT p.codigo, o.sequencia, o.maquina, o.tempo_estimado, o.descricao
                          FROM pecas p JOIN operacoes o ON o.peca_id = p.id
                          ORDER BY p.codigo, o.sequencia'''):
        roteiros[r['codigo']].append(dict(r))
    if not roteiros:
        sys.exit('Nenhuma peça com roteiro em `operacoes`. Rode o app uma vez para semear.')

    for codigo, ops in roteiros.items():
        for op in ops:
            if op['maquina'] not in maquinas:
                sys.exit(f"Roteiro da peça {codigo}: máquina '{op['maquina']}' não existe em `maquinas`.")
            if op['tempo_estimado'] * FAIXA_MAX >= JORNADA_MIN - 10:
                sys.exit(f"Roteiro da peça {codigo}: operação de {op['tempo_estimado']} min "
                         f'não cabe num expediente de {JORNADA_MIN} min.')

    # O que é real e já ocupou máquina: execuções concluídas e janelas de
    # manutenção com hora de quebra conhecida. O gerador desvia disso.
    bloqueios = defaultdict(list)
    paradas = defaultdict(list)
    for r in c.execute('''SELECT am.maquina_id, am.inicio_real, am.fim_real
                          FROM alocacao_maquinas am
                          JOIN ordens_servico os ON os.id = am.ordem_servico_id
                          JOIN notas n ON n.id = os.nota_id
                          WHERE COALESCE(n.origem, 'REAL') != ?
                            AND am.inicio_real IS NOT NULL AND am.fim_real IS NOT NULL''',
                         (ORIGEM,)):
        ini, fim = _parse_ts(r['inicio_real']), _parse_ts(r['fim_real'])
        if ini and fim:
            bloqueios[r['maquina_id']].append((ini, fim))
    for r in c.execute('''SELECT maquina_id, quebrada_em, criado_em FROM relatorios_manutencao
                          WHERE COALESCE(origem, 'REAL') != ? AND quebrada_em IS NOT NULL''',
                       (ORIGEM,)):
        ini, fim = _parse_ts(r['quebrada_em']), _parse_ts(r['criado_em'])
        if ini and fim:
            bloqueios[r['maquina_id']].append((ini, fim))
            paradas[r['maquina_id']].append((ini, fim))

    return {'maquinas': maquinas, 'roteiros': dict(roteiros),
            'bloqueios': bloqueios, 'paradas': paradas}


# ---------------------------------------------------------------------------
# Sorteios
# ---------------------------------------------------------------------------

def sortear_minutos(rng, estimado, classe):
    """Tempo realizado. 'normal' fica em 70%-140% do estimado; 'sob'/'sobre'
    ficam deliberadamente fora da faixa (para os indicadores terem outliers)."""
    lo, hi = math.ceil(FAIXA_MIN * estimado), math.floor(FAIXA_MAX * estimado)
    if classe == 'sobre':
        m = round(estimado * rng.uniform(1.45, 2.2))
        return min(max(m, hi + 1), JORNADA_MIN - 10)
    if classe == 'sob':
        m = round(estimado * rng.uniform(0.45, 0.68))
        return max(1, min(m, lo - 1))
    m = round(estimado * rng.triangular(FAIXA_MIN, FAIXA_MAX, 1.05))
    return max(lo, min(hi, m))


def categoria(minutos, estimado, classe):
    if classe in ('sob', 'sobre'):
        return classe
    razao = minutos / estimado
    return 'rapida' if razao < 0.85 else 'lenta' if razao > 1.15 else 'normal'


def sortear_observacao(rng, maquina_nome, cat):
    pool = list(OBS_GERAL[cat])
    for chave, extras in OBS_POR_MAQUINA.items():
        if chave in maquina_nome.lower():
            pool += extras.get(cat, [])
    return rng.choice(pool)


def gerar_paradas(rng, ctx, dias, agora):
    """6 a 8 ciclos quebra -> conserto. O tempo de reparo é o relógio corrido
    entre as duas horas, como o endpoint /consertada calcula (ver
    instante_conserto para quando o relógio para à noite)."""
    ids = sorted(ctx['maquinas'].values())
    usadas = sorted({ctx['maquinas'][op['maquina']]
                     for ops in ctx['roteiros'].values() for op in ops})
    pool = ids + usadas                          # máquinas do roteiro quebram mais
    k = rng.randint(6, 8)
    tipos = ['longa'] + rng.choices(['curta', 'media', 'longa'], weights=[70, 22, 8], k=k - 1)

    ocupado = defaultdict(list, {m: list(v) for m, v in ctx['paradas'].items()})
    ciclos = []
    folga = timedelta(hours=1)
    for tipo in tipos:
        for _ in range(200):
            mid = rng.choice(pool)
            ini = sortear_instante(rng, dias) + timedelta(seconds=rng.randint(0, 59))
            if tipo == 'curta':
                trabalho = int(rng.triangular(45, 240, 110))
            elif tipo == 'media':
                trabalho = rng.randint(240, 480)
            else:
                trabalho = rng.randint(480, 1200)
            fim = instante_conserto(ini, trabalho, tipo).replace(microsecond=0)
            if fim > agora:
                continue
            if any(a < fim + folga and ini < b + folga for a, b in ocupado[mid]):
                continue
            ocupado[mid].append((ini, fim))
            ciclos.append({
                'maquina_id': mid, 'quebrada_em': ini, 'conserto': fim,
                'tempo_reparo_min': int((fim - ini).total_seconds() / 60),
                'usuario': rng.choice(MECANICOS),
                'descricao': rng.choice(REPAROS[tipo]),
            })
            break
        else:
            raise _Recomecar()
    ciclos.sort(key=lambda x: x['quebrada_em'])
    return ciclos


def gerar_plano(rng, ctx, n, agora):
    hoje = agora.date()
    dias = sorted(d for d in (hoje - timedelta(days=k) for k in range(1, SEMANAS * 7 + 1))
                  if eh_util(d))

    codigos = sorted(ctx['roteiros'])
    pecas = [codigos[i % len(codigos)] for i in range(n)]
    rng.shuffle(pecas)

    # Distribui por semana (com variação) em vez de sortear dia a dia: sorteio
    # puro deixa semanas com 1 nota e outras com 9.
    semanas = defaultdict(list)
    for d in dias:
        semanas[d.isocalendar()[:2]].append(d)
    grupos = [semanas[k] for k in sorted(semanas)]
    pesos = [len(g) * rng.uniform(0.6, 1.4) for g in grupos]
    bruto = [n * p / sum(pesos) for p in pesos]
    cotas = [int(b) for b in bruto]
    for i in sorted(range(len(grupos)), key=lambda i: bruto[i] - cotas[i], reverse=True)[:n - sum(cotas)]:
        cotas[i] += 1
    criadas = sorted(sortear_instante(rng, g) for g, q in zip(grupos, cotas) for _ in range(q))

    total_ops = sum(len(ctx['roteiros'][p]) for p in pecas)
    k_fora = max(1, round(FRACAO_FORA_DA_FAIXA * total_ops))
    n_sob = round(k_fora * FRACAO_FORA_ABAIXO)
    escolhidas = rng.sample(range(total_ops), k_fora)
    classe_de = {idx: ('sob' if i < n_sob else 'sobre') for i, idx in enumerate(escolhidas)}

    ciclos = gerar_paradas(rng, ctx, dias, agora)

    bloqueios = defaultdict(list, {m: list(v) for m, v in ctx['bloqueios'].items()})
    paradas = defaultdict(list, {m: list(v) for m, v in ctx['paradas'].items()})
    for cl in ciclos:
        janela = (cl['quebrada_em'], cl['conserto'])
        bloqueios[cl['maquina_id']].append(janela)
        paradas[cl['maquina_id']].append(janela)

    usadas = sorted({ctx['maquinas'][op['maquina']]
                     for ops in ctx['roteiros'].values() for op in ops})
    operador_de = {mid: f'operador.demo{i + 1}@fabrica.com' for i, mid in enumerate(usadas)}

    livre_desde = defaultdict(lambda: datetime.min)   # fila real: sem furar a vez
    fila_plan = defaultdict(list)                     # [[fim_planejado, fim_real], ...]
    notas, contador = [], 0

    for codigo, criada in zip(pecas, criadas):
        roteiro = ctx['roteiros'][codigo]
        t_proc = criada + timedelta(seconds=rng.randint(0, 2))

        # Planejado: mesma conta de AutomacaoUsinagem.processar_nota.
        fim_anterior, entradas, planejado = t_proc, [], []
        for op in roteiro:
            mid = ctx['maquinas'][op['maquina']]
            fim_fila = max((fp for fp, fr in fila_plan[mid] if fr > t_proc and fp > t_proc),
                           default=t_proc)
            parada = any(a <= t_proc < b for a, b in paradas[mid])
            disponivel_em = t_proc + timedelta(minutes=FOLGA_MAQUINA_PARADA_MIN) if parada else t_proc
            ini_p = max(fim_anterior, fim_fila, disponivel_em)
            fim_p = ini_p + timedelta(minutes=op['tempo_estimado'])
            entrada = [fim_p, datetime.max]
            fila_plan[mid].append(entrada)
            entradas.append(entrada)
            planejado.append((ini_p, fim_p))
            fim_anterior = fim_p

        # Realizado: respeita fila da máquina, ordem das operações, expediente
        # e paradas.
        prev, ops = t_proc, []
        for op, entrada, (ini_p, fim_p) in zip(roteiro, entradas, planejado):
            mid = ctx['maquinas'][op['maquina']]
            classe = classe_de.get(contador, 'normal')
            contador += 1
            minutos = sortear_minutos(rng, op['tempo_estimado'], classe)
            duracao = timedelta(minutes=minutos, seconds=rng.randint(0, 59))
            a_partir = max(prev, livre_desde[mid]) + latencia(rng)
            ini_r = achar_slot(rng, bloqueios[mid], a_partir, duracao)
            fim_r = ini_r + duracao
            livre_desde[mid] = fim_r
            entrada[1] = fim_r
            prev = fim_r
            ops.append({
                'maquina_id': mid, 'sequencia': op['sequencia'],
                'estimado': op['tempo_estimado'],
                'inicio_planejado': ini_p, 'fim_planejado': fim_p,
                'inicio_real': ini_r, 'fim_real': fim_r,
                'tempo_realizado_min': minutos, 'classe': classe,
                'operador': operador_de[mid],
                'observacao': sortear_observacao(
                    rng, op['maquina'], categoria(minutos, op['tempo_estimado'], classe)),
            })

        notas.append({
            'peca_codigo': codigo, 'quantidade': rng.choice(QUANTIDADES),
            'prioridade': 'URGENTE' if rng.random() < PRIORIDADE_URGENTE else 'NORMAL',
            'solicitante': rng.choice(SOLICITANTES),
            'criada_em': criada, 't_proc': t_proc, 'ops': ops,
            'tempo_total': sum(op['tempo_estimado'] for op in roteiro),
        })

    ultimo = max([o['fim_real'] for nt in notas for o in nt['ops']] +
                 [cl['conserto'] for cl in ciclos])
    if ultimo > agora:
        raise _Recomecar()
    return {'notas': notas, 'paradas': ciclos}


# ---------------------------------------------------------------------------
# Gravação e limpeza
# ---------------------------------------------------------------------------

def gravar(conn, plano):
    """Tudo numa transação só: ou entra o histórico inteiro, ou nada."""
    c = conn.cursor()
    c.execute('BEGIN IMMEDIATE')
    try:
        for nt in plano['notas']:
            numero = _proximo_numero(c, 'notas', 'NT')
            c.execute('''INSERT INTO notas
                         (numero, peca_codigo, quantidade, prioridade, solicitante,
                          status, criada_em, validada_em, origem)
                         VALUES (?, ?, ?, ?, ?, 'PROCESSADA', ?, ?, ?)''',
                      (numero, nt['peca_codigo'], nt['quantidade'], nt['prioridade'],
                       nt['solicitante'], nt['criada_em'].isoformat(),
                       nt['t_proc'].isoformat(), ORIGEM))
            nota_id = c.lastrowid

            primeira, ultima = nt['ops'][0], nt['ops'][-1]
            c.execute('''INSERT INTO ordens_servico
                         (numero, nota_id, status, prioridade, tempo_total,
                          tempo_inicio, tempo_fim, criada_em, concluida_em)
                         VALUES (?, ?, 'CONCLUIDA', ?, ?, ?, ?, ?, ?)''',
                      (_proximo_numero(c, 'ordens_servico', 'OS'), nota_id, nt['prioridade'],
                       nt['tempo_total'], primeira['inicio_real'].isoformat(),
                       ultima['fim_real'].isoformat(), nt['t_proc'].isoformat(),
                       ultima['fim_real'].isoformat()))
            os_id = c.lastrowid

            for op in nt['ops']:
                c.execute('''INSERT INTO alocacao_maquinas
                             (ordem_servico_id, maquina_id, sequencia, status,
                              inicio_planejado, fim_planejado, inicio_real, fim_real,
                              tempo_realizado_min, operador, observacao)
                             VALUES (?, ?, ?, 'CONCLUIDO', ?, ?, ?, ?, ?, ?, ?)''',
                          (os_id, op['maquina_id'], op['sequencia'],
                           op['inicio_planejado'].isoformat(), op['fim_planejado'].isoformat(),
                           op['inicio_real'].isoformat(), op['fim_real'].isoformat(),
                           op['tempo_realizado_min'], op['operador'], op['observacao']))

        for cl in plano['paradas']:
            c.execute('''INSERT INTO relatorios_manutencao
                         (maquina_id, usuario, descricao, quebrada_em, tempo_reparo_min,
                          criado_em, origem)
                         VALUES (?, ?, ?, ?, ?, ?, ?)''',
                      (cl['maquina_id'], cl['usuario'], cl['descricao'],
                       cl['quebrada_em'].isoformat(), cl['tempo_reparo_min'],
                       cl['conserto'].isoformat(), ORIGEM))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def limpar():
    conn = get_db()
    c = conn.cursor()
    c.execute('BEGIN IMMEDIATE')
    try:
        nas_notas = '''(SELECT os.id FROM ordens_servico os
                        JOIN notas n ON n.id = os.nota_id WHERE n.origem = ?)'''
        aloc = c.execute(f'DELETE FROM alocacao_maquinas WHERE ordem_servico_id IN {nas_notas}',
                         (ORIGEM,)).rowcount
        oss = c.execute('''DELETE FROM ordens_servico
                           WHERE nota_id IN (SELECT id FROM notas WHERE origem = ?)''',
                        (ORIGEM,)).rowcount
        notas = c.execute('DELETE FROM notas WHERE origem = ?', (ORIGEM,)).rowcount
        reps = c.execute('DELETE FROM relatorios_manutencao WHERE origem = ?',
                         (ORIGEM,)).rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(f'Removido (origem={ORIGEM}): {notas} notas, {oss} OS, {aloc} operações, '
          f'{reps} relatórios de manutenção.')


def resumo(plano, seed):
    notas, ciclos = plano['notas'], plano['paradas']
    ops = [o for nt in notas for o in nt['ops']]
    fora = [o for o in ops if o['classe'] != 'normal']
    razoes = [o['tempo_realizado_min'] / o['estimado'] for o in ops]
    mttr = [cl['tempo_reparo_min'] for cl in ciclos]
    print(f'Histórico de demonstração gravado (seed {seed}).')
    print(f"  fabricações: {len(notas)}, de {notas[0]['criada_em']:%d/%m/%Y} "
          f"a {max(o['fim_real'] for o in ops):%d/%m/%Y}")
    print(f'  operações:   {len(ops)}; realizado/estimado médio {sum(razoes) / len(razoes):.0%}; '
          f'{len(fora)} fora de 70%-140%')
    print(f'  quebras:     {len(ciclos)} ciclos; reparo mín/média/máx '
          f'{min(mttr)}/{sum(mttr) // len(mttr)}/{max(mttr)} min (relógio corrido)')
    print('  Para remover: python seed_demo.py --limpar')


def main():
    sys.stdout.reconfigure(errors='replace')
    ap = argparse.ArgumentParser(description='Gera histórico de demonstração (origem=DEMONSTRACAO).')
    ap.add_argument('--n', type=int, default=40, help='número de fabricações (padrão 40)')
    ap.add_argument('--seed', type=int, default=None, help='semente, para repetir o mesmo histórico')
    ap.add_argument('--limpar', action='store_true',
                    help="apaga só o que tem origem='DEMONSTRACAO' e sai")
    args = ap.parse_args()

    if args.limpar:
        limpar()
        return
    if args.n < 1:
        sys.exit('--n precisa ser >= 1')

    conn = get_db()
    c = conn.cursor()
    ja = c.execute('SELECT COUNT(*) FROM notas WHERE origem = ?', (ORIGEM,)).fetchone()[0]
    ja += c.execute('SELECT COUNT(*) FROM relatorios_manutencao WHERE origem = ?',
                    (ORIGEM,)).fetchone()[0]
    if ja:
        conn.close()
        sys.exit(f'Já existe histórico de demonstração no banco ({ja} registros). '
                 'Rode com --limpar antes de gerar de novo.')

    ctx = carregar_contexto(c)
    agora = datetime.now().replace(microsecond=0)
    seed = args.seed if args.seed is not None else random.randrange(10 ** 6)

    for tentativa in range(MAX_TENTATIVAS):
        try:
            plano = gerar_plano(random.Random(f'{seed}:{tentativa}'), ctx, args.n, agora)
            break
        except _Recomecar:
            continue
    else:
        conn.close()
        sys.exit('Não consegui montar um histórico que termine antes de agora. '
                 'Tente outra --seed ou menos fabricações.')

    try:
        gravar(conn, plano)
    finally:
        conn.close()
    resumo(plano, seed)


if __name__ == '__main__':
    main()
