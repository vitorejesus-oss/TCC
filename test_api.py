"""
Testes Unitários - Sistema de Automação de Usinagem
Pytest coverage dos endpoints principais e dos diferenciais
"""

import io
import json
from datetime import date, datetime

import pytest

import app as app_module
from app import (AutomacaoUsinagem, DB_PATH, alinhar_ao_expediente, app, eh_dia_util,
                 feriados_do_ano, get_db, init_db, seed_data, seed_usuarios,
                 somar_expediente)
from clean_sap import limpar_sap


@pytest.fixture
def client():
    """Setup do cliente de teste.

    init_db()/seed_data()/seed_usuarios() são idempotentes, mas não apagam
    notas: se o mesmo usinagem.db já tiver 'SAP-NOT-*' de uma rodada
    anterior de test_importar_sap_arquivo, esse teste vê "já processada" e
    falha. limpar_sap() (clean_sap.py, escrito exatamente para isso, mas
    nunca chamado por nada) resolve isso de uma vez por todas aqui.

    O mesmo problema existe para o vínculo do bot: vinculos_pendentes,
    tentativas_vinculo_telegram e usuarios.telegram_id também não são
    tocados por seed_usuarios(), então uma rodada anterior (bloqueio de
    tentativas, telegram_id já vinculado) vaza para a próxima. Zera os três
    aqui, mesma lógica do limpar_sap().
    """
    app.config['TESTING'] = True
    with app.app_context():
        init_db()
        seed_data()
        seed_usuarios()
        limpar_sap(db_path=DB_PATH)
        conn = get_db()
        conn.execute('DELETE FROM vinculos_pendentes')
        conn.execute('DELETE FROM tentativas_vinculo_telegram')
        conn.execute('UPDATE usuarios SET telegram_id = NULL')
        conn.commit()
        conn.close()
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

    def test_desenho_tecnico_existente(self, client):
        r = client.get('/api/pecas/40-091799/desenho')
        assert r.status_code == 200
        assert r.content_type == 'application/pdf'

    def test_desenho_tecnico_inexistente(self, client):
        r = client.get('/api/pecas/00-000000/desenho')
        assert r.status_code == 404

    @pytest.mark.parametrize('codigo', ['../app', '..%2Fapp.py', '40 091799', '40/091799'])
    def test_desenho_tecnico_codigo_invalido_e_recusado(self, client, codigo):
        r = client.get(f'/api/pecas/{codigo}/desenho')
        assert r.status_code in (400, 404)  # 404 quando a barra nem chega a casar a rota


class TestMaquinas:
    """Testes de Máquinas"""

    def test_listar_maquinas(self, client):
        """Verifica se lista máquinas. Não afirma o status de nenhuma em
        particular: no banco real ele muda com o uso (máquina pode estar
        QUEBRADA de verdade), e travar num valor deixa o teste refém do
        estado ao vivo da demonstração."""
        response = client.get('/api/maquinas')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data) > 0
        for maquina in data:
            assert maquina['nome']
            assert maquina['status'] in ('DISPONIVEL', 'QUEBRADA')


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


class TestPermissoesEtapa0Bot:
    """Etapa 0 do bot do Telegram: requer_roles nos 4 endpoints mutantes que
    antes só exigiam `@jwt_required()` (qualquer papel autenticado passava),
    conforme a tabela de permissões da seção 2 do brief."""

    EMAILS = {'operador': 'operador@fabrica.com', 'coordenador': 'coordenador@fabrica.com',
              'gestor': 'gestor@fabrica.com', 'diretor': 'diretor@fabrica.com'}

    @classmethod
    def _token(cls, client, papel):
        r = client.post('/api/auth/login',
                        data=json.dumps({'email': cls.EMAILS[papel], 'senha': 'Vitor367'}),
                        content_type='application/json')
        return json.loads(r.data)['token']

    @staticmethod
    def _maquina_id(client):
        return json.loads(client.get('/api/maquinas').data)[0]['id']

    @staticmethod
    def _nova_alocacao(client):
        """Cria uma nota (peça com roteiro de 2 operações) e devolve o id da
        primeira alocação gerada, sempre nova e sem inicio_real."""
        r = client.post('/api/notas',
                        data=json.dumps({'peca_codigo': '40-091799', 'quantidade': 1}),
                        content_type='application/json')
        os_id = json.loads(r.data)['processamento']['os_id']
        ops = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)
        return ops[0]['id']

    @pytest.mark.parametrize('papel', ['gestor', 'diretor'])
    def test_gestor_e_diretor_nao_iniciam_operacao(self, client, papel):
        alocacao_id = self._nova_alocacao(client)
        token = self._token(client, papel)
        r = client.post(f'/api/alocacoes/{alocacao_id}/iniciar', headers={'Authorization': f'Bearer {token}'})
        assert r.status_code == 403

    @pytest.mark.parametrize('papel', ['gestor', 'diretor'])
    def test_gestor_e_diretor_nao_concluem_operacao(self, client, papel):
        alocacao_id = self._nova_alocacao(client)
        token = self._token(client, papel)
        r = client.post(f'/api/alocacoes/{alocacao_id}/concluir', headers={'Authorization': f'Bearer {token}'})
        assert r.status_code == 403

    @pytest.mark.parametrize('papel', ['operador', 'coordenador'])
    def test_operador_e_coordenador_iniciam_e_concluem_operacao(self, client, papel):
        alocacao_id = self._nova_alocacao(client)
        token = self._token(client, papel)
        headers = {'Authorization': f'Bearer {token}'}
        r = client.post(f'/api/alocacoes/{alocacao_id}/iniciar', headers=headers)
        assert r.status_code == 200, r.data
        r = client.post(f'/api/alocacoes/{alocacao_id}/concluir', headers=headers,
                        data=json.dumps({}), content_type='application/json')
        assert r.status_code == 200, r.data

    @pytest.mark.parametrize('papel', ['gestor', 'diretor'])
    def test_gestor_e_diretor_nao_reportam_quebra(self, client, papel):
        maquina_id = self._maquina_id(client)
        token = self._token(client, papel)
        r = client.post(f'/api/maquinas/{maquina_id}/quebrada', headers={'Authorization': f'Bearer {token}'})
        assert r.status_code == 403

    @pytest.mark.parametrize('papel', ['operador', 'coordenador'])
    def test_operador_e_coordenador_reportam_quebra(self, client, papel):
        maquina_id = self._maquina_id(client)
        token = self._token(client, papel)
        r = client.post(f'/api/maquinas/{maquina_id}/quebrada', headers={'Authorization': f'Bearer {token}'})
        assert r.status_code == 200, r.data

    @pytest.mark.parametrize('papel', ['operador', 'gestor', 'diretor'])
    def test_so_coordenador_registra_conserto(self, client, papel):
        maquina_id = self._maquina_id(client)
        token = self._token(client, papel)
        r = client.post(f'/api/maquinas/{maquina_id}/consertada', headers={'Authorization': f'Bearer {token}'},
                        data=json.dumps({'relatorio': 'teste'}), content_type='application/json')
        assert r.status_code == 403

    def test_coordenador_registra_conserto(self, client):
        maquina_id = self._maquina_id(client)
        token = self._token(client, 'coordenador')
        r = client.post(f'/api/maquinas/{maquina_id}/consertada', headers={'Authorization': f'Bearer {token}'},
                        data=json.dumps({'relatorio': 'teste'}), content_type='application/json')
        assert r.status_code == 200, r.data


