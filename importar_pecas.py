"""Importação do catálogo de peças (código, nome e roteiro) a partir de um CSV.

Formato: separador ';', uma linha por operação, com o cabeçalho
    codigo;nome;sequencia;maquina;tempo_estimado_min;descricao
Veja o modelo_pecas.csv. O CSV do Excel em português (";") e o "CSV UTF-8"
são lidos.

Cada peça é aceita ou recusada INTEIRA: um roteiro pela metade planejaria
errado. Só é aceita se
  - os campos obrigatórios (todos menos descricao) estão preenchidos,
  - a máquina existe em `maquinas` (o planejador acha a máquina pelo nome),
  - sequencia e tempo são inteiros (sequencia >= 1, tempo > 0),
  - as sequências são 1, 2, 3... sem buraco nem repetição,
  - o nome é o mesmo em todas as linhas da peça.

Peça que já existe tem o nome e o roteiro SUBSTITUÍDOS pelos do arquivo (as
sequências que sumiram são apagadas). Notas e OS já criadas não mudam: o
planejado delas ficou gravado. Peça nova entra sem descricao própria (o CSV
só traz a descrição de cada operação). Tudo o que é aceito entra numa
transação só, e cada peça criada ou atualizada vira um evento na auditoria.

Uso:
    python importar_pecas.py catalogo.csv              # grava
    python importar_pecas.py catalogo.csv --simular    # valida e mostra, sem gravar
Saída: 0 = tudo importado, 1 = alguma peça recusada, 2 = arquivo inválido.
"""
import argparse
import csv
import io
import re
import sqlite3
import sys
from collections import OrderedDict, defaultdict

from app import get_db, registrar_auditoria

COLUNAS = ('codigo', 'nome', 'sequencia', 'maquina', 'tempo_estimado_min', 'descricao')
OBRIGATORIAS = COLUNAS[:5]
SEM_MUDANCAS = 'sem mudanças'


class ArquivoInvalido(Exception):
    """O arquivo em si não dá para ler (nada a importar nem a recusar)."""


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------

def ler_csv(caminho):
    """Devolve (linhas, codificacao, colunas_ignoradas).

    `linhas` é [(numero_da_linha, {coluna: texto}, erro_de_formato_ou_None)].
    """
    try:
        with open(caminho, 'rb') as f:
            bruto = f.read()
    except OSError as e:
        raise ArquivoInvalido(f'não consegui abrir {caminho}: {e.strerror or e}')

    try:
        texto, codificacao = bruto.decode('utf-8-sig'), 'UTF-8'
    except UnicodeDecodeError:
        try:
            texto, codificacao = bruto.decode('cp1252'), 'Windows-1252 (Excel)'
        except UnicodeDecodeError:
            raise ArquivoInvalido('codificação não reconhecida (salve como CSV UTF-8)')

    leitor = csv.reader(io.StringIO(texto, newline=''), delimiter=';')
    cabecalho, linhas = None, []
    for campos in leitor:
        if not any(x.strip() for x in campos):
            continue
        if cabecalho is None:
            cabecalho = [x.strip().lower() for x in campos]
            faltam = [c for c in OBRIGATORIAS if c not in cabecalho]
            if faltam:
                dica = ''
                if len(cabecalho) == 1 and ',' in cabecalho[0]:
                    dica = " O separador precisa ser ';' (ponto e vírgula), não ','."
                raise ArquivoInvalido(
                    f"cabeçalho sem a(s) coluna(s): {', '.join(faltam)}.{dica} "
                    f"Esperado: {';'.join(COLUNAS)}")
            repetidas = sorted({c for c in cabecalho if cabecalho.count(c) > 1})
            if repetidas:
                raise ArquivoInvalido(f"coluna repetida no cabeçalho: {', '.join(repetidas)}")
            continue

        erro = None
        if len(campos) > len(cabecalho):
            erro = (f'{len(campos)} colunas, o cabeçalho tem {len(cabecalho)} '
                    "(algum texto tem ';'? coloque entre aspas)")
        campos = list(campos) + [''] * (len(cabecalho) - len(campos))
        linhas.append((leitor.line_num, {c: v.strip() for c, v in zip(cabecalho, campos)}, erro))

    if cabecalho is None:
        raise ArquivoInvalido('arquivo vazio')
    if not linhas:
        raise ArquivoInvalido('só o cabeçalho, sem nenhuma linha de dados')

    ignoradas = [c for c in cabecalho if c and c not in COLUNAS]
    return linhas, codificacao, ignoradas


