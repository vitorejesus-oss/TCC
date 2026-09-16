"""
Testes Unitários - Sistema de Automação de Usinagem
Pytest coverage dos endpoints principais e dos diferenciais
"""

import io
import json

import pytest

from app import app, init_db, seed_data, seed_usuarios


@pytest.fixture
def client():
    """Setup do cliente de teste"""
    app.config['TESTING'] = True
    with app.app_context():
        init_db()
        seed_data()
        seed_usuarios()
        with app.test_client() as client:
            yield client


class TestHealth:
    """Testes de Health Check"""

    def test_health_check(self, client):
        """Verifica se API está online"""
        response = client.get('/api/health')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'OK'


class TestPecas:
    """Testes de Peças"""

    def test_listar_pecas(self, client):
        """Verifica se lista peças"""
        response = client.get('/api/pecas')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data) > 0
        assert data[0]['codigo']


class TestMaquinas:
    """Testes de Máquinas"""

    def test_listar_maquinas(self, client):
        """Verifica se lista máquinas"""
        response = client.get('/api/maquinas')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data) > 0
        assert data[0]['nome']
        assert data[0]['status'] == 'DISPONIVEL'


class TestNotas:
    """Testes de Notas"""

    def test_listar_notas(self, client):
        """Verifica se lista notas"""
        response = client.get('/api/notas')
        assert response.status_code == 200

    def test_criar_nota(self, client):
        """Verifica criação automática de nota e OS"""
        payload = {
            'peca_codigo': '40-091799',
            'quantidade': 1,
            'prioridade': 'NORMAL',
            'solicitante': 'TESTE'
        }
        response = client.post('/api/notas',
                             data=json.dumps(payload),
                             content_type='application/json')

        assert response.status_code == 201
        data = json.loads(response.data)
        assert 'nota_id' in data
        assert 'numero' in data
        assert 'processamento' in data
        assert data['processamento']['status'] == 'SUCESSO'
        assert 'os_numero' in data['processamento']

    def test_criar_nota_sem_peca_codigo_retorna_erro_de_validacao(self, client):
        """Validação avançada (diferencial #9) deve barrar payload incompleto"""
        payload = {'quantidade': 1}
        response = client.post('/api/notas',
                             data=json.dumps(payload),
                             content_type='application/json')

        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'erros' in data

    def test_criar_nota_quantidade_invalida_retorna_erro(self, client):
        """quantidade <= 0 deve ser rejeitada"""
        payload = {'peca_codigo': '40-091799', 'quantidade': 0}
        response = client.post('/api/notas',
                             data=json.dumps(payload),
                             content_type='application/json')

        assert response.status_code == 400


class TestOrdens:
    """Testes de Ordens de Serviço"""

    def test_listar_ordens(self, client):
        """Verifica se lista ordens"""
        response = client.get('/api/ordens-servico')
        assert response.status_code == 200

    def test_criar_nota_gera_os(self, client):
        """Verifica se criar nota gera OS automaticamente"""
        payload = {
            'peca_codigo': '40-122633',
            'quantidade': 1,
            'prioridade': 'URGENTE',
            'solicitante': 'TESTE'
        }
        response = client.post('/api/notas',
                             data=json.dumps(payload),
                             content_type='application/json')

        data = json.loads(response.data)
        os_numero = data['processamento']['os_numero']

        response = client.get('/api/ordens-servico')
        ordens = json.loads(response.data)

        ordem_encontrada = any(o['numero'] == os_numero for o in ordens)
        assert ordem_encontrada


class TestMetricas:
    """Testes de Métricas"""

    def test_metricas(self, client):
        """Verifica se retorna métricas calculadas em tempo real"""
        response = client.get('/api/metricas')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'total_notas' in data
        assert 'os_concluidas' in data
        assert 'taxa_aderencia' in data
        assert 'economia_mensal' in data


class TestAuditoria:
    """Testes de Auditoria"""

    def test_auditoria(self, client):
        """Verifica se registra eventos de auditoria"""
        response = client.get('/api/auditoria')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)