class TestAuditoriaUsuarioECanal:
    """registrar_auditoria grava quem agiu e por qual canal (Etapa 0 do bot)."""

    @staticmethod
    def _ultimo_evento(client, tipo_evento):
        eventos = json.loads(client.get('/api/auditoria').data)
        for e in eventos:
            if e['tipo_evento'] == tipo_evento:
                return e
        return None

    def test_login_grava_usuario_e_canal_web(self, client):
        client.post('/api/auth/login',
                    data=json.dumps({'email': 'operador@fabrica.com', 'senha': 'Vitor367'}),
                    content_type='application/json')
        evento = self._ultimo_evento(client, 'LOGIN')
        assert evento is not None
        assert evento['usuario'] == 'operador@fabrica.com'
        assert evento['canal'] == 'WEB'

    def test_acao_sem_usuario_autenticado_grava_sistema(self, client):
        """POST /api/notas não exige login: quem processa é o sistema."""
        client.post('/api/notas', data=json.dumps({'peca_codigo': '40-091799', 'quantidade': 1}),
                   content_type='application/json')
        evento = self._ultimo_evento(client, 'PROCESSAMENTO')
        assert evento is not None
        assert evento['usuario'] == 'SISTEMA'
        assert evento['canal'] == 'WEB'

    def test_quebra_e_conserto_gravam_o_coordenador_que_agiu(self, client):
        maquina_id = json.loads(client.get('/api/maquinas').data)[0]['id']
        login = client.post('/api/auth/login',
                           data=json.dumps({'email': 'coordenador@fabrica.com', 'senha': 'Vitor367'}),
                           content_type='application/json')
        token = json.loads(login.data)['token']
        headers = {'Authorization': f'Bearer {token}'}

        r = client.post(f'/api/maquinas/{maquina_id}/quebrada', headers=headers)
        assert r.status_code == 200, r.data
        evento = self._ultimo_evento(client, 'MAQUINA_QUEBRADA')
        assert evento['usuario'] == 'coordenador@fabrica.com'

        r = client.post(f'/api/maquinas/{maquina_id}/consertada', headers=headers,
                       data=json.dumps({'relatorio': 'ok'}), content_type='application/json')
        assert r.status_code == 200, r.data
        evento = self._ultimo_evento(client, 'MAQUINA_CONSERTADA')
        assert evento['usuario'] == 'coordenador@fabrica.com'
        assert evento['canal'] == 'WEB'