# ---------------------------------------------------------------------------
# Validação (não toca no banco)
# ---------------------------------------------------------------------------

def _inteiro(texto):
    """Inteiro positivo escrito só com dígitos, ou None."""
    if re.fullmatch(r'[0-9]+', texto or ''):
        valor = int(texto)
        return valor if valor >= 1 else None
    return None


def validar(linhas, maquinas):
    """`maquinas` é {nome em minúsculas: nome como está no banco}.

    Devolve (aceitas, recusadas). Aceita: {codigo, nome, ops, avisos}.
    Recusada: {codigo, nome, motivos}.
    """
    grupos, sem_codigo = OrderedDict(), []
    for numero, linha, erro in linhas:
        codigo = linha.get('codigo', '')
        if not codigo:
            sem_codigo.append(f'linha {numero}: código vazio')
        else:
            grupos.setdefault(codigo, []).append((numero, linha, erro))

    aceitas, recusadas = [], []
    for codigo, itens in grupos.items():
        motivos, avisos, ops = [], [], []
        nomes = OrderedDict()
        sequencias = []                 # (sequencia, linha) de toda linha com sequência válida
        sequencia_invalida = False

        for numero, l, erro in itens:
            def recusar(texto, numero=numero):
                motivos.append(f'linha {numero}: {texto}')

            if erro:
                recusar(erro)
                sequencia_invalida = True
                continue

            if not l.get('nome'):
                recusar('nome vazio')
            else:
                nomes.setdefault(l['nome'], []).append(numero)

            seq = _inteiro(l.get('sequencia'))
            if seq is None:
                recusar(f"sequencia '{l.get('sequencia', '')}' inválida (inteiro, 1 ou mais)")
                sequencia_invalida = True
            else:
                sequencias.append((seq, numero))

            tempo = _inteiro(l.get('tempo_estimado_min'))
            if tempo is None:
                recusar(f"tempo_estimado_min '{l.get('tempo_estimado_min', '')}' inválido "
                        '(inteiro positivo, em minutos)')

            maquina = None
            texto_maquina = l.get('maquina', '')
            if not texto_maquina:
                recusar('maquina vazia')
            else:
                maquina = maquinas.get(texto_maquina.casefold())
                if maquina is None:
                    recusar(f"maquina '{texto_maquina}' não existe em maquinas "
                            f"(existentes: {', '.join(sorted(maquinas.values()))})")
                elif maquina != texto_maquina:
                    avisos.append(f"linha {numero}: maquina '{texto_maquina}' gravada como '{maquina}'")

            if seq is not None and tempo is not None and maquina is not None:
                ops.append({'sequencia': seq, 'maquina': maquina, 'tempo': tempo,
                            'descricao': l.get('descricao', ''), 'linha': numero})

        if len(nomes) > 1:
            partes = [f"'{n}' (linha{'s' if len(v) > 1 else ''} {', '.join(map(str, v))})"
                      for n, v in nomes.items()]
            motivos.append('nome diferente entre as linhas: ' + ' e '.join(partes))

        por_sequencia = defaultdict(list)
        for seq, numero in sequencias:
            por_sequencia[seq].append(numero)
        for seq, numeros in sorted(por_sequencia.items()):
            if len(numeros) > 1:
                motivos.append(f"sequencia {seq} repetida (linhas {', '.join(map(str, numeros))})")
        if por_sequencia and not sequencia_invalida:
            faltam = [s for s in range(1, max(por_sequencia) + 1) if s not in por_sequencia]
            if faltam:
                motivos.append(f"sequências com buraco: faltam {', '.join(map(str, faltam))} "
                               '(precisam ser 1, 2, 3... sem buraco)')

        if motivos:
            recusadas.append({'codigo': codigo, 'nome': next(iter(nomes), ''), 'motivos': motivos})
        else:
            aceitas.append({'codigo': codigo, 'nome': next(iter(nomes)), 'avisos': avisos,
                            'ops': sorted(ops, key=lambda o: o['sequencia'])})

    if sem_codigo:
        recusadas.append({'codigo': '(sem código)', 'nome': '', 'motivos': sem_codigo})
    return aceitas, recusadas


