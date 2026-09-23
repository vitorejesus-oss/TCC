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


class TestTextoFilaProducao:
    def test_vazia(self):
        assert 'vazia' in bt.texto_fila_producao({'fila_producao': []})

    def test_com_itens(self):
        texto = bt.texto_fila_producao({'fila_producao': [
            {'numero': 'OS-1', 'peca_codigo': '40-091799', 'status': 'USINANDO', 'prioridade': 'NORMAL'}
        ]})
        assert 'OS-1' in texto and '40-091799' in texto


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