class TestBotTelegramEtapa1:
    """Vínculo de conta (Etapa 1 do bot): gerar-codigo, vincular, token."""

    TOKEN_SERVICO = 'teste-token-de-servico-bot'

    @pytest.fixture(autouse=True)
    def servico_configurado(self, monkeypatch):
        monkeypatch.setattr(app_module, 'BOT_SERVICE_TOKEN', self.TOKEN_SERVICO)

    def _jwt_site(self, client, email='operador@fabrica.com'):
        r = client.post('/api/auth/login', data=json.dumps({'email': email, 'senha': 'Vitor367'}),
                        content_type='application/json')
        return json.loads(r.data)['token']

    def _gerar_codigo(self, client, email='operador@fabrica.com'):
        token = self._jwt_site(client, email)
        r = client.post('/api/telegram/gerar-codigo', headers={'Authorization': f'Bearer {token}'})
        assert r.status_code == 201, r.data
        return json.loads(r.data)

    def _vincular(self, client, codigo, telegram_id=555, token_servico=None):
        headers = {'X-Bot-Token': self.TOKEN_SERVICO if token_servico is None else token_servico}
        return client.post('/api/telegram/vincular', headers=headers,
                          data=json.dumps({'codigo': codigo, 'telegram_id': telegram_id}),
                          content_type='application/json')

    # --- gerar-codigo ---------------------------------------------------

    def test_gerar_codigo_exige_login(self, client):
        assert client.post('/api/telegram/gerar-codigo').status_code == 401

    def test_gerar_codigo_tem_6_digitos_e_validade(self, client):
        dados = self._gerar_codigo(client)
        assert len(dados['codigo']) == 6 and dados['codigo'].isdigit()
        assert dados['validade_minutos'] == 10

    def test_gerar_codigo_de_novo_invalida_o_anterior(self, client):
        primeiro = self._gerar_codigo(client)['codigo']
        segundo = self._gerar_codigo(client)['codigo']
        assert self._vincular(client, primeiro).status_code == 400
        assert self._vincular(client, segundo, telegram_id=556).status_code == 200

    # --- vincular ---------------------------------------------------------

    def test_criado_em_e_expira_em_em_hora_local(self, client):
        from datetime import datetime
        antes = datetime.now().replace(microsecond=0)
        self._gerar_codigo(client)
        conn = app_module.get_db()
        linha = conn.execute('SELECT criado_em, expira_em FROM vinculos_pendentes').fetchone()
        conn.close()
        criado = datetime.fromisoformat(linha['criado_em'])
        expira = datetime.fromisoformat(linha['expira_em'])
        assert 0 <= (criado - antes).total_seconds() < 5  # UTC daria horas de diferença (exceto fuso UTC)
        assert (expira - criado).total_seconds() == pytest.approx(app_module.VINCULO_CODIGO_EXPIRA_MIN * 60, abs=1)

    def test_status_sem_token_401(self, client):
        assert client.get('/api/telegram/status').status_code == 401

    def test_status_reflete_o_vinculo(self, client):
        h = {'Authorization': f'Bearer {self._jwt_site(client, "coordenador@fabrica.com")}'}
        assert json.loads(client.get('/api/telegram/status', headers=h).data)['vinculado'] is False
        codigo = self._gerar_codigo(client, 'coordenador@fabrica.com')['codigo']
        assert self._vincular(client, codigo, telegram_id=777001).status_code == 200
        assert json.loads(client.get('/api/telegram/status', headers=h).data)['vinculado'] is True

    def test_vincular_sem_token_de_servico_e_negado(self, client):
        codigo = self._gerar_codigo(client)['codigo']
        r = self._vincular(client, codigo, token_servico='')
        assert r.status_code == 401

    def test_vincular_com_token_de_servico_errado_e_negado(self, client):
        codigo = self._gerar_codigo(client)['codigo']
        r = self._vincular(client, codigo, token_servico='chute-qualquer')
        assert r.status_code == 401

    def test_vincular_com_bot_service_token_vazio_no_ambiente_nega_tudo(self, client, monkeypatch):
        monkeypatch.setattr(app_module, 'BOT_SERVICE_TOKEN', None)
        codigo = self._gerar_codigo(client)['codigo']
        assert self._vincular(client, codigo, token_servico='qualquer-coisa').status_code == 401
        assert self._vincular(client, codigo, token_servico='').status_code == 401

    def test_vincular_codigo_certo(self, client):
        codigo = self._gerar_codigo(client)['codigo']
        r = self._vincular(client, codigo, telegram_id=999)
        assert r.status_code == 200
        assert json.loads(r.data) == {'nome': 'operador@fabrica.com', 'role': 'operador'}

        conn = get_db()
        try:
            row = conn.execute('SELECT telegram_id FROM usuarios WHERE email = ?',
                              ('operador@fabrica.com',)).fetchone()
            assert row['telegram_id'] == 999
            assert conn.execute('SELECT COUNT(*) c FROM vinculos_pendentes').fetchone()['c'] == 0
        finally:
            conn.close()

    def test_vincular_codigo_e_uso_unico(self, client):
        codigo = self._gerar_codigo(client)['codigo']
        assert self._vincular(client, codigo, telegram_id=201).status_code == 200
        r = self._vincular(client, codigo, telegram_id=202)
        assert r.status_code == 400
        assert 'inválido' in json.loads(r.data)['erro'] or 'expirado' in json.loads(r.data)['erro']

    def test_vincular_codigo_errado(self, client):
        self._gerar_codigo(client)
        r = self._vincular(client, '000000', telegram_id=203)
        assert r.status_code == 400

    def test_vincular_codigo_expirado(self, client):
        dados = self._gerar_codigo(client)
        conn = get_db()
        try:
            conn.execute("UPDATE vinculos_pendentes SET expira_em = ? WHERE codigo = ?",
                        ('2000-01-01T00:00:00', dados['codigo']))
            conn.commit()
        finally:
            conn.close()
        assert self._vincular(client, dados['codigo'], telegram_id=204).status_code == 400

    def test_mesmo_telegram_id_nao_vincula_duas_contas(self, client):
        cod_operador = self._gerar_codigo(client, 'operador@fabrica.com')['codigo']
        assert self._vincular(client, cod_operador, telegram_id=42).status_code == 200
        cod_coord = self._gerar_codigo(client, 'coordenador@fabrica.com')['codigo']
        r = self._vincular(client, cod_coord, telegram_id=42)
        assert r.status_code == 409

    def test_tentativas_erradas_bloqueiam_depois_de_5(self, client, monkeypatch):
        monkeypatch.setattr(app_module, 'VINCULO_MAX_TENTATIVAS', 5)
        codigo_valido = self._gerar_codigo(client)['codigo']
        for _ in range(5):
            r = self._vincular(client, '000000', telegram_id=77)
            assert r.status_code == 400
        # 6a tentativa: mesmo com o codigo CERTO, o telegram_id ja esta bloqueado
        r = self._vincular(client, codigo_valido, telegram_id=77)
        assert r.status_code == 429

    def test_tentativas_de_um_telegram_id_nao_afetam_outro(self, client):
        for _ in range(5):
            assert self._vincular(client, '000000', telegram_id=205).status_code == 400
        codigo = self._gerar_codigo(client)['codigo']
        assert self._vincular(client, codigo, telegram_id=206).status_code == 200

    # --- token --------------------------------------------------------------

    def test_token_exige_bot_service_token(self, client):
        codigo = self._gerar_codigo(client)['codigo']
        self._vincular(client, codigo, telegram_id=10)
        r = client.post('/api/telegram/token', data=json.dumps({'telegram_id': 10}),
                       content_type='application/json')
        assert r.status_code == 401

    def test_token_para_quem_nao_vinculou_falha(self, client):
        r = client.post('/api/telegram/token', headers={'X-Bot-Token': self.TOKEN_SERVICO},
                       data=json.dumps({'telegram_id': 123456}), content_type='application/json')
        assert r.status_code == 404

    def test_token_devolve_papel_atual_e_pode_ser_usado_na_api(self, client):
        codigo = self._gerar_codigo(client, 'coordenador@fabrica.com')['codigo']
        self._vincular(client, codigo, telegram_id=11)

        r = client.post('/api/telegram/token', headers={'X-Bot-Token': self.TOKEN_SERVICO},
                       data=json.dumps({'telegram_id': 11}), content_type='application/json')
        assert r.status_code == 200
        dados = json.loads(r.data)
        assert dados['role'] == 'coordenador' and dados['usuario'] == 'coordenador@fabrica.com'

        # o token do bot precisa valer nas MESMAS rotas do site, sem rota nova
        maquina_id = json.loads(client.get('/api/maquinas').data)[0]['id']
        r = client.post(f'/api/maquinas/{maquina_id}/quebrada',
                       headers={'Authorization': f"Bearer {dados['token']}"})
        assert r.status_code == 200, r.data

    def test_token_le_o_papel_na_hora_nao_o_de_quando_vinculou(self, client):
        codigo = self._gerar_codigo(client, 'operador@fabrica.com')['codigo']
        self._vincular(client, codigo, telegram_id=12)

        # Muda o papel do usuário demo DEPOIS do vínculo, pra provar que
        # /token não usa um papel guardado na hora de vincular. Reverte no
        # finally: essa conta é reaproveitada por outros testes na mesma
        # cópia do banco.
        conn = get_db()
        try:
            conn.execute("UPDATE usuarios SET role = 'coordenador' WHERE email = 'operador@fabrica.com'")
            conn.commit()

            r = client.post('/api/telegram/token', headers={'X-Bot-Token': self.TOKEN_SERVICO},
                           data=json.dumps({'telegram_id': 12}), content_type='application/json')
            assert json.loads(r.data)['role'] == 'coordenador'
        finally:
            conn.execute("UPDATE usuarios SET role = 'operador' WHERE email = 'operador@fabrica.com'")
            conn.commit()
            conn.close()

    def test_canal_telegram_aparece_na_auditoria_so_para_acoes_do_bot(self, client):
        codigo = self._gerar_codigo(client, 'coordenador@fabrica.com')['codigo']
        self._vincular(client, codigo, telegram_id=13)
        token_bot = json.loads(client.post(
            '/api/telegram/token', headers={'X-Bot-Token': self.TOKEN_SERVICO},
            data=json.dumps({'telegram_id': 13}), content_type='application/json').data)['token']

        maquina_id = json.loads(client.get('/api/maquinas').data)[0]['id']
        client.post(f'/api/maquinas/{maquina_id}/quebrada', headers={'Authorization': f'Bearer {token_bot}'})

        eventos = json.loads(client.get('/api/auditoria').data)
        via_bot = next(e for e in eventos if e['tipo_evento'] == 'MAQUINA_QUEBRADA')
        assert via_bot['canal'] == 'TELEGRAM'
        assert via_bot['usuario'] == 'coordenador@fabrica.com'

        # a mesma ação pelo site (JWT sem claim canal) continua WEB
        token_web = self._jwt_site(client, 'coordenador@fabrica.com')
        client.post(f'/api/maquinas/{maquina_id}/consertada', headers={'Authorization': f'Bearer {token_web}'},
                   data=json.dumps({'relatorio': 'ok'}), content_type='application/json')
        eventos = json.loads(client.get('/api/auditoria').data)
        via_site = next(e for e in eventos if e['tipo_evento'] == 'MAQUINA_CONSERTADA')
        assert via_site['canal'] == 'WEB'


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


