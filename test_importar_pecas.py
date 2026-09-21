"""Testes do importador de catálogo (importar_pecas.py) e da semeadura de roteiros.

Cada teste roda num banco temporário: DB_PATH é trocado antes de criar as tabelas.
"""
from pathlib import Path

import pytest

import app as app_module
import importar_pecas as imp

MODELO = Path(__file__).parent / 'modelo_pecas.csv'
CAB = 'codigo;nome;sequencia;maquina;tempo_estimado_min;descricao'


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, 'DB_PATH', str(tmp_path / 'teste.db'))
    app_module.init_db()
    app_module.seed_data()
    return tmp_path


def csv_em(pasta, *linhas, cab=CAB, codificacao='utf-8-sig', nome='catalogo.csv'):
    caminho = pasta / nome
    caminho.write_bytes(('\r\n'.join([cab, *linhas]) + '\r\n').encode(codificacao))
    return str(caminho)


def maquinas_do_banco():
    conn = app_module.get_db()
    try:
        return {r['nome'].casefold(): r['nome'] for r in conn.execute('SELECT nome FROM maquinas')}
    finally:
        conn.close()


def validar_arquivo(caminho):
    linhas, _, _ = imp.ler_csv(caminho)
    return imp.validar(linhas, maquinas_do_banco())


def roteiro(codigo):
    conn = app_module.get_db()
    try:
        return [tuple(r) for r in conn.execute(
            '''SELECT o.sequencia, o.maquina, o.tempo_estimado, o.descricao
               FROM operacoes o JOIN pecas p ON p.id = o.peca_id
               WHERE p.codigo = ? ORDER BY o.sequencia''', (codigo,))]
    finally:
        conn.close()