# ---------------------------------------------------------------------------
# Comparação e gravação
# ---------------------------------------------------------------------------

def _diferencas(nome_atual, nome_novo, atual, novo):
    """Lista de mudanças legíveis entre o roteiro do banco e o do arquivo."""
    mudancas = []
    if nome_atual != nome_novo:
        mudancas.append(f"nome: '{nome_atual}' -> '{nome_novo}'")
    for seq in sorted(set(atual) | set(novo)):
        if seq not in atual:
            mudancas.append(f'sequência {seq} adicionada: {novo[seq][0]}, {novo[seq][1]} min')
        elif seq not in novo:
            mudancas.append(f'sequência {seq} removida ({atual[seq][0]}, {atual[seq][1]} min)')
        elif atual[seq] != novo[seq]:
            (m0, t0, d0), (m1, t1, d1) = atual[seq], novo[seq]
            partes = []
            if m0 != m1:
                partes.append(f"maquina '{m0}' -> '{m1}'")
            if t0 != t1:
                partes.append(f'tempo {t0} -> {t1} min')
            if d0 != d1:
                partes.append('descrição alterada')
            mudancas.append(f"sequência {seq}: {'; '.join(partes)}")
    return mudancas


def _gravar_peca(c, peca, atual):
    if atual is None:
        peca_id = c.execute('INSERT INTO pecas (codigo, nome) VALUES (?, ?)',
                            (peca['codigo'], peca['nome'])).lastrowid
    else:
        peca_id = atual['id']
        c.execute('UPDATE pecas SET nome = ? WHERE id = ?', (peca['nome'], peca_id))
    for op in peca['ops']:
        c.execute('''INSERT INTO operacoes (peca_id, sequencia, maquina, tempo_estimado, descricao)
                     VALUES (?, ?, ?, ?, ?)
                     ON CONFLICT(peca_id, sequencia) DO UPDATE SET
                         maquina = excluded.maquina,
                         tempo_estimado = excluded.tempo_estimado,
                         descricao = excluded.descricao''',
                  (peca_id, op['sequencia'], op['maquina'], op['tempo'], op['descricao'] or None))
    c.execute('DELETE FROM operacoes WHERE peca_id = ? AND sequencia > ?',
              (peca_id, len(peca['ops'])))
    return peca_id


def aplicar(conn, aceitas, gravar):
    """Compara cada peça aceita com o banco e, se `gravar`, grava tudo numa
    transação só. Devolve [{peca, situacao, mudancas, peca_id}]."""
    c = conn.cursor()
    if gravar:
        c.execute('BEGIN IMMEDIATE')
    resultado = []
    try:
        for peca in aceitas:
            atual = c.execute('SELECT id, nome FROM pecas WHERE codigo = ?',
                              (peca['codigo'],)).fetchone()
            novo = {o['sequencia']: (o['maquina'], o['tempo'], o['descricao'] or '')
                    for o in peca['ops']}
            if atual is None:
                situacao, mudancas, peca_id = 'nova', [], None
            else:
                antigo = {r['sequencia']: (r['maquina'], r['tempo_estimado'], r['descricao'] or '')
                          for r in c.execute('SELECT sequencia, maquina, tempo_estimado, descricao '
                                             'FROM operacoes WHERE peca_id = ?', (atual['id'],))}
                mudancas = _diferencas(atual['nome'], peca['nome'], antigo, novo)
                situacao = 'atualizada' if mudancas else SEM_MUDANCAS
                peca_id = atual['id']
            if gravar and situacao != SEM_MUDANCAS:
                peca_id = _gravar_peca(c, peca, atual)
            resultado.append({'peca': peca, 'situacao': situacao,
                              'mudancas': mudancas, 'peca_id': peca_id})
        if gravar:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return resultado