def _auth_papel(client, papel):
    """Header Authorization para o papel (todos os usuários seed usam Vitor367)."""
    r = client.post('/api/auth/login',
                    data=json.dumps({'email': f'{papel}@fabrica.com', 'senha': 'Vitor367'}),
                    content_type='application/json')
    return {'Authorization': f'Bearer {json.loads(r.data)["token"]}'}


class TestEstatisticas:
    """Diferencial #10 - Estatísticas customizadas"""

    def test_get_estatisticas(self, client):
        response = client.get('/api/estatisticas', headers=_auth_papel(client, 'gestor'))
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'desempenho_por_maquina' in data
        assert 'notas_por_operador' in data
        assert 'economia_semanal' in data


class TestPermissoesIndicadores:
    """/api/estatisticas e /api/indicadores/manutencao: só coordenador, gestor e diretor."""

    ROTAS = ['/api/estatisticas', '/api/indicadores/manutencao']

    @pytest.mark.parametrize('rota', ROTAS)
    def test_sem_token_401(self, client, rota):
        assert client.get(rota).status_code == 401

    @pytest.mark.parametrize('rota', ROTAS)
    def test_operador_403(self, client, rota):
        assert client.get(rota, headers=_auth_papel(client, 'operador')).status_code == 403

    @pytest.mark.parametrize('papel', ['coordenador', 'gestor', 'diretor'])
    @pytest.mark.parametrize('rota', ROTAS)
    def test_papeis_permitidos_200(self, client, rota, papel):
        assert client.get(rota, headers=_auth_papel(client, papel)).status_code == 200


