"""Testes do interpretador de máquina por palavra-chave (interpretador.py).

Isolado de propósito: não importa app.py, não abre banco, não fala com o
Telegram. Só a função pura interpretar_maquina().
"""
import pytest

from interpretador import PALAVRAS_CHAVE, interpretar_maquina

TODAS_AS_8 = [
    'Torno Horizontal', 'Torno Vertical', 'Fresadora Universal', 'Mandrilhadora',
    'Furadeira Radial', 'Serra de Fita', 'Torno CNC Cilindros', 'Retificadora Cilíndrica',
]


class TestCadaMaquinaTemPalavraChaveUnica:
    """As 8 máquinas reais (fotos_maquinas/, seed_data) precisam continuar
    reconhecíveis: se alguém editar PALAVRAS_CHAVE e colidir duas máquinas,
    isso tem que aparecer aqui, não só na hora de usar o bot."""

    def test_todas_as_8_maquinas_estao_no_dicionario(self):
        assert set(PALAVRAS_CHAVE) == set(TODAS_AS_8)

    @pytest.mark.parametrize('maquina', TODAS_AS_8)
    def test_nome_completo_da_maquina_resolve_para_ela_mesma(self, maquina):
        assert interpretar_maquina(maquina) == maquina

    @pytest.mark.parametrize('maquina', TODAS_AS_8)
    def test_cada_palavra_chave_resolve_so_para_a_sua_maquina(self, maquina):
        for palavra in PALAVRAS_CHAVE[maquina]:
            assert interpretar_maquina(palavra) == maquina, f"'{palavra}' deveria apontar para {maquina}"


class TestCasosDoBrief:
    """Exemplos literais da seção 5 do brief."""

    def test_a_serra_ta_vibrando_muito(self):
        assert interpretar_maquina('a serra tá vibrando muito') == 'Serra de Fita'

    def test_frase_livre_com_torno_vertical(self):
        assert interpretar_maquina('acho que é o torno vertical que travou') == 'Torno Vertical'


class TestNormalizacao:
    def test_maiusculas(self):
        assert interpretar_maquina('SERRA DE FITA') == 'Serra de Fita'

    def test_sem_acento(self):
        assert interpretar_maquina('retifica') == 'Retificadora Cilíndrica'
        assert interpretar_maquina('RETÍFICA') == 'Retificadora Cilíndrica'

    def test_espacos_extras(self):
        assert interpretar_maquina('  torno   horizontal  ') == 'Torno Horizontal'


class TestAmbiguoOuSemMatch:
    def test_torno_sozinho_e_ambiguo(self):
        """'torno' bate com 3 máquinas (horizontal/vertical/CNC) — nenhuma
        palavra-chave é só 'torno', então isto não bate com nenhuma delas
        sozinho: é o comportamento certo (mostrar os botões), não um match
        de 3 vias por acidente."""
        assert interpretar_maquina('preciso usar o torno') is None

    def test_duas_maquinas_na_mesma_frase_e_ambiguo(self):
        assert interpretar_maquina('a serra e a fresadora pararam') is None

    def test_texto_sem_nenhuma_maquina(self):
        assert interpretar_maquina('o café acabou de novo') is None

    def test_string_vazia(self):
        assert interpretar_maquina('') is None

    def test_none(self):
        assert interpretar_maquina(None) is None

    def test_so_espacos(self):
        assert interpretar_maquina('   ') is None


class TestNomesDisponiveis:
    """Restringe a busca à lista vinda do banco (maquinas.nome hoje)."""

    def test_maquina_fora_da_lista_disponivel_nao_conta(self):
        assert interpretar_maquina('serra de fita', nomes_disponiveis=['Torno Horizontal']) is None

    def test_maquina_dentro_da_lista_disponivel_resolve(self):
        assert interpretar_maquina('serra de fita', nomes_disponiveis=TODAS_AS_8) == 'Serra de Fita'

    def test_lista_vazia_nunca_resolve(self):
        assert interpretar_maquina('serra de fita', nomes_disponiveis=[]) is None