class TestIntegracaoSAP:
    """Diferencial #1 - Integração com arquivo SAP"""

    CONTEUDO_SAP = (
        "NOTNUM\tMATERIAL\tQTD\tDUEDATE\tURGENTE\n"
        "NOT-001\t40-091799\t50\t2026-09-16\tS\n"
        "NOT-002\t40-122633\t30\t2026-09-17\tN\n"
        "NOT-003\t40-999999\t5\t2026-09-19\tN\n"
        "NOT-004\t\t20\t2026-09-20\tN\n"
    )

    def test_importar_sap_sem_arquivo(self, client):
        """Sem o campo 'arquivo' deve retornar 400"""
        response = client.post('/api/sap/importar')
        assert response.status_code == 400

    def test_importar_sap_arquivo(self, client):
        """Processa um arquivo SAP com linhas válidas, inválidas e peça desconhecida"""
        data = {
            'arquivo': (io.BytesIO(self.CONTEUDO_SAP.encode('utf-8')), 'sap_test.txt')
        }
        response = client.post('/api/sap/importar',
                             data=data,
                             content_type='multipart/form-data')

        assert response.status_code == 200
        resultado = json.loads(response.data)
        assert resultado['sucesso'] is True
        assert resultado['total_processadas'] == 3
        assert len(resultado['erros']) == 1
        assert any(not n['peca_encontrada'] for n in resultado['notas'])
        assert any(n['peca_encontrada'] and n.get('os_numero') for n in resultado['notas'])


class TestAlertaEmail:
    """Diferencial #2 - Alertas por email"""

    def test_alerta_sem_campos_obrigatorios(self, client):
        response = client.post('/api/alerta/email',
                             data=json.dumps({}),
                             content_type='application/json')
        assert response.status_code == 400

    def test_alerta_sem_credenciais_configuradas(self, client, monkeypatch):
        """Sem EMAIL_USUARIO/EMAIL_SENHA no ambiente, o envio deve falhar de forma controlada"""
        monkeypatch.delenv('EMAIL_USUARIO', raising=False)
        monkeypatch.delenv('EMAIL_SENHA', raising=False)

        payload = {
            'destinatario': 'teste@example.com',
            'assunto': 'Teste',
            'corpo': 'Mensagem de teste',
            'tipo': 'info'
        }
        response = client.post('/api/alerta/email',
                             data=json.dumps(payload),
                             content_type='application/json')

        assert response.status_code == 502
        data = json.loads(response.data)
        assert data['enviado'] is False


class TestRelatorioPDF:
    """Diferencial #3 - Gerador de relatório em PDF"""

    def test_gerar_relatorio_economia(self, client):
        response = client.get('/api/relatorio/economia?mes=Janeiro&ano=2026')
        assert response.status_code == 200
        assert response.mimetype == 'application/pdf'
        assert len(response.data) > 0


class TestAutenticacao:
    """Diferencial #5 - Autenticação JWT + papéis"""

    def test_login_sucesso(self, client):
        response = client.post('/api/auth/login',
                             data=json.dumps({'email': 'operador@fabrica.com', 'senha': 'Vitor367'}),
                             content_type='application/json')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['role'] == 'operador'
        assert 'token' in data

    def test_login_senha_incorreta(self, client):
        response = client.post('/api/auth/login',
                             data=json.dumps({'email': 'operador@fabrica.com', 'senha': 'errada'}),
                             content_type='application/json')
        assert response.status_code == 401

    def test_painel_sem_token_e_negado(self, client):
        response = client.get('/api/painel/operador')
        assert response.status_code == 401

    def test_painel_operador_com_token(self, client):
        login = client.post('/api/auth/login',
                          data=json.dumps({'email': 'operador@fabrica.com', 'senha': 'Vitor367'}),
                          content_type='application/json')
        token = json.loads(login.data)['token']

        response = client.get('/api/painel/operador',
                            headers={'Authorization': f'Bearer {token}'})
        assert response.status_code == 200

    def test_painel_gestor_nega_role_operador(self, client):
        login = client.post('/api/auth/login',
                          data=json.dumps({'email': 'operador@fabrica.com', 'senha': 'Vitor367'}),
                          content_type='application/json')
        token = json.loads(login.data)['token']

        response = client.get('/api/painel/gestor',
                            headers={'Authorization': f'Bearer {token}'})
        assert response.status_code == 403


class TestBackup:
    """Diferencial #6 - Backup automático"""

    def test_criar_e_listar_backup(self, client):
        response = client.post('/api/backup/criar')
        assert response.status_code == 201

        response = client.get('/api/backup/listar')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) >= 1


class TestLogs:
    """Diferencial #7 - Logs estruturados"""

    def test_get_logs(self, client):
        response = client.get('/api/logs?limite=10')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)


class TestEstatisticas:
    """Diferencial #10 - Estatísticas customizadas"""

    def test_get_estatisticas(self, client):
        response = client.get('/api/estatisticas')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'desempenho_por_maquina' in data
        assert 'notas_por_operador' in data
        assert 'economia_semanal' in data


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