class TestOrigemDados:
    """Visibilidade da origem: ?origem=REAL|DEMONSTRACAO|TODAS e o bloco origem_dados"""

    ROTAS = ['/api/metricas', '/api/estatisticas', '/api/indicadores/manutencao']

    @staticmethod
    def _get(client, rota, origem=None):
        resposta = client.get(rota + (f'?origem={origem}' if origem else ''),
                              headers=_auth_papel(client, 'gestor'))
        assert resposta.status_code == 200
        return json.loads(resposta.data)

    @pytest.mark.parametrize('rota', ROTAS)
    def test_bloco_origem_dados_sempre_presente(self, client, rota):
        data = self._get(client, rota)
        assert set(data['origem_dados']) == {'real', 'demonstracao'}

    @pytest.mark.parametrize('rota', ROTAS)
    def test_filtros_particionam_o_total(self, client, rota):
        todas = self._get(client, rota)['origem_dados']
        real = self._get(client, rota, 'REAL')['origem_dados']
        demo = self._get(client, rota, 'DEMONSTRACAO')['origem_dados']
        assert real['demonstracao'] == 0
        assert demo['real'] == 0
        assert todas == {'real': real['real'], 'demonstracao': demo['demonstracao']}

    @pytest.mark.parametrize('rota', ROTAS)
    def test_origem_invalida_retorna_400(self, client, rota):
        assert client.get(rota + '?origem=INVENTADA',
                          headers=_auth_papel(client, 'gestor')).status_code == 400

    def test_registro_de_demonstracao_entra_na_contagem_e_o_filtro_o_separa(self, client):
        """Insere uma nota e um relatório DEMONSTRACAO e confere que aparecem
        (e só aparecem) onde devem, independente do que já houver no banco."""
        from app import get_db

        antes_m = self._get(client, '/api/metricas')['origem_dados']
        antes_r = self._get(client, '/api/indicadores/manutencao')['origem_dados']
        conn = get_db()
        try:
            conn.execute('''INSERT INTO notas (numero, peca_codigo, quantidade, status, origem)
                            VALUES ('TESTE-ORIGEM-1', '40-091799', 1, 'PROCESSADA', 'DEMONSTRACAO')''')
            maquina_id = conn.execute('SELECT id FROM maquinas LIMIT 1').fetchone()[0]
            conn.execute('''INSERT INTO relatorios_manutencao
                            (maquina_id, usuario, descricao, tempo_reparo_min, origem)
                            VALUES (?, 'teste.demo@fabrica.com', 'teste', 30, 'DEMONSTRACAO')''',
                         (maquina_id,))
            conn.commit()

            depois_m = self._get(client, '/api/metricas')['origem_dados']
            depois_r = self._get(client, '/api/indicadores/manutencao')['origem_dados']
            assert depois_m['demonstracao'] == antes_m['demonstracao'] + 1
            assert depois_m['real'] == antes_m['real']
            assert depois_r['demonstracao'] == antes_r['demonstracao'] + 1
            assert depois_r['real'] == antes_r['real']

            so_real = self._get(client, '/api/metricas', 'REAL')
            so_demo = self._get(client, '/api/metricas', 'DEMONSTRACAO')
            assert so_real['origem_dados']['demonstracao'] == 0
            assert so_demo['total_notas'] == so_demo['origem_dados']['demonstracao'] >= 1
        finally:
            conn.execute("DELETE FROM notas WHERE numero = 'TESTE-ORIGEM-1'")
            conn.execute("DELETE FROM relatorios_manutencao WHERE usuario = 'teste.demo@fabrica.com'")
            conn.commit()
            conn.close()

    def test_programacao_traz_origem_dados(self, client):
        data = self._get(client, '/api/programacao')
        assert set(data['origem_dados']) == {'real', 'demonstracao'}