# ---------------------------------------------------------------------------
# Saída
# ---------------------------------------------------------------------------

def imprimir(caminho, codificacao, ignoradas, resultado, recusadas, gravou):
    print(f'Arquivo: {caminho} ({codificacao})')
    if ignoradas:
        print(f"Colunas ignoradas: {', '.join(ignoradas)}")
    print()

    if gravou:
        print(f'IMPORTADAS ({len(resultado)})')
    else:
        print(f'SERIAM IMPORTADAS ({len(resultado)}) - simulação, nada foi gravado')
    for r in resultado:
        p = r['peca']
        print(f"  {p['codigo']}  {p['nome']}  [{r['situacao']}]  {len(p['ops'])} operação(ões)")
        for o in p['ops']:
            detalhe = f" - {o['descricao']}" if o['descricao'] else ''
            print(f"      {o['sequencia']}. {o['maquina']} - {o['tempo']} min{detalhe}")
        for m in r['mudancas']:
            print(f'      alteração: {m}')
        for a in p['avisos']:
            print(f'      aviso: {a}')
    if not resultado:
        print('  (nenhuma)')

    print(f'\nRECUSADAS ({len(recusadas)})')
    for r in recusadas:
        print(f"  {r['codigo']}  {r['nome']}".rstrip())
        for m in r['motivos']:
            print(f'      - {m}')
    if not recusadas:
        print('  (nenhuma)')

    contagem = defaultdict(int)
    for r in resultado:
        contagem[r['situacao']] += 1
    print(f"\nResumo: {contagem['nova']} nova(s), {contagem['atualizada']} atualizada(s), "
          f"{contagem[SEM_MUDANCAS]} sem mudanças, {len(recusadas)} recusada(s)."
          + ('' if gravou else ' [SIMULAÇÃO]'))


def main(argv=None):
    sys.stdout.reconfigure(errors='replace')
    ap = argparse.ArgumentParser(description='Importa peças e roteiros de um CSV (veja modelo_pecas.csv).')
    ap.add_argument('arquivo', help='CSV com codigo;nome;sequencia;maquina;tempo_estimado_min;descricao')
    ap.add_argument('--simular', action='store_true',
                    help='valida e mostra o que aconteceria, sem gravar nada')
    args = ap.parse_args(argv)

    try:
        linhas, codificacao, ignoradas = ler_csv(args.arquivo)
    except ArquivoInvalido as e:
        print(f'Arquivo inválido: {e}', file=sys.stderr)
        return 2

    conn = get_db()
    try:
        maquinas = {r['nome'].casefold(): r['nome'] for r in conn.execute('SELECT nome FROM maquinas')}
        aceitas, recusadas = validar(linhas, maquinas)
        resultado = aplicar(conn, aceitas, gravar=not args.simular)
    except sqlite3.OperationalError as e:
        print(f'Não consegui gravar (o banco está ocupado? feche o backend e tente de novo): {e}',
              file=sys.stderr)
        return 2
    finally:
        conn.close()

    if not args.simular:
        for r in resultado:
            if r['situacao'] != SEM_MUDANCAS:
                p = r['peca']
                registrar_auditoria(
                    'IMPORTACAO_CATALOGO', 'PECA', r['peca_id'],
                    f"Peça {p['codigo']} {r['situacao']} por importação de {args.arquivo}: "
                    f"{len(p['ops'])} operação(ões)")

    imprimir(args.arquivo, codificacao, ignoradas, resultado, recusadas, gravou=not args.simular)
    return 1 if recusadas else 0


if __name__ == '__main__':
    sys.exit(main())