def consultar(sql, *params):
    conn = app_module.get_db()
    try:
        return [tuple(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


class TestModelo:
    def test_modelo_tem_o_cabecalho_e_duas_linhas_de_pecas_existentes(self):
        texto = MODELO.read_text(encoding='utf-8-sig')
        linhas = texto.splitlines()
        assert linhas[0] == CAB
        assert len(linhas) == 3

    def test_modelo_e_valido_e_bate_com_o_catalogo_atual(self, banco):
        aceitas, recusadas = validar_arquivo(str(MODELO))
        assert recusadas == [] and len(aceitas) == 1
        conn = app_module.get_db()
        try:
            resultado = imp.aplicar(conn, aceitas, gravar=False)
        finally:
            conn.close()
        assert resultado[0]['situacao'] == imp.SEM_MUDANCAS


class TestLeitura:
    def test_cabecalho_sem_coluna_obrigatoria(self, banco):
        caminho = csv_em(banco, 'X;Y;1;Torno Horizontal;60;', cab='codigo;nome;sequencia;maquina;descricao')
        with pytest.raises(imp.ArquivoInvalido, match='tempo_estimado_min'):
            imp.ler_csv(caminho)

    def test_separador_virgula_da_dica(self, banco):
        caminho = csv_em(banco, 'X,Y,1,Torno Horizontal,60,', cab=CAB.replace(';', ','))
        with pytest.raises(imp.ArquivoInvalido, match="';'"):
            imp.ler_csv(caminho)

    def test_arquivo_vazio_e_so_cabecalho(self, banco):
        vazio = banco / 'vazio.csv'
        vazio.write_bytes(b'')
        with pytest.raises(imp.ArquivoInvalido, match='vazio'):
            imp.ler_csv(str(vazio))
        with pytest.raises(imp.ArquivoInvalido, match='sem nenhuma linha'):
            imp.ler_csv(csv_em(banco))

    def test_arquivo_inexistente(self, banco):
        with pytest.raises(imp.ArquivoInvalido, match='abrir'):
            imp.ler_csv(str(banco / 'nao_existe.csv'))

    def test_coluna_repetida(self, banco):
        with pytest.raises(imp.ArquivoInvalido, match='repetida'):
            imp.ler_csv(csv_em(banco, 'X;Y;1;Torno Horizontal;60;', cab=CAB + ';nome'))

    def test_csv_do_excel_em_windows_1252_le_os_acentos(self, banco):
        caminho = csv_em(banco, 'X-1;Peça Nova;1;Torno Horizontal;60;Usinagem cilíndrica', codificacao='cp1252')
        linhas, codificacao, _ = imp.ler_csv(caminho)
        assert 'Windows-1252' in codificacao
        assert linhas[0][1]['nome'] == 'Peça Nova'
        assert linhas[0][1]['descricao'] == 'Usinagem cilíndrica'

    def test_colunas_extras_sao_ignoradas_e_avisadas(self, banco):
        caminho = csv_em(banco, 'X-1;Peça;1;Torno Horizontal;60;;Setor 1', cab=CAB + ';setor')
        linhas, _, ignoradas = imp.ler_csv(caminho)
        assert ignoradas == ['setor']
        aceitas, recusadas = imp.validar(linhas, maquinas_do_banco())
        assert len(aceitas) == 1 and recusadas == []

    def test_linha_com_mais_colunas_que_o_cabecalho_e_recusada(self, banco):
        caminho = csv_em(banco, 'X-1;Peça;1;Torno Horizontal;60;desc com; ponto e vírgula')
        aceitas, recusadas = validar_arquivo(caminho)
        assert aceitas == []
        assert "algum texto tem ';'" in recusadas[0]['motivos'][0]

    def test_linhas_em_branco_sao_ignoradas(self, banco):
        caminho = csv_em(banco, '', 'X-1;Peça;1;Torno Horizontal;60;', ';;;;;')
        aceitas, recusadas = validar_arquivo(caminho)
        assert len(aceitas) == 1 and recusadas == []


class TestValidacao:
    @pytest.mark.parametrize('linhas, trecho', [
        (['X-1;Peça;1;Máquina Fantasma;60;'], "não existe em maquinas"),
        (['X-1;Peça;1;Torno Horizontal;60;', 'X-1;Peça;3;Torno Vertical;30;'], 'faltam 2'),
        (['X-1;Peça;2;Torno Horizontal;60;'], 'faltam 1'),
        (['X-1;Peça;1;Torno Horizontal;60;', 'X-1;Peça;3;Torno Vertical;30;', 'X-1;Peça;5;Serra de Fita;9;'], 'faltam 2, 4'),
        (['X-1;Peça;1;Torno Horizontal;60;', 'X-1;Peça;1;Torno Vertical;30;'], 'repetida'),
        (['X-1;Peça;0;Torno Horizontal;60;'], "sequencia '0' inválida"),
        (['X-1;Peça;-1;Torno Horizontal;60;'], "sequencia '-1' inválida"),
        (['X-1;Peça;a;Torno Horizontal;60;'], "sequencia 'a' inválida"),
        (['X-1;Peça;1.0;Torno Horizontal;60;'], "sequencia '1.0' inválida"),
        (['X-1;Peça;1;Torno Horizontal;0;'], "tempo_estimado_min '0' inválido"),
        (['X-1;Peça;1;Torno Horizontal;-5;'], "tempo_estimado_min '-5' inválido"),
        (['X-1;Peça;1;Torno Horizontal;90,5;'], "tempo_estimado_min '90,5' inválido"),
        (['X-1;Peça;1;Torno Horizontal;muito;'], "tempo_estimado_min 'muito' inválido"),
        (['X-1;Peça;1;Torno Horizontal;;'], 'tempo_estimado_min'),
        (['X-1;Peça;1;;60;'], 'maquina vazia'),
        (['X-1;;1;Torno Horizontal;60;'], 'nome vazio'),
        (['X-1;A;1;Torno Horizontal;60;', 'X-1;B;2;Torno Vertical;30;'], 'nome diferente entre as linhas'),
        ([';Peça;1;Torno Horizontal;60;'], 'código vazio'),
    ])
    def test_recusa_com_motivo(self, banco, linhas, trecho):
        aceitas, recusadas = validar_arquivo(csv_em(banco, *linhas))
        assert aceitas == []
        assert any(trecho in m for r in recusadas for m in r['motivos']), recusadas

    def test_sequencia_fora_de_ordem_e_aceita_e_ordenada(self, banco):
        aceitas, recusadas = validar_arquivo(csv_em(
            banco, 'X-1;Peça;2;Torno Vertical;30;b', 'X-1;Peça;1;Torno Horizontal;60;a'))
        assert recusadas == []
        assert [o['sequencia'] for o in aceitas[0]['ops']] == [1, 2]

    def test_maquina_com_outra_caixa_e_gravada_com_o_nome_do_banco(self, banco):
        aceitas, recusadas = validar_arquivo(csv_em(banco, 'X-1;Peça;1;torno horizontal;60;'))
        assert recusadas == []
        assert aceitas[0]['ops'][0]['maquina'] == 'Torno Horizontal'
        assert "gravada como 'Torno Horizontal'" in aceitas[0]['avisos'][0]

    def test_uma_peca_ruim_nao_bloqueia_as_boas(self, banco):
        aceitas, recusadas = validar_arquivo(csv_em(
            banco,
            'BOA-1;Boa;1;Torno Horizontal;60;',
            'RUIM-1;Ruim;1;Máquina Fantasma;60;',
            'BOA-2;Outra boa;1;Serra de Fita;30;'))
        assert [p['codigo'] for p in aceitas] == ['BOA-1', 'BOA-2']
        assert [r['codigo'] for r in recusadas] == ['RUIM-1']

    def test_todos_os_problemas_da_peca_sao_listados(self, banco):
        _, recusadas = validar_arquivo(csv_em(
            banco,
            'X-1;Peça;1;Máquina Fantasma;60;',
            'X-1;Peça;3;Torno Vertical;zero;'))
        motivos = ' | '.join(recusadas[0]['motivos'])
        assert 'linha 2' in motivos and 'linha 3' in motivos
        assert 'não existe em maquinas' in motivos and 'tempo_estimado_min' in motivos
        assert 'buraco' in motivos


class TestGravacao:
    def test_peca_nova_entra_e_e_planejavel(self, banco):
        caminho = csv_em(banco,
                         'Z-100;Peça Z;1;Torno CNC Cilindros;60;Desbaste',
                         'Z-100;Peça Z;2;Retificadora Cilíndrica;45;Acabamento')
        assert imp.main([caminho]) == 0
        assert roteiro('Z-100') == [(1, 'Torno CNC Cilindros', 60, 'Desbaste'),
                                    (2, 'Retificadora Cilíndrica', 45, 'Acabamento')]

        conn = app_module.get_db()
        try:
            nota_id = conn.execute('''INSERT INTO notas (numero, peca_codigo, quantidade, status)
                                      VALUES ('TESTE-IMP-1', 'Z-100', 1, 'RECEBIDA')''').lastrowid
            conn.commit()
        finally:
            conn.close()
        resultado = app_module.AutomacaoUsinagem.processar_nota(nota_id)
        assert resultado['status'] == 'SUCESSO'
        assert [o['maquina'] for o in resultado['operacoes']] == ['Torno CNC Cilindros', 'Retificadora Cilíndrica']

    def test_peca_existente_troca_o_roteiro_e_apaga_sequencias_que_sumiram(self, banco):
        ids_antes = consultar('SELECT id FROM operacoes WHERE peca_id = (SELECT id FROM pecas WHERE codigo = ?) ORDER BY sequencia',
                              '40-091799')
        caminho = csv_em(banco, '40-091799;Placa Bronze B;1;Torno CNC Cilindros;45;Novo desbaste')
        assert imp.main([caminho]) == 0
        assert roteiro('40-091799') == [(1, 'Torno CNC Cilindros', 45, 'Novo desbaste')]
        assert consultar('SELECT nome FROM pecas WHERE codigo = ?', '40-091799') == [('Placa Bronze B',)]
        ids_depois = consultar('SELECT id FROM operacoes WHERE peca_id = (SELECT id FROM pecas WHERE codigo = ?)',
                               '40-091799')
        assert ids_depois == ids_antes[:1]          # a sequência mantida conserva o id

    def test_atualizacao_descreve_o_que_mudou(self, banco, capsys):
        caminho = csv_em(banco,
                         '40-091799;Placa Bronze A;1;Torno Horizontal;150;Usinagem cilíndrica',
                         '40-091799;Placa Bronze A;2;Serra de Fita;90;Acabamento superficial')
        assert imp.main([caminho]) == 0
        saida = capsys.readouterr().out
        assert '[atualizada]' in saida
        assert 'tempo 120 -> 150 min' in saida
        assert "maquina 'Torno Vertical' -> 'Serra de Fita'" in saida

    def test_simular_nao_grava_nada(self, banco, capsys):
        antes = consultar('SELECT * FROM operacoes ORDER BY id'), consultar('SELECT * FROM pecas ORDER BY id')
        caminho = csv_em(banco, 'Z-100;Peça Z;1;Torno CNC Cilindros;60;', '40-091799;Placa Bronze A;1;Serra de Fita;5;')
        assert imp.main([caminho, '--simular']) == 0
        assert (consultar('SELECT * FROM operacoes ORDER BY id'), consultar('SELECT * FROM pecas ORDER BY id')) == antes
        assert consultar("SELECT COUNT(*) FROM auditoria WHERE tipo_evento = 'IMPORTACAO_CATALOGO'") == [(0,)]
        saida = capsys.readouterr().out
        assert 'SERIAM IMPORTADAS' in saida and '[SIMULAÇÃO]' in saida

    def test_importar_duas_vezes_e_idempotente(self, banco, capsys):
        caminho = csv_em(banco, 'Z-100;Peça Z;1;Torno CNC Cilindros;60;Desbaste')
        assert imp.main([caminho]) == 0
        assert imp.main([caminho]) == 0
        assert '[sem mudanças]' in capsys.readouterr().out
        assert consultar("SELECT COUNT(*) FROM auditoria WHERE tipo_evento = 'IMPORTACAO_CATALOGO'") == [(1,)]
        assert consultar("SELECT COUNT(*) FROM pecas WHERE codigo = 'Z-100'") == [(1,)]

    def test_peca_recusada_nao_deixa_roteiro_pela_metade(self, banco):
        caminho = csv_em(banco,
                         'BOA-1;Boa;1;Torno Horizontal;60;',
                         'RUIM-1;Ruim;1;Torno Horizontal;60;',
                         'RUIM-1;Ruim;3;Torno Vertical;30;')
        assert imp.main([caminho]) == 1
        assert roteiro('BOA-1') == [(1, 'Torno Horizontal', 60, None)]
        assert consultar("SELECT COUNT(*) FROM pecas WHERE codigo = 'RUIM-1'") == [(0,)]
        assert roteiro('RUIM-1') == []

    def test_recusar_uma_peca_existente_nao_altera_o_roteiro_dela(self, banco):
        antes = roteiro('40-091799')
        caminho = csv_em(banco, '40-091799;Placa Bronze A;1;Máquina Fantasma;60;')
        assert imp.main([caminho]) == 1
        assert roteiro('40-091799') == antes

    def test_auditoria_registra_peca_nova_e_atualizada(self, banco):
        caminho = csv_em(banco,
                         'Z-100;Peça Z;1;Torno CNC Cilindros;60;',
                         '40-154120;Mancal Inferior;1;Retificadora Cilíndrica;210;Polimento fino')
        assert imp.main([caminho]) == 0
        eventos = consultar("SELECT descricao FROM auditoria WHERE tipo_evento = 'IMPORTACAO_CATALOGO' ORDER BY id")
        assert len(eventos) == 2
        assert 'Z-100 nova' in eventos[0][0] and '40-154120 atualizada' in eventos[1][0]

    def test_codigos_de_saida(self, banco):
        assert imp.main([csv_em(banco, 'A-1;A;1;Torno Horizontal;60;')]) == 0
        assert imp.main([csv_em(banco, 'A-2;A;1;Fantasma;60;', nome='b.csv')]) == 1
        assert imp.main([str(banco / 'nao_existe.csv')]) == 2


class TestSemeaduraNaoDesfazImportacao:
    """seed_data() roda a cada partida do app: não pode sobrescrever o que o
    catálogo importado definiu."""

    def test_seed_data_nao_desfaz_roteiro_importado(self, banco):
        caminho = csv_em(banco, '40-091799;Placa Bronze A;1;Torno CNC Cilindros;45;Novo')
        assert imp.main([caminho]) == 0
        app_module.seed_data()
        app_module.seed_data()
        assert roteiro('40-091799') == [(1, 'Torno CNC Cilindros', 45, 'Novo')]

    def test_seed_data_semeia_roteiro_de_peca_sem_operacoes(self, banco):
        conn = app_module.get_db()
        try:
            conn.execute("DELETE FROM operacoes WHERE peca_id = (SELECT id FROM pecas WHERE codigo = '40-122633')")
            conn.commit()
        finally:
            conn.close()
        app_module.seed_data()
        assert roteiro('40-122633') == [(1, 'Fresadora Universal', 150, 'Usinagem em fresadora')]

    def test_seed_data_ainda_migra_nomes_antigos_de_maquina(self, banco):
        conn = app_module.get_db()
        try:
            conn.execute("UPDATE operacoes SET maquina = 'FRESADORA' WHERE maquina = 'Fresadora Universal'")
            conn.commit()
        finally:
            conn.close()
        app_module.seed_data()
        assert roteiro('40-122633')[0][1] == 'Fresadora Universal'