class TestExpediente:
    """Planejamento só em minutos de expediente (seg-sex, 7h-17h por padrão)."""

    # 2026-09-21 é segunda-feira.
    SEG, TER, SEX = (datetime(2026, 9, 21), datetime(2026, 9, 22), datetime(2026, 9, 25))
    SAB, DOM, SEG2 = (datetime(2026, 9, 26), datetime(2026, 9, 27), datetime(2026, 9, 28))

    @pytest.fixture(autouse=True)
    def expediente_padrao(self, monkeypatch):
        import app as app_module
        monkeypatch.setattr(app_module, 'EXPEDIENTE_INICIO_H', 7)
        monkeypatch.setattr(app_module, 'EXPEDIENTE_FIM_H', 17)

    def test_120_min_as_16h_terminam_as_8h_do_dia_util_seguinte(self):
        assert somar_expediente(self.SEG.replace(hour=16), 120) == self.TER.replace(hour=8)

    def test_60_min_as_16h_terminam_no_fechamento_do_mesmo_dia(self):
        assert somar_expediente(self.SEG.replace(hour=16), 60) == self.SEG.replace(hour=17)

    def test_sexta_a_tarde_atravessa_o_fim_de_semana(self):
        assert somar_expediente(self.SEX.replace(hour=16), 120) == self.SEG2.replace(hour=8)

    def test_dia_inteiro_termina_no_fechamento_e_mais_um_minuto_vai_para_o_proximo_dia(self):
        assert somar_expediente(self.SEG.replace(hour=7), 600) == self.SEG.replace(hour=17)
        assert somar_expediente(self.SEG.replace(hour=7), 601) == self.TER.replace(hour=7, minute=1)

    def test_operacao_maior_que_um_dia_consome_varios_expedientes(self):
        assert somar_expediente(self.SEG.replace(hour=7), 700) == self.TER.replace(hour=8, minute=40)

    def test_inicio_fora_do_expediente_empurra_para_a_proxima_abertura(self):
        assert alinhar_ao_expediente(self.SEG.replace(hour=6)) == self.SEG.replace(hour=7)
        assert alinhar_ao_expediente(self.SEG.replace(hour=17)) == self.TER.replace(hour=7)
        assert alinhar_ao_expediente(self.SEG.replace(hour=22)) == self.TER.replace(hour=7)
        assert alinhar_ao_expediente(self.SAB.replace(hour=10)) == self.SEG2.replace(hour=7)
        assert alinhar_ao_expediente(self.DOM.replace(hour=12)) == self.SEG2.replace(hour=7)
        assert alinhar_ao_expediente(self.SEG.replace(hour=10, minute=30)) == self.SEG.replace(hour=10, minute=30)
        assert somar_expediente(self.SAB.replace(hour=10), 60) == self.SEG2.replace(hour=8)

    def test_processar_nota_grava_planejado_so_dentro_do_expediente(self, client):
        """Chama processar_nota direto (a rota POST /api/notas notifica o Telegram)."""
        conn = get_db()
        nota_id = None
        try:
            nota_id = conn.execute('''INSERT INTO notas (numero, peca_codigo, quantidade, status)
                                      VALUES ('TESTE-EXPEDIENTE-1', '40-091799', 1, 'RECEBIDA')''').lastrowid
            conn.commit()
            resultado = AutomacaoUsinagem.processar_nota(nota_id)
            assert resultado['status'] == 'SUCESSO'

            ops = json.loads(client.get(f"/api/ordens-servico/{resultado['os_id']}/operacoes").data)
            assert len(ops) >= 1
            for op in ops:
                ini = datetime.fromisoformat(op['inicio_planejado'])
                fim = datetime.fromisoformat(op['fim_planejado'])
                assert ini.weekday() < 5 and fim.weekday() < 5
                assert 7 <= ini.hour < 17
                assert (7, 0, 0) < (fim.hour, fim.minute, fim.second) <= (17, 0, 0)
                # a duração planejada é a estimada, mesmo que fim - início inclua a noite
                assert op['tempo_planejado_min'] in {o['tempo'] for o in resultado['operacoes']}
        finally:
            if nota_id is not None:
                os_ids = [r[0] for r in conn.execute('SELECT id FROM ordens_servico WHERE nota_id = ?', (nota_id,))]
                for os_id in os_ids:
                    conn.execute('DELETE FROM alocacao_maquinas WHERE ordem_servico_id = ?', (os_id,))
                    conn.execute("DELETE FROM auditoria WHERE entidade = 'ORDEM_SERVICO' AND entidade_id = ?", (os_id,))
                conn.execute('DELETE FROM ordens_servico WHERE nota_id = ?', (nota_id,))
                conn.execute("DELETE FROM auditoria WHERE entidade = 'NOTA' AND entidade_id = ?", (nota_id,))
                conn.execute('DELETE FROM notas WHERE id = ?', (nota_id,))
            conn.commit()
            conn.close()

    def test_programacao_tem_eixo_do_expediente_e_barra_recortada_por_dia(self, client):
        """Operação planejada de 16h a 8h aparece 16-17 num dia e 7-8 no outro."""
        conn = get_db()
        ids = {}
        try:
            ids['nota'] = conn.execute('''INSERT INTO notas (numero, peca_codigo, quantidade, status)
                                          VALUES ('TESTE-EXPEDIENTE-2', '40-091799', 1, 'PROCESSADA')''').lastrowid
            ids['os'] = conn.execute('''INSERT INTO ordens_servico (numero, nota_id, status, prioridade, tempo_total)
                                        VALUES ('TESTE-EXPEDIENTE-OS', ?, 'PLANEJAMENTO', 'NORMAL', 120)''',
                                     (ids['nota'],)).lastrowid
            maquina_id = conn.execute('SELECT id FROM maquinas LIMIT 1').fetchone()[0]
            conn.execute('''INSERT INTO alocacao_maquinas
                            (ordem_servico_id, maquina_id, sequencia, status,
                             inicio_planejado, fim_planejado, tempo_planejado_min)
                            VALUES (?, ?, 1, 'PLANEJADO', '2099-03-02T16:00:00', '2099-03-03T08:00:00', 120)''',
                         (ids['os'], maquina_id))
            conn.commit()

            for dia, esperado in (('2099-03-02', ('16:00', '17:00', 60)),
                                  ('2099-03-03', ('07:00', '08:00', 60))):
                data = json.loads(client.get(f'/api/programacao?data={dia}').data)
                assert (data['janela_inicio'], data['janela_fim']) == ('07:00', '17:00')
                barras = [b for m in data['maquinas'] for b in m['barras'] if b['os_numero'] == 'TESTE-EXPEDIENTE-OS']
                assert len(barras) == 1
                p = barras[0]['planejado']
                assert (p['inicio'], p['fim'], p['minutos']) == esperado
        finally:
            conn.execute('DELETE FROM alocacao_maquinas WHERE ordem_servico_id = ?', (ids.get('os'),))
            conn.execute('DELETE FROM ordens_servico WHERE id = ?', (ids.get('os'),))
            conn.execute('DELETE FROM notas WHERE id = ?', (ids.get('nota'),))
            conn.commit()
            conn.close()

    @staticmethod
    def _janela_com_alocacao(client, dia, **campos):
        """Cria nota/OS/alocação de teste com os campos dados, consulta a
        programação de `dia`, limpa tudo e devolve (janela_inicio, janela_fim)."""
        conn = get_db()
        ids = {}
        try:
            ids['nota'] = conn.execute('''INSERT INTO notas (numero, peca_codigo, quantidade, status)
                                          VALUES ('TESTE-EXPEDIENTE-J', '40-091799', 1, 'PROCESSADA')''').lastrowid
            ids['os'] = conn.execute('''INSERT INTO ordens_servico (numero, nota_id, status, prioridade, tempo_total)
                                        VALUES ('TESTE-EXPEDIENTE-OSJ', ?, 'PLANEJAMENTO', 'NORMAL', 60)''',
                                     (ids['nota'],)).lastrowid
            maquina_id = conn.execute('SELECT id FROM maquinas LIMIT 1').fetchone()[0]
            conn.execute('''INSERT INTO alocacao_maquinas
                            (ordem_servico_id, maquina_id, sequencia, status,
                             inicio_planejado, fim_planejado, tempo_planejado_min,
                             inicio_real, fim_real)
                            VALUES (?, ?, 1, 'CONCLUIDO', ?, ?, 60, ?, ?)''',
                         (ids['os'], maquina_id, campos.get('ini_p'), campos.get('fim_p'),
                          campos.get('ini_r'), campos.get('fim_r')))
            conn.commit()
            data = json.loads(client.get(f'/api/programacao?data={dia}').data)
            return data['janela_inicio'], data['janela_fim']
        finally:
            conn.execute('DELETE FROM alocacao_maquinas WHERE ordem_servico_id = ?', (ids.get('os'),))
            conn.execute('DELETE FROM ordens_servico WHERE id = ?', (ids.get('os'),))
            conn.execute('DELETE FROM notas WHERE id = ?', (ids.get('nota'),))
            conn.commit()
            conn.close()

    def test_execucao_real_de_outro_dia_nao_estende_o_eixo(self, client):
        """Planejada na segunda, executada na terça: o eixo da segunda continua 7h-17h."""
        janela = self._janela_com_alocacao(
            client, '2099-03-02',
            ini_p='2099-03-02T15:00:00', fim_p='2099-03-02T16:00:00',
            ini_r='2099-03-03T08:00:00', fim_r='2099-03-03T09:00:00')
        assert janela == ('07:00', '17:00')

    def test_execucao_real_fora_do_expediente_estende_o_eixo_so_o_necessario(self, client):
        """Executada 6h10-7h40 no próprio dia: nada some, o eixo abre às 6h."""
        janela = self._janela_com_alocacao(
            client, '2099-03-02',
            ini_p='2099-03-02T07:00:00', fim_p='2099-03-02T08:00:00',
            ini_r='2099-03-02T06:10:00', fim_r='2099-03-02T07:40:00')
        assert janela == ('06:00', '17:00')

    def test_programacao_nao_desenha_planejado_no_fim_de_semana(self, client):
        """Sexta 16h -> segunda 8h: sábado e domingo não têm barra planejada."""
        conn = get_db()
        ids = {}
        try:
            ids['nota'] = conn.execute('''INSERT INTO notas (numero, peca_codigo, quantidade, status)
                                          VALUES ('TESTE-EXPEDIENTE-3', '40-091799', 1, 'PROCESSADA')''').lastrowid
            ids['os'] = conn.execute('''INSERT INTO ordens_servico (numero, nota_id, status, prioridade, tempo_total)
                                        VALUES ('TESTE-EXPEDIENTE-OS3', ?, 'PLANEJAMENTO', 'NORMAL', 120)''',
                                     (ids['nota'],)).lastrowid
            maquina_id = conn.execute('SELECT id FROM maquinas LIMIT 1').fetchone()[0]
            # 2099-03-06 é sexta-feira
            conn.execute('''INSERT INTO alocacao_maquinas
                            (ordem_servico_id, maquina_id, sequencia, status,
                             inicio_planejado, fim_planejado, tempo_planejado_min)
                            VALUES (?, ?, 1, 'PLANEJADO', '2099-03-06T16:00:00', '2099-03-09T08:00:00', 120)''',
                         (ids['os'], maquina_id))
            conn.commit()

            for dia in ('2099-03-07', '2099-03-08'):
                data = json.loads(client.get(f'/api/programacao?data={dia}').data)
                barras = [b for m in data['maquinas'] for b in m['barras'] if b['os_numero'] == 'TESTE-EXPEDIENTE-OS3']
                assert barras == [], f'{dia} não deveria ter barra planejada'
            sexta = json.loads(client.get('/api/programacao?data=2099-03-06').data)
            assert any(b['os_numero'] == 'TESTE-EXPEDIENTE-OS3' and b['planejado']['minutos'] == 60
                       for m in sexta['maquinas'] for b in m['barras'])
        finally:
            conn.execute('DELETE FROM alocacao_maquinas WHERE ordem_servico_id = ?', (ids.get('os'),))
            conn.execute('DELETE FROM ordens_servico WHERE id = ?', (ids.get('os'),))
            conn.execute('DELETE FROM notas WHERE id = ?', (ids.get('nota'),))
            conn.commit()
            conn.close()


class TestFeriados:
    """Feriados nacionais (fixos e derivados da Páscoa) não são dia útil."""

    # Domingos de Páscoa publicados, para conferir o algoritmo.
    PASCOAS = {2020: (4, 12), 2021: (4, 4), 2022: (4, 17), 2023: (4, 9), 2024: (3, 31),
               2025: (4, 20), 2026: (4, 5), 2027: (3, 28), 2028: (4, 16), 2030: (4, 21)}

    @pytest.fixture(autouse=True)
    def expediente_padrao(self, monkeypatch):
        import app as app_module
        monkeypatch.setattr(app_module, 'EXPEDIENTE_INICIO_H', 7)
        monkeypatch.setattr(app_module, 'EXPEDIENTE_FIM_H', 17)

    def test_pascoa_bate_com_as_datas_publicadas(self):
        from app import _pascoa
        for ano, (mes, dia) in self.PASCOAS.items():
            assert _pascoa(ano) == date(ano, mes, dia), ano

    def test_feriados_de_2026(self):
        assert feriados_do_ano(2026) == {
            date(2026, 1, 1), date(2026, 2, 16), date(2026, 2, 17),   # Ano Novo, Carnaval seg e ter
            date(2026, 4, 3), date(2026, 4, 21), date(2026, 5, 1),    # Sexta-feira Santa, Tiradentes, Trabalho
            date(2026, 6, 4), date(2026, 9, 7), date(2026, 10, 12),   # Corpus Christi, Independência, Aparecida
            date(2026, 11, 2), date(2026, 11, 15), date(2026, 11, 20),  # Finados, República, Consciência Negra
            date(2026, 12, 25),
        }

    def test_consciencia_negra_e_feriado_nacional_so_a_partir_de_2024(self):
        assert date(2023, 11, 20) not in feriados_do_ano(2023)
        for ano in (2024, 2025, 2026, 2030):
            assert date(ano, 11, 20) in feriados_do_ano(ano), ano

    def test_moveis_de_outros_anos(self):
        assert {date(2025, 3, 3), date(2025, 3, 4), date(2025, 4, 18), date(2025, 6, 19)} <= feriados_do_ano(2025)
        assert {date(2024, 2, 12), date(2024, 2, 13), date(2024, 3, 29), date(2024, 5, 30)} <= feriados_do_ano(2024)

    def test_feriado_em_dia_de_semana_nao_e_util_e_aceita_datetime(self):
        assert not eh_dia_util(date(2026, 9, 7))                 # segunda-feira, Independência
        assert not eh_dia_util(datetime(2026, 9, 7, 10, 0))
        assert eh_dia_util(date(2026, 9, 8))                     # terça normal
        assert not eh_dia_util(date(2026, 9, 5))                 # sábado continua não sendo

    def test_planejador_pula_o_feriado(self):
        # sexta 04/09 16h + 120 min: 60 na sexta; segunda 07/09 é feriado; termina terça 08/09 8h
        assert somar_expediente(datetime(2026, 9, 4, 16), 120) == datetime(2026, 9, 8, 8)
        assert alinhar_ao_expediente(datetime(2026, 9, 7, 10)) == datetime(2026, 9, 8, 7)
        # Sexta-feira Santa: quinta 02/04 16h + 120 -> 60 na quinta, sex feriado, fds, segunda 08h
        assert somar_expediente(datetime(2026, 4, 2, 16), 120) == datetime(2026, 4, 6, 8)
        # Consciência Negra (sexta 20/11/2026): quinta 19/11 16h + 120 min -> segunda 23/11 8h
        assert somar_expediente(datetime(2026, 11, 19, 16), 120) == datetime(2026, 11, 23, 8)
        assert alinhar_ao_expediente(datetime(2026, 11, 20, 10)) == datetime(2026, 11, 23, 7)
        # em 2023 o 20/11 (segunda) ainda era dia útil
        assert alinhar_ao_expediente(datetime(2023, 11, 20, 10)) == datetime(2023, 11, 20, 10)

    def test_programacao_nao_desenha_planejado_no_feriado(self, client):
        """Operação sexta 16h -> terça 8h: barra na sexta e na terça, nenhuma na segunda (feriado)."""
        conn = get_db()
        ids = {}
        try:
            ids['nota'] = conn.execute('''INSERT INTO notas (numero, peca_codigo, quantidade, status)
                                          VALUES ('TESTE-FERIADO-1', '40-091799', 1, 'PROCESSADA')''').lastrowid
            ids['os'] = conn.execute('''INSERT INTO ordens_servico (numero, nota_id, status, prioridade, tempo_total)
                                        VALUES ('TESTE-FERIADO-OS', ?, 'PLANEJAMENTO', 'NORMAL', 120)''',
                                     (ids['nota'],)).lastrowid
            maquina_id = conn.execute('SELECT id FROM maquinas LIMIT 1').fetchone()[0]
            conn.execute('''INSERT INTO alocacao_maquinas
                            (ordem_servico_id, maquina_id, sequencia, status,
                             inicio_planejado, fim_planejado, tempo_planejado_min)
                            VALUES (?, ?, 1, 'PLANEJADO', '2026-09-04T16:00:00', '2026-09-08T08:00:00', 120)''',
                         (ids['os'], maquina_id))
            conn.commit()

            def barras(dia):
                data = json.loads(client.get(f'/api/programacao?data={dia}').data)
                return [b for m in data['maquinas'] for b in m['barras'] if b['os_numero'] == 'TESTE-FERIADO-OS']

            assert barras('2026-09-07') == []
            sexta, terca = barras('2026-09-04'), barras('2026-09-08')
            assert [(b['planejado']['inicio'], b['planejado']['fim']) for b in sexta] == [('16:00', '17:00')]
            assert [(b['planejado']['inicio'], b['planejado']['fim']) for b in terca] == [('07:00', '08:00')]
        finally:
            conn.execute('DELETE FROM alocacao_maquinas WHERE ordem_servico_id = ?', (ids.get('os'),))
            conn.execute('DELETE FROM ordens_servico WHERE id = ?', (ids.get('os'),))
            conn.execute('DELETE FROM notas WHERE id = ?', (ids.get('nota'),))
            conn.commit()
            conn.close()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
