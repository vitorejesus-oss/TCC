"""
Testes Unitários - Sistema de Automação de Usinagem
Pytest coverage dos endpoints principais e dos diferenciais
"""

import io
import json
import os
from datetime import date, datetime, timedelta

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

    def test_iniciar_primeira_operacao_poe_a_os_em_usinando(self, client):
        """Etapa 2 do bot inicia por /alocacoes: a OS não pode ficar em PLANEJAMENTO."""
        r = client.post('/api/notas', data=json.dumps({'peca_codigo': '40-091799', 'quantidade': 1}),
                        content_type='application/json')
        os_id = json.loads(r.data)['processamento']['os_id']
        ops = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)
        headers = {'Authorization': f'Bearer {self._token(client, "operador")}'}
        assert json.loads(client.get(f'/api/ordens-servico/{os_id}').data)['status'] == 'PLANEJAMENTO'
        assert client.post(f'/api/alocacoes/{ops[0]["id"]}/iniciar', headers=headers).status_code == 200
        os_ = json.loads(client.get(f'/api/ordens-servico/{os_id}').data)
        assert os_['status'] == 'USINANDO' and os_['tempo_inicio']

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


class TestLiberadoESequencia:
    """LIBERADO = "pode começar" em qualquer canal; a sequência de fabricação
    é regra do servidor (a operação N só inicia com a N-1 CONCLUIDO)."""

    @staticmethod
    def _nova_os(client):
        r = client.post('/api/notas', data=json.dumps({'peca_codigo': '40-091799', 'quantidade': 1}),
                        content_type='application/json')
        os_id = json.loads(r.data)['processamento']['os_id']
        return os_id, json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)

    def test_primeira_operacao_nasce_liberada_e_as_demais_planejadas(self, client):
        _, ops = self._nova_os(client)
        assert len(ops) >= 2
        assert ops[0]['status'] == 'LIBERADO'
        assert all(o['status'] == 'PLANEJADO' for o in ops[1:])

    def test_botao_iniciar_do_site_continua_funcionando(self, client):
        os_id, ops = self._nova_os(client)
        r = client.post(f'/api/ordens-servico/{os_id}/iniciar', headers=_auth_papel(client, 'operador'))
        assert r.status_code == 200, r.data
        depois = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)
        assert depois[0]['status'] == 'EXECUTANDO' and depois[1]['status'] == 'PLANEJADO'
        assert json.loads(client.get(f'/api/ordens-servico/{os_id}').data)['status'] == 'USINANDO'

    def test_nao_inicia_operacao_com_a_anterior_pendente(self, client):
        os_id, ops = self._nova_os(client)
        h = _auth_papel(client, 'operador')
        r = client.post(f'/api/alocacoes/{ops[1]["id"]}/iniciar', headers=h)
        assert r.status_code == 409
        erro = json.loads(r.data)['erro']
        assert 'operação anterior' in erro and 'OP 1' in erro and 'não foi concluída' in erro
        # nada mudou: a OP 2 continua PLANEJADO e sem início
        depois = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)
        assert depois[1]['status'] == 'PLANEJADO' and depois[1]['inicio_real'] is None

    def test_anterior_em_execucao_tambem_bloqueia(self, client):
        _, ops = self._nova_os(client)
        h = _auth_papel(client, 'operador')
        assert client.post(f'/api/alocacoes/{ops[0]["id"]}/iniciar', headers=h).status_code == 200
        assert client.post(f'/api/alocacoes/{ops[1]["id"]}/iniciar', headers=h).status_code == 409

    def test_inicia_depois_que_a_anterior_conclui(self, client):
        _, ops = self._nova_os(client)
        h = _auth_papel(client, 'operador')
        assert client.post(f'/api/alocacoes/{ops[0]["id"]}/iniciar', headers=h).status_code == 200
        assert client.post(f'/api/alocacoes/{ops[0]["id"]}/concluir', headers=h,
                           data=json.dumps({}), content_type='application/json').status_code == 200
        assert client.post(f'/api/alocacoes/{ops[1]["id"]}/iniciar', headers=h).status_code == 200

    def test_migracao_liberada_so_atinge_seq1_de_os_nao_iniciada(self, client):
        os_id, ops = self._nova_os(client)
        conn = app_module.get_db()
        try:
            conn.execute("UPDATE alocacao_maquinas SET status='PLANEJADO' WHERE id=?", (ops[0]['id'],))
            conn.commit()
            app_module.init_db()
            status = {r['id']: r['status'] for r in conn.execute(
                'SELECT id, status FROM alocacao_maquinas WHERE ordem_servico_id = ?', (os_id,))}
            assert status[ops[0]['id']] == 'LIBERADO'
            assert status[ops[1]['id']] == 'PLANEJADO'
        finally:
            conn.close()

    def test_migracao_nao_toca_os_ja_iniciada(self, client):
        os_id, ops = self._nova_os(client)
        h = _auth_papel(client, 'operador')
        assert client.post(f'/api/ordens-servico/{os_id}/iniciar', headers=h).status_code == 200
        conn = app_module.get_db()
        try:
            conn.execute("UPDATE alocacao_maquinas SET status='PLANEJADO', inicio_real=NULL WHERE id=?", (ops[0]['id'],))
            conn.commit()
            app_module.init_db()  # a OS está USINANDO: fora do alcance da migração
            assert conn.execute('SELECT status FROM alocacao_maquinas WHERE id=?', (ops[0]['id'],)).fetchone()[0] == 'PLANEJADO'
        finally:
            conn.close()


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


class TestFichaTecnicaDaPeca:
    """pecas ganhou material/dimensoes/tolerancia/aplicacao/observacoes_tecnicas (opcionais)."""

    def _lista(self, client):
        return json.loads(client.get('/api/pecas').data)

    def test_colunas_da_ficha_existem_e_sao_opcionais(self, client):
        conn = app_module.get_db()
        try:
            colunas = {r[1] for r in conn.execute('PRAGMA table_info(pecas)')}
        finally:
            conn.close()
        assert set(app_module.FICHA_CAMPOS) <= colunas

    def test_lista_de_pecas_informa_o_que_falta(self, client):
        for p in self._lista(client):
            assert isinstance(p['tem_desenho'], bool)
            assert set(p['ficha']) | set(p['ficha_faltando']) == set(app_module.FICHA_CAMPOS)
            assert not set(p['ficha']) & set(p['ficha_faltando'])

    def test_campo_vazio_nao_aparece_na_ficha(self, client):
        conn = app_module.get_db()
        try:
            conn.execute("INSERT OR REPLACE INTO pecas (codigo, nome, material, dimensoes) "
                         "VALUES ('FICHA-T1', 'Peça ficha', 'Aço 1045', '   ')")
            conn.commit()
            p = next(x for x in self._lista(client) if x['codigo'] == 'FICHA-T1')
            assert p['ficha'] == {'material': 'Aço 1045'}   # '   ' não conta como preenchido
            assert 'dimensoes' in p['ficha_faltando'] and 'material' not in p['ficha_faltando']
            assert p['tem_desenho'] is False
        finally:
            conn.execute("DELETE FROM pecas WHERE codigo = 'FICHA-T1'")
            conn.commit()
            conn.close()

    def test_peca_com_pdf_tem_desenho(self, client):
        com = [p for p in self._lista(client) if p['tem_desenho']]
        assert com and all(os.path.isfile(os.path.join(app_module.DESENHOS_DIR, p['codigo'] + '.pdf')) for p in com)

    def test_detalhes_da_nota_trazem_ficha_e_desenho(self, client):
        r = client.post('/api/notas', data=json.dumps({'peca_codigo': '40-091799', 'quantidade': 1}),
                        content_type='application/json')
        nota_id = json.loads(r.data)['nota_id']
        det = json.loads(client.get(f'/api/notas/{nota_id}/detalhes', headers=_auth_papel(client, 'operador')).data)
        assert det['peca']['tem_desenho'] is True
        assert set(det['peca']['ficha']) | set(det['peca']['ficha_faltando']) == set(app_module.FICHA_CAMPOS)


class TestBuscaDeOS:
    """GET /api/ordens-servico com filtros combináveis, ordenação e paginação."""

    @staticmethod
    def _tag():
        import uuid
        return 'BUSCA-' + uuid.uuid4().hex[:10]

    @staticmethod
    def _criar(client, tag, prioridade='NORMAL'):
        r = client.post('/api/notas', data=json.dumps({'peca_codigo': '40-091799', 'quantidade': 1,
                                                        'solicitante': tag, 'prioridade': prioridade}),
                        content_type='application/json')
        d = json.loads(r.data)
        return d['processamento']['os_id'], d['nota_id']

    @staticmethod
    def _buscar(client, **params):
        r = client.get('/api/ordens-servico', query_string=params)
        return r, (json.loads(r.data) if r.status_code == 200 else None)

    @staticmethod
    def _sql(sql, *params):
        conn = app_module.get_db()
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def test_sem_parametros_continua_devolvendo_lista_simples(self, client):
        r, data = self._buscar(client)
        assert r.status_code == 200 and isinstance(data, list)
        assert {'numero', 'peca_nome', 'peca_codigo', 'status'} <= set(data[0])

    def test_texto_livre_acha_por_solicitante_numero_da_os_da_nota_peca(self, client):
        tag = self._tag()
        os_id, nota_id = self._criar(client, tag)
        _, por_solicitante = self._buscar(client, q=tag.lower())      # sem diferenciar maiúscula
        assert [o['id'] for o in por_solicitante] == [os_id]
        o = por_solicitante[0]
        for termo in (o['numero'], o['nota_numero'], o['peca_codigo'], o['peca_nome'][:5]):
            _, d = self._buscar(client, q=termo)
            assert os_id in [x['id'] for x in d], termo

    def test_texto_livre_trata_percentual_e_underscore_como_texto(self, client):
        assert self._buscar(client, q='%')[1] == []
        assert self._buscar(client, q='_')[1] == []

    def test_prioridade_e_status(self, client):
        tag = self._tag()
        u, _ = self._criar(client, tag, 'URGENTE')
        n, _ = self._criar(client, tag, 'NORMAL')
        assert [o['id'] for o in self._buscar(client, q=tag, prioridade='URGENTE')[1]] == [u]
        assert [o['id'] for o in self._buscar(client, q=tag, prioridade='normal')[1]] == [n]
        self._sql("UPDATE ordens_servico SET status='USINANDO' WHERE id=?", u)
        assert [o['id'] for o in self._buscar(client, q=tag, status='USINANDO')[1]] == [u]
        assert [o['id'] for o in self._buscar(client, q=tag, status='PLANEJAMENTO')[1]] == [n]
        assert self._buscar(client, q=tag, status='CONCLUIDA')[1] == []

    def test_filtro_por_maquina(self, client):
        tag = self._tag()
        os_id, _ = self._criar(client, tag)
        maquinas = json.loads(client.get('/api/maquinas').data)
        usada = next(m for m in maquinas if m['nome'] == 'Torno Horizontal')   # roteiro da peça 40-091799
        fora = next(m for m in maquinas if m['nome'] == 'Serra de Fita')
        assert [o['id'] for o in self._buscar(client, q=tag, maquina_id=usada['id'])[1]] == [os_id]
        assert self._buscar(client, q=tag, maquina_id=fora['id'])[1] == []

    def test_periodo_de_criacao_e_de_conclusao(self, client):
        tag = self._tag()
        os_id, _ = self._criar(client, tag)
        self._sql("UPDATE ordens_servico SET criada_em='2031-03-10T12:00:00', concluida_em='2031-03-12 09:30:00', "
                  "status='CONCLUIDA' WHERE id=?", os_id)
        achou = lambda **p: os_id in [o['id'] for o in self._buscar(client, q=tag, **p)[1]]
        assert achou(criada_de='2031-03-10', criada_ate='2031-03-10')          # limites inclusivos
        assert not achou(criada_de='2031-03-11')
        assert not achou(criada_ate='2031-03-09')
        assert achou(concluida_de='2031-03-12', concluida_ate='2031-03-12')   # formato antigo (espaço) também
        assert not achou(concluida_de='2031-03-13')

    def test_operador_que_executou(self, client):
        tag = self._tag()
        os_id, _ = self._criar(client, tag)
        outra, _ = self._criar(client, tag)
        self._sql("UPDATE alocacao_maquinas SET operador='fulano.busca@fabrica.com' WHERE ordem_servico_id=? AND sequencia=1", os_id)
        assert [o['id'] for o in self._buscar(client, q=tag, operador='fulano.busca')[1]] == [os_id]
        assert 'fulano.busca@fabrica.com' in self._buscar(client, q=tag, operador='fulano.busca')[1][0]['operadores']
        assert self._buscar(client, q=tag, operador='ninguem.assim')[1] == []

    def test_em_atraso_so_operacao_aberta_com_fim_planejado_passado(self, client):
        tag = self._tag()
        atrasada, _ = self._criar(client, tag)
        no_prazo, _ = self._criar(client, tag)
        concluida, _ = self._criar(client, tag)
        self._sql("UPDATE alocacao_maquinas SET fim_planejado='2020-01-01T10:00:00' WHERE ordem_servico_id=?", atrasada)
        self._sql("UPDATE alocacao_maquinas SET fim_planejado='2099-01-01T10:00:00' WHERE ordem_servico_id=?", no_prazo)
        self._sql("UPDATE alocacao_maquinas SET fim_planejado='2020-01-01T10:00:00' WHERE ordem_servico_id=?", concluida)
        self._sql("UPDATE ordens_servico SET status='CONCLUIDA' WHERE id=?", concluida)
        _, atrasos = self._buscar(client, q=tag, em_atraso='1')
        assert [o['id'] for o in atrasos] == [atrasada]
        assert atrasos[0]['em_atraso'] is True and atrasos[0]['atraso_min'] > 60 * 24 * 365
        _, todas = self._buscar(client, q=tag)
        por_id = {o['id']: o for o in todas}
        assert por_id[no_prazo]['em_atraso'] is False and por_id[no_prazo]['atraso_min'] is None
        assert por_id[concluida]['em_atraso'] is False

    def test_operacao_concluida_no_prazo_nao_e_atraso(self, client):
        tag = self._tag()
        os_id, _ = self._criar(client, tag)
        self._sql("UPDATE alocacao_maquinas SET fim_planejado='2020-01-01T10:00:00', status='CONCLUIDO' "
                  "WHERE ordem_servico_id=? AND sequencia=1", os_id)
        self._sql("UPDATE alocacao_maquinas SET fim_planejado='2099-01-01T10:00:00' WHERE ordem_servico_id=? AND sequencia>1", os_id)
        assert self._buscar(client, q=tag, em_atraso='1')[1] == []

    def test_planejado_realizado_e_maquina_atual(self, client):
        tag = self._tag()
        os_id, _ = self._criar(client, tag)
        ops = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)
        linha = self._buscar(client, q=tag)[1][0]
        assert linha['planejado_min'] == sum(o['tempo_planejado_min'] for o in ops)
        assert linha['realizado_min'] is None
        assert linha['maquina_atual'] == ops[0]['maquina_nome']           # a LIBERADO
        h = _auth_papel(client, 'operador')
        client.post(f'/api/alocacoes/{ops[0]["id"]}/iniciar', headers=h)
        client.post(f'/api/alocacoes/{ops[0]["id"]}/concluir', headers=h, data=json.dumps({}), content_type='application/json')
        self._sql("UPDATE alocacao_maquinas SET tempo_realizado_min=130 WHERE id=?", ops[0]['id'])
        linha = self._buscar(client, q=tag)[1][0]
        assert linha['realizado_min'] == 130
        assert linha['maquina_atual'] == ops[1]['maquina_nome']           # a seguinte foi liberada

    def test_filtros_combinam(self, client):
        tag = self._tag()
        u, _ = self._criar(client, tag, 'URGENTE')
        self._criar(client, tag, 'NORMAL')
        assert [o['id'] for o in self._buscar(client, q=tag, prioridade='URGENTE', status='PLANEJAMENTO')[1]] == [u]
        assert self._buscar(client, q=tag, prioridade='URGENTE', status='CONCLUIDA')[1] == []

    def test_paginacao(self, client):
        tag = self._tag()
        ids = [self._criar(client, tag)[0] for _ in range(5)]
        r, p1 = self._buscar(client, q=tag, pagina=1, por_pagina=2, ordenar='numero', direcao='asc')
        assert set(p1) == {'itens', 'total', 'pagina', 'por_pagina', 'paginas'}
        assert p1['total'] == 5 and p1['paginas'] == 3 and len(p1['itens']) == 2
        _, p3 = self._buscar(client, q=tag, pagina=3, por_pagina=2, ordenar='numero', direcao='asc')
        assert len(p3['itens']) == 1
        _, p4 = self._buscar(client, q=tag, pagina=4, por_pagina=2, ordenar='numero')
        assert p4['itens'] == []
        vistos = [o['id'] for pg in (1, 2, 3) for o in self._buscar(client, q=tag, pagina=pg, por_pagina=2, ordenar='numero')[1]['itens']]
        assert sorted(vistos) == sorted(ids) and len(set(vistos)) == 5   # sem repetir nem perder

    def test_ordenacao_asc_e_desc(self, client):
        tag = self._tag()
        for _ in range(3):
            self._criar(client, tag)
        asc = [o['numero'] for o in self._buscar(client, q=tag, ordenar='numero', direcao='asc')[1]]
        desc = [o['numero'] for o in self._buscar(client, q=tag, ordenar='numero', direcao='desc')[1]]
        assert asc == sorted(asc) and desc == list(reversed(asc))

    def test_parametros_invalidos_retornam_400(self, client):
        for params in ({'status': 'XYZ'}, {'prioridade': 'XYZ'}, {'criada_de': '10/03/2031'},
                       {'concluida_ate': 'ontem'}, {'ordenar': 'senha'}, {'direcao': 'cima'},
                       {'pagina': '0'}, {'pagina': 'abc'}, {'por_pagina': '1000'}, {'maquina_id': 'x'},
                       {'origem': 'INVENTADA'}):
            r, _ = self._buscar(client, **params)
            assert r.status_code == 400, params

    def test_ordenar_nao_aceita_sql(self, client):
        r, _ = self._buscar(client, ordenar='os.id; DROP TABLE ordens_servico')
        assert r.status_code == 400
        assert self._buscar(client)[0].status_code == 200

class TestDesenhoProvisorio:
    """desenhos_tecnicos/PLACEHOLDERS.txt marca PDFs que são só um aviso, não o desenho oficial."""

    @pytest.fixture
    def pasta(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app_module, 'DESENHOS_DIR', str(tmp_path))
        for codigo in ('P-REAL', 'P-PROV'):
            (tmp_path / f'{codigo}.pdf').write_bytes(b'%PDF-1.4\n%%EOF\n')
        return tmp_path

    def test_sem_arquivo_de_marcadores_nada_e_provisorio(self, pasta):
        assert app_module.tem_desenho('P-PROV') and not app_module.desenho_provisorio('P-PROV')

    def test_codigo_listado_e_provisorio_e_o_outro_nao(self, pasta):
        (pasta / 'PLACEHOLDERS.txt').write_text('# comentário\n\nP-PROV\n', encoding='utf-8')
        assert app_module.desenho_provisorio('P-PROV') is True
        assert app_module.desenho_provisorio('P-REAL') is False

    def test_comentario_e_linhas_vazias_nao_contam_como_codigo(self, pasta):
        (pasta / 'PLACEHOLDERS.txt').write_text('# P-REAL\n   \n', encoding='utf-8')
        assert app_module.desenho_provisorio('P-REAL') is False

    def test_codigo_listado_sem_pdf_nao_e_provisorio_nem_tem_desenho(self, pasta):
        (pasta / 'PLACEHOLDERS.txt').write_text('P-SEM-PDF\n', encoding='utf-8')
        assert not app_module.tem_desenho('P-SEM-PDF') and not app_module.desenho_provisorio('P-SEM-PDF')

    def test_lista_de_pecas_traz_desenho_provisorio(self, client, pasta):
        conn = app_module.get_db()
        try:
            conn.execute("INSERT OR REPLACE INTO pecas (codigo, nome) VALUES ('P-PROV', 'Provisória')")
            conn.execute("INSERT OR REPLACE INTO pecas (codigo, nome) VALUES ('P-REAL', 'Real')")
            conn.commit()
            (pasta / 'PLACEHOLDERS.txt').write_text('P-PROV\n', encoding='utf-8')
            por_codigo = {p['codigo']: p for p in json.loads(client.get('/api/pecas').data)}
            assert por_codigo['P-PROV']['tem_desenho'] is True and por_codigo['P-PROV']['desenho_provisorio'] is True
            assert por_codigo['P-REAL']['tem_desenho'] is True and por_codigo['P-REAL']['desenho_provisorio'] is False
        finally:
            conn.execute("DELETE FROM pecas WHERE codigo IN ('P-PROV', 'P-REAL')")
            conn.commit()
            conn.close()

    def test_o_pdf_provisorio_continua_sendo_servido(self, client, pasta):
        (pasta / 'PLACEHOLDERS.txt').write_text('P-PROV\n', encoding='utf-8')
        r = client.get('/api/pecas/P-PROV/desenho')
        assert r.status_code == 200 and r.mimetype == 'application/pdf'

    def test_arquivo_de_marcadores_nao_e_servido(self, client, pasta):
        (pasta / 'PLACEHOLDERS.txt').write_text('P-PROV\n', encoding='utf-8')
        assert client.get('/api/pecas/PLACEHOLDERS/desenho').status_code == 404

    def test_detalhes_da_nota_trazem_a_marca(self, client):
        r = client.post('/api/notas', data=json.dumps({'peca_codigo': '40-091799', 'quantidade': 1}),
                        content_type='application/json')
        nota_id = json.loads(r.data)['nota_id']
        peca = json.loads(client.get(f'/api/notas/{nota_id}/detalhes', headers=_auth_papel(client, 'operador')).data)['peca']
        assert peca['tem_desenho'] is True and isinstance(peca['desenho_provisorio'], bool)
        assert peca['desenho_provisorio'] is app_module.desenho_provisorio('40-091799')

    def test_o_pdf_de_40_091799_no_repositorio_e_marcado_como_placeholder(self):
        assert app_module.desenho_provisorio('40-091799') is True

class TestMinutosDeExpediente:
    """minutos_de_expediente: o inverso de somar_expediente (7h-17h, dias úteis)."""

    SEG = datetime(2031, 3, 10)   # segunda-feira, sem feriado

    def test_a_data_de_teste_e_dia_util(self):
        assert self.SEG.weekday() == 0 and eh_dia_util(self.SEG.date())

    def test_mesmo_dia_dentro_do_expediente(self):
        m = app_module.minutos_de_expediente
        assert m(self.SEG.replace(hour=9), self.SEG.replace(hour=11, minute=30)) == 150

    def test_noite_nao_conta(self):
        m = app_module.minutos_de_expediente
        # segunda 16h -> terça 8h = 60 min (até as 17h) + 60 min (desde as 7h)
        assert m(self.SEG.replace(hour=16), (self.SEG + timedelta(days=1)).replace(hour=8)) == 120

    def test_so_madrugada_vale_zero(self):
        m = app_module.minutos_de_expediente
        assert m(self.SEG.replace(hour=18), (self.SEG + timedelta(days=1)).replace(hour=6)) == 0

    def test_fim_de_semana_nao_conta(self):
        m = app_module.minutos_de_expediente
        sabado = self.SEG + timedelta(days=5)
        assert m(sabado.replace(hour=8), sabado.replace(hour=16)) == 0
        # sexta 16h -> segunda 8h = 60 (sexta) + 60 (segunda)
        sexta = self.SEG + timedelta(days=4)
        assert m(sexta.replace(hour=16), (self.SEG + timedelta(days=7)).replace(hour=8)) == 120

    def test_feriado_nao_conta(self):
        m = app_module.minutos_de_expediente
        natal = datetime(2030, 12, 25)     # quarta, feriado nacional
        assert eh_dia_util(natal.date()) is False
        assert m(natal.replace(hour=8), natal.replace(hour=16)) == 0

    def test_varios_dias_uteis(self):
        m = app_module.minutos_de_expediente
        # segunda 7h -> quarta 17h = 3 dias de 600 min
        assert m(self.SEG.replace(hour=7), (self.SEG + timedelta(days=2)).replace(hour=17)) == 1800

    def test_fim_menor_ou_igual_ao_inicio(self):
        m = app_module.minutos_de_expediente
        assert m(self.SEG.replace(hour=9), self.SEG.replace(hour=9)) == 0
        assert m(self.SEG.replace(hour=10), self.SEG.replace(hour=9)) == 0

    def test_e_o_inverso_de_somar_expediente(self):
        m = app_module.minutos_de_expediente
        ini = self.SEG.replace(hour=16, minute=20)
        for minutos in (30, 100, 700, 2000):
            assert m(ini, app_module.somar_expediente(ini, minutos)) == minutos


class TestInterrupcaoPorQuebra:
    """Etapa 3A: máquina que quebra interrompe a operação EXECUTANDO nela.

    Os testes fixam o relógio do sistema (app._agora) numa segunda-feira: as
    contas de expediente dependem de que hora é, e o resultado não pode
    depender de quando a suíte roda."""

    SEG = datetime(2031, 3, 10)   # segunda-feira, sem feriado

    class _Relogio:
        def __init__(self, agora):
            self.agora = agora

        def em(self, dia_offset, hora, minuto=0):
            self.agora = (datetime(2031, 3, 10) + timedelta(days=dia_offset)).replace(hour=hora, minute=minuto)

        def avancar(self, minutos=0, segundos=0):
            self.agora += timedelta(minutes=minutos, seconds=segundos)

    @pytest.fixture
    def relogio(self, monkeypatch):
        r = self._Relogio(datetime(2031, 3, 10, 9, 0))
        monkeypatch.setattr(app_module, '_agora', lambda: r.agora)
        return r

    @staticmethod
    def _nova_os(client):
        r = client.post('/api/notas', data=json.dumps({'peca_codigo': '40-091799', 'quantidade': 1}),
                        content_type='application/json')
        os_id = json.loads(r.data)['processamento']['os_id']
        return os_id, json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)

    @staticmethod
    def _sql(sql, *params):
        conn = app_module.get_db()
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _linha(alocacao_id):
        conn = app_module.get_db()
        try:
            return dict(conn.execute('SELECT * FROM alocacao_maquinas WHERE id = ?', (alocacao_id,)).fetchone())
        finally:
            conn.close()

    @staticmethod
    def _paradas(alocacao_id):
        conn = app_module.get_db()
        try:
            return [dict(r) for r in conn.execute(
                'SELECT * FROM paradas_operacao WHERE alocacao_id = ? ORDER BY id', (alocacao_id,))]
        finally:
            conn.close()

    @staticmethod
    def _maquina_id(nome):
        conn = app_module.get_db()
        try:
            return conn.execute('SELECT id FROM maquinas WHERE nome = ?', (nome,)).fetchone()[0]
        finally:
            conn.close()

    def _quebrar(self, client, maquina_id):
        r = client.post(f'/api/maquinas/{maquina_id}/quebrada', headers=_auth_papel(client, 'operador'))
        assert r.status_code == 200, r.data

    def _consertar(self, client, maquina_id):
        r = client.post(f'/api/maquinas/{maquina_id}/consertada', headers=_auth_papel(client, 'coordenador'),
                        data=json.dumps({'relatorio': 'teste 3A'}), content_type='application/json')
        assert r.status_code == 200, r.data

    def _iniciar(self, client, aloc_id, papel='operador'):
        return client.post(f'/api/alocacoes/{aloc_id}/iniciar', headers=_auth_papel(client, papel))

    def _concluir(self, client, aloc_id, papel='operador'):
        return client.post(f'/api/alocacoes/{aloc_id}/concluir', headers=_auth_papel(client, papel),
                           data=json.dumps({}), content_type='application/json')

    @pytest.fixture
    def torno(self, client):
        """Garante que o Torno Horizontal termina o teste consertado, aconteça o que acontecer."""
        mid = self._maquina_id('Torno Horizontal')
        yield mid
        r = client.post(f'/api/maquinas/{mid}/consertada', headers=_auth_papel(client, 'coordenador'),
                        data=json.dumps({'relatorio': 'limpeza do teste'}), content_type='application/json')
        assert r.status_code == 200

    def test_migracao_criou_colunas_e_tabela(self, client):
        conn = app_module.get_db()
        try:
            colunas = {r[1] for r in conn.execute('PRAGMA table_info(alocacao_maquinas)')}
            paradas = {r[1] for r in conn.execute('PRAGMA table_info(paradas_operacao)')}
        finally:
            conn.close()
        assert {'tempo_acumulado_min', 'retomada_em', 'tempo_realizado_corrido_min',
                'tempo_acumulado_corrido_min'} <= colunas
        assert {'id', 'alocacao_id', 'maquina_id', 'inicio', 'fim', 'relatorio_manutencao_id', 'criado_em'} <= paradas

    def test_iniciar_grava_retomada_em_igual_ao_inicio_real(self, client, relogio):
        _, ops = self._nova_os(client)
        assert self._iniciar(client, ops[0]['id']).status_code == 200
        linha = self._linha(ops[0]['id'])
        assert linha['retomada_em'] == linha['inicio_real'] == relogio.agora.isoformat()
        assert not linha['tempo_acumulado_min']

    def test_quebra_interrompe_a_operacao_e_grava_o_acumulado(self, client, relogio, torno):
        _, ops = self._nova_os(client)
        a = ops[0]['id']
        self._iniciar(client, a)
        relogio.avancar(30)
        self._quebrar(client, torno)
        linha = self._linha(a)
        assert linha['status'] == 'INTERROMPIDA'
        assert linha['tempo_acumulado_min'] == 30 and linha['tempo_acumulado_corrido_min'] == 30
        assert linha['inicio_real'] == datetime(2031, 3, 10, 9, 0).isoformat()   # não muda
        assert linha['retomada_em'] is None                                       # nada executando agora
        paradas = self._paradas(a)
        assert len(paradas) == 1 and paradas[0]['fim'] is None and paradas[0]['maquina_id'] == torno
        assert paradas[0]['inicio'] == relogio.agora.isoformat()

    def test_quebra_nao_toca_operacoes_de_outras_maquinas_nem_as_nao_executando(self, client, relogio, torno):
        _, ops = self._nova_os(client)             # OP1 Torno Horizontal (LIBERADO), OP2 Torno Vertical
        self._quebrar(client, torno)
        assert self._linha(ops[0]['id'])['status'] == 'LIBERADO'
        assert self._linha(ops[1]['id'])['status'] == 'PLANEJADO'
        assert self._paradas(ops[0]['id']) == []

    def test_segunda_quebra_soma_ao_acumulado_e_abre_outra_parada(self, client, relogio, torno):
        _, ops = self._nova_os(client)
        a = ops[0]['id']
        self._iniciar(client, a); relogio.avancar(20); self._quebrar(client, torno)
        relogio.avancar(60); self._consertar(client, torno)
        assert self._iniciar(client, a).status_code == 200
        relogio.avancar(15); self._quebrar(client, torno)
        linha = self._linha(a)
        assert linha['status'] == 'INTERROMPIDA' and linha['tempo_acumulado_min'] == 35
        assert len(self._paradas(a)) == 2

    def test_conserto_libera_fecha_a_parada_e_nao_reinicia_sozinho(self, client, relogio, torno):
        _, ops = self._nova_os(client)
        a = ops[0]['id']
        self._iniciar(client, a); self._quebrar(client, torno)
        relogio.avancar(45)
        self._consertar(client, torno)
        linha = self._linha(a)
        assert linha['status'] == 'LIBERADO' and linha['retomada_em'] is None
        parada = self._paradas(a)[0]
        assert parada['fim'] == relogio.agora.isoformat() and parada['relatorio_manutencao_id']

    def test_nao_inicia_nem_conclui_operacao_interrompida(self, client, relogio, torno):
        _, ops = self._nova_os(client)
        a = ops[0]['id']
        self._iniciar(client, a); self._quebrar(client, torno)
        r = self._iniciar(client, a)
        assert r.status_code == 409 and 'interrompida' in json.loads(r.data)['erro']
        r = self._concluir(client, a)
        assert r.status_code == 409 and 'interrompida' in json.loads(r.data)['erro']

    def test_nao_conclui_operacao_liberada_que_ainda_nao_foi_retomada(self, client, relogio, torno):
        _, ops = self._nova_os(client)
        a = ops[0]['id']
        self._iniciar(client, a); self._quebrar(client, torno); self._consertar(client, torno)
        r = self._concluir(client, a)
        assert r.status_code == 409 and 'retomada' in json.loads(r.data)['erro']

    def test_retomada_preserva_inicio_real_e_grava_retomada_em(self, client, relogio, torno):
        _, ops = self._nova_os(client)
        a = ops[0]['id']
        self._iniciar(client, a)
        inicio_real = self._linha(a)['inicio_real']
        relogio.avancar(10); self._quebrar(client, torno)
        relogio.avancar(30); self._consertar(client, torno)
        r = self._iniciar(client, a)
        assert r.status_code == 200
        corpo = json.loads(r.data)
        assert corpo['retomada'] is True and corpo['inicio_real'] == inicio_real
        linha = self._linha(a)
        assert linha['status'] == 'EXECUTANDO' and linha['inicio_real'] == inicio_real
        assert linha['retomada_em'] == relogio.agora.isoformat()
        assert linha['tempo_acumulado_min'] == 10

    def test_interrupcao_com_menos_de_um_minuto_ainda_e_retomada(self, client, relogio, torno):
        """acumulado = 0 não pode fazer a retomada passar por um início novo."""
        _, ops = self._nova_os(client)
        a = ops[0]['id']
        self._iniciar(client, a)
        inicio_real = self._linha(a)['inicio_real']
        relogio.avancar(segundos=30)
        self._quebrar(client, torno); self._consertar(client, torno)
        assert self._linha(a)['tempo_acumulado_min'] == 0
        r = self._iniciar(client, a)
        assert r.status_code == 200 and json.loads(r.data)['retomada'] is True
        assert self._linha(a)['inicio_real'] == inicio_real

    def test_concluir_soma_os_dois_trechos_sem_o_tempo_parado(self, client, relogio, torno):
        _, ops = self._nova_os(client)
        a = ops[0]['id']
        self._iniciar(client, a)
        relogio.avancar(30); self._quebrar(client, torno)
        relogio.avancar(180); self._consertar(client, torno)          # 3 h parada, dentro do expediente
        assert self._iniciar(client, a).status_code == 200
        relogio.avancar(20)
        r = self._concluir(client, a)
        assert r.status_code == 200, r.data
        corpo = json.loads(r.data)
        assert corpo['tempo_realizado_min'] == 50 and corpo['tempo_realizado_corrido_min'] == 50   # 30 + 20; as 3 h ficam de fora
        assert corpo['fora_do_expediente'] is False
        linha = self._linha(a)
        assert linha['tempo_realizado_min'] == 50 and linha['tempo_realizado_corrido_min'] == 50

    def test_parada_que_atravessa_a_noite_fica_fora_do_realizado_e_conta_so_expediente_na_perda(self, client, relogio, torno):
        _, ops = self._nova_os(client)
        a = ops[0]['id']
        relogio.em(0, 15, 30); self._iniciar(client, a)
        relogio.em(0, 16, 0); self._quebrar(client, torno)              # 30 min de usinagem
        relogio.em(1, 9, 0); self._consertar(client, torno)             # terça 9h
        p = self._paradas(a)[0]
        assert app_module.minutos_de_expediente(datetime.fromisoformat(p['inicio']), datetime.fromisoformat(p['fim'])) == 180
        self._iniciar(client, a)
        relogio.avancar(20)
        corpo = json.loads(self._concluir(client, a).data)
        assert corpo['tempo_realizado_min'] == 50 and corpo['tempo_realizado_corrido_min'] == 50
        op = json.loads(client.get(f'/api/ordens-servico/{ops[0]["id"] and self._linha(a)["ordem_servico_id"]}/operacoes').data)[0]
        assert op['tempo_parado_min'] == 17 * 60 and op['tempo_parado_expediente_min'] == 180

    def test_realizado_em_expediente_quando_a_execucao_atravessa_a_noite(self, client, relogio):
        """A régua do realizado é a do planejado: 16h30 -> 8h do dia seguinte = 90 min, não 15h30."""
        _, ops = self._nova_os(client)
        a = ops[0]['id']
        relogio.em(0, 16, 30); self._iniciar(client, a)
        relogio.em(1, 8, 0)
        corpo = json.loads(self._concluir(client, a).data)
        assert corpo['tempo_realizado_min'] == 90 and corpo['tempo_realizado_corrido_min'] == 930
        assert corpo['fora_do_expediente'] is True
        linha = self._linha(a)
        assert linha['tempo_realizado_min'] == 90 and linha['tempo_realizado_corrido_min'] == 930

    def test_fim_de_semana_aberto_e_sinalizado(self, client, relogio):
        _, ops = self._nova_os(client)
        a = ops[0]['id']
        relogio.em(4, 16, 0); self._iniciar(client, a)                 # sexta 16h
        relogio.em(7, 8, 0)                                              # segunda 8h
        corpo = json.loads(self._concluir(client, a).data)
        assert corpo['tempo_realizado_min'] == 120 and corpo['fora_do_expediente'] is True
        assert corpo['tempo_realizado_corrido_min'] == 64 * 60

    def test_limiar_da_sinalizacao_de_fora_do_expediente(self, client, relogio):
        assert app_module.FORA_EXPEDIENTE_LIMIAR_MIN == 60
        assert app_module.fora_do_expediente(90, 30) is True          # diferença de exatamente 60: sinaliza
        assert app_module.fora_do_expediente(89, 30) is False         # 59: hora extra pequena, não sinaliza
        assert app_module.fora_do_expediente(30, 30) is False
        assert app_module.fora_do_expediente(None, 30) is False

    def test_hora_extra_pequena_nao_e_sinalizada(self, client, relogio):
        _, ops = self._nova_os(client)
        a = ops[0]['id']
        relogio.em(0, 16, 30); self._iniciar(client, a)
        relogio.em(0, 17, 30)
        corpo = json.loads(self._concluir(client, a).data)
        assert corpo['tempo_realizado_min'] == 30 and corpo['tempo_realizado_corrido_min'] == 60
        assert corpo['fora_do_expediente'] is False

    def test_operacao_sem_interrupcao_dentro_do_expediente_conclui_como_antes(self, client, relogio):
        _, ops = self._nova_os(client)
        a = ops[0]['id']
        self._iniciar(client, a)
        relogio.avancar(45)
        corpo = json.loads(self._concluir(client, a).data)
        assert corpo['tempo_realizado_min'] == corpo['tempo_realizado_corrido_min'] == 45
        assert corpo['fora_do_expediente'] is False

    def test_linha_antiga_sem_retomada_em_usa_inicio_real(self, client, relogio):
        _, ops = self._nova_os(client)
        a = ops[0]['id']
        self._iniciar(client, a)
        self._sql('UPDATE alocacao_maquinas SET retomada_em = NULL WHERE id = ?', a)
        relogio.avancar(25)
        assert json.loads(self._concluir(client, a).data)['tempo_realizado_min'] == 25

    def test_endpoint_de_operacoes_traz_paradas_tempos_e_sinalizacao(self, client, relogio, torno):
        os_id, ops = self._nova_os(client)
        a = ops[0]['id']
        self._iniciar(client, a); relogio.avancar(30); self._quebrar(client, torno)
        op = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)[0]
        assert op['status'] == 'INTERROMPIDA'
        assert op['tempo_usinagem_min'] == 30 and op['tempo_usinagem_corrido_min'] == 30
        assert op['fora_do_expediente'] is False
        assert len(op['paradas']) == 1 and op['paradas'][0]['aberta'] is True
        assert op['tempo_parado_min'] == 0 and 'tempo_parado_expediente_min' in op

    def test_operacao_em_execucao_atravessando_a_noite_ja_mostra_a_sinalizacao(self, client, relogio):
        os_id, ops = self._nova_os(client)
        relogio.em(0, 16, 30); self._iniciar(client, ops[0]['id'])
        relogio.em(1, 8, 0)
        op = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)[0]
        assert op['status'] == 'EXECUTANDO'
        assert op['tempo_usinagem_min'] == 90 and op['tempo_usinagem_corrido_min'] == 930
        assert op['fora_do_expediente'] is True and op['fora_do_expediente_min'] == 840

    def test_detalhes_da_nota_trazem_as_paradas_e_a_sinalizacao(self, client, relogio, torno):
        r = client.post('/api/notas', data=json.dumps({'peca_codigo': '40-091799', 'quantidade': 1}),
                        content_type='application/json')
        d = json.loads(r.data)
        ops = json.loads(client.get(f'/api/ordens-servico/{d["processamento"]["os_id"]}/operacoes').data)
        self._iniciar(client, ops[0]['id']); self._quebrar(client, torno)
        det = json.loads(client.get(f'/api/notas/{d["nota_id"]}/detalhes', headers=_auth_papel(client, 'operador')).data)
        aloc = det['alocacoes'][0]
        assert aloc['status'] == 'INTERROMPIDA' and len(aloc['paradas']) == 1
        assert {'inicio', 'fim', 'duracao_min', 'expediente_min'} <= set(aloc['paradas'][0])
        assert {'tempo_usinagem_min', 'tempo_parado_min', 'fora_do_expediente', 'tempo_usinagem_corrido_min'} <= set(aloc)

    def test_programacao_mostra_a_operacao_interrompida_e_o_trecho_parado(self, client, relogio, torno):
        _, ops = self._nova_os(client)
        a = ops[0]['id']
        self._iniciar(client, a)
        relogio.avancar(40)
        self._quebrar(client, torno)
        relogio.avancar(20)          # a parada precisa ter alguma duração para aparecer na barra
        prog = json.loads(client.get('/api/programacao?data=2031-03-10').data)
        barra = next(b for m in prog['maquinas'] for b in m['barras'] if b['alocacao_id'] == a)
        assert barra['status'] == 'INTERROMPIDA'
        assert barra['realizado'] is not None
        assert len(barra['paradas']) == 1 and barra['paradas'][0]['aberta'] is True
        assert barra['paradas'][0]['largura_pct'] > 0

    def test_quebra_gera_auditoria_da_operacao_interrompida(self, client, relogio, torno):
        _, ops = self._nova_os(client)
        self._iniciar(client, ops[0]['id']); self._quebrar(client, torno)
        eventos = json.loads(client.get('/api/auditoria').data)
        e = next(x for x in eventos if x['tipo_evento'] == 'OPERACAO_INTERROMPIDA')
        assert e['usuario'] == 'operador@fabrica.com'

    def test_conserto_e_retomada_geram_auditoria(self, client, relogio, torno):
        _, ops = self._nova_os(client)
        a = ops[0]['id']
        self._iniciar(client, a); self._quebrar(client, torno); self._consertar(client, torno)
        self._iniciar(client, a)
        tipos = {x['tipo_evento'] for x in json.loads(client.get('/api/auditoria').data)}
        assert {'OPERACAO_LIBERADA', 'OPERACAO_RETOMADA'} <= tipos


class TestMigracaoDoRealizadoParaExpediente:
    """Operações antigas: tempo_realizado_min passa de minutos corridos para minutos de expediente."""

    SEG = datetime(2031, 3, 10)

    @staticmethod
    def _inserir(ini, fim, realizado, corrido=None, status='CONCLUIDO'):
        conn = app_module.get_db()
        try:
            maquina_id = conn.execute("SELECT id FROM maquinas WHERE nome = 'Torno Vertical'").fetchone()[0]
            os_id = conn.execute('SELECT id FROM ordens_servico ORDER BY id DESC LIMIT 1').fetchone()[0]
            cur = conn.execute('''INSERT INTO alocacao_maquinas
                                  (ordem_servico_id, maquina_id, sequencia, status, inicio_real, fim_real,
                                   tempo_realizado_min, tempo_realizado_corrido_min)
                                  VALUES (?, ?, 98, ?, ?, ?, ?, ?)''',
                               (os_id, maquina_id, status, ini.isoformat(), fim.isoformat() if fim else None,
                                realizado, corrido))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    @staticmethod
    def _ler(alocacao_id):
        conn = app_module.get_db()
        try:
            r = conn.execute('SELECT tempo_realizado_min r, tempo_realizado_corrido_min c FROM alocacao_maquinas WHERE id = ?',
                             (alocacao_id,)).fetchone()
            return r['r'], r['c']
        finally:
            conn.close()

    @staticmethod
    def _limpar(*ids):
        conn = app_module.get_db()
        try:
            for i in ids:
                conn.execute('DELETE FROM alocacao_maquinas WHERE id = ?', (i,))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _migrar(monkeypatch):
        chamadas = []
        monkeypatch.setattr(app_module, 'criar_backup', lambda: chamadas.append(1) or 'backup.db')
        conn = app_module.get_db()
        try:
            return app_module._migrar_realizado_para_expediente(conn), chamadas
        finally:
            conn.close()

    def test_operacao_do_fim_de_semana_e_recalculada_e_o_corrido_e_guardado(self, client, monkeypatch):
        ini = self.SEG + timedelta(days=4, hours=16)                  # sexta 16h
        fim = self.SEG + timedelta(days=7, hours=8)                   # segunda 8h
        corrido = int((fim - ini).total_seconds() / 60)
        a = self._inserir(ini, fim, realizado=corrido)
        try:
            recalculadas, chamadas = self._migrar(monkeypatch)
            assert recalculadas >= 1 and chamadas
            assert self._ler(a) == (120, corrido)                      # 60 (sexta) + 60 (segunda)
        finally:
            self._limpar(a)

    def test_operacao_dentro_do_expediente_mantem_o_valor_e_ganha_o_corrido(self, client, monkeypatch):
        a = self._inserir(self.SEG.replace(hour=9), self.SEG.replace(hour=11), realizado=118)   # 118 gravado, 120 nos timestamps
        try:
            self._migrar(monkeypatch)
            assert self._ler(a) == (118, 118)                          # nada muda além da coluna de auditoria
        finally:
            self._limpar(a)

    def test_e_idempotente(self, client, monkeypatch):
        ini, fim = self.SEG.replace(hour=16), (self.SEG + timedelta(days=1)).replace(hour=8)
        a = self._inserir(ini, fim, realizado=960)
        try:
            self._migrar(monkeypatch)
            primeira = self._ler(a)
            assert primeira == (120, 960)
            recalculadas, chamadas = self._migrar(monkeypatch)
            assert self._ler(a) == primeira and recalculadas == 0 and not chamadas
        finally:
            self._limpar(a)

    def test_linha_ja_migrada_nao_e_tocada(self, client, monkeypatch):
        ini, fim = self.SEG.replace(hour=16), (self.SEG + timedelta(days=1)).replace(hour=8)
        a = self._inserir(ini, fim, realizado=77, corrido=960)
        try:
            self._migrar(monkeypatch)
            assert self._ler(a) == (77, 960)
        finally:
            self._limpar(a)

    def test_sem_recalculo_nao_faz_backup(self, client, monkeypatch):
        a = self._inserir(self.SEG.replace(hour=9), self.SEG.replace(hour=10), realizado=60)
        try:
            recalculadas, chamadas = self._migrar(monkeypatch)
            assert recalculadas == 0 and not chamadas
        finally:
            self._limpar(a)

    def test_falha_no_backup_adia_o_recalculo(self, client, monkeypatch):
        ini, fim = self.SEG.replace(hour=16), (self.SEG + timedelta(days=1)).replace(hour=8)
        a = self._inserir(ini, fim, realizado=960)
        try:
            def quebrado():
                raise OSError('disco cheio')
            monkeypatch.setattr(app_module, 'criar_backup', quebrado)
            conn = app_module.get_db()
            try:
                assert app_module._migrar_realizado_para_expediente(conn) == 0
            finally:
                conn.close()
            assert self._ler(a) == (960, None)                         # nada foi mexido sem backup
        finally:
            self._limpar(a)


class TestProducaoPerdida:
    """/api/indicadores/manutencao: producao_perdida_min (minutos de expediente) e operações interrompidas."""

    SEG = datetime(2033, 3, 14)

    @staticmethod
    def _preparar():
        """Cria uma alocação de teste e devolve (alocacao_id, maquina_id) para pendurar paradas."""
        conn = app_module.get_db()
        try:
            maquina_id = conn.execute("SELECT id FROM maquinas WHERE nome = 'Torno Vertical'").fetchone()[0]
            os_id = conn.execute('SELECT id FROM ordens_servico ORDER BY id DESC LIMIT 1').fetchone()[0]
            cur = conn.execute('''INSERT INTO alocacao_maquinas (ordem_servico_id, maquina_id, sequencia, status)
                                  VALUES (?, ?, 99, 'CONCLUIDO')''', (os_id, maquina_id))
            conn.commit()
            return cur.lastrowid, maquina_id
        finally:
            conn.close()

    @staticmethod
    def _parada(alocacao_id, maquina_id, ini, fim):
        conn = app_module.get_db()
        try:
            conn.execute('INSERT INTO paradas_operacao (alocacao_id, maquina_id, inicio, fim) VALUES (?, ?, ?, ?)',
                         (alocacao_id, maquina_id, ini.isoformat(), fim.isoformat() if fim else None))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _limpar(alocacao_id):
        conn = app_module.get_db()
        try:
            conn.execute('DELETE FROM paradas_operacao WHERE alocacao_id = ?', (alocacao_id,))
            conn.execute('DELETE FROM alocacao_maquinas WHERE id = ?', (alocacao_id,))
            conn.commit()
        finally:
            conn.close()

    def _indicadores(self, client, **params):
        r = client.get('/api/indicadores/manutencao', query_string=params, headers=_auth_papel(client, 'gestor'))
        assert r.status_code == 200, r.data
        return json.loads(r.data)

    def test_soma_so_minutos_de_expediente_e_separa_por_maquina(self, client):
        aloc, maq = self._preparar()
        try:
            # seg 16h -> ter 8h: 120 min de expediente (a noite não conta)
            self._parada(aloc, maq, self.SEG.replace(hour=16), (self.SEG + timedelta(days=1)).replace(hour=8))
            # sáb 10h -> dom 10h: 0 min (fim de semana)
            sab = self.SEG + timedelta(days=5)
            self._parada(aloc, maq, sab.replace(hour=10), sab.replace(hour=10) + timedelta(days=1))
            d = self._indicadores(client, de='2033-03-01', ate='2033-03-31')
            assert d['producao_perdida_min']['total'] == 120
            por = {m['nome']: m['minutos'] for m in d['producao_perdida_min']['por_maquina']}
            assert por['Torno Vertical'] == 120 and sum(por.values()) == 120
            item = next(m for m in d['maquinas'] if m['nome'] == 'Torno Vertical')
            assert item['producao_perdida_min'] == 120 and item['operacoes_interrompidas'] == 1
            assert d['operacoes_interrompidas'] == 1
        finally:
            self._limpar(aloc)

    def test_periodo_filtra_pelo_inicio_da_parada(self, client):
        aloc, maq = self._preparar()
        try:
            self._parada(aloc, maq, self.SEG.replace(hour=9), self.SEG.replace(hour=10))
            assert self._indicadores(client, de='2033-03-14', ate='2033-03-14')['producao_perdida_min']['total'] == 60
            assert self._indicadores(client, de='2033-03-15', ate='2033-03-31')['producao_perdida_min']['total'] == 0
            assert self._indicadores(client, de='2033-04-01', ate='2033-04-30')['producao_perdida_min']['total'] == 0
            assert self._indicadores(client, de='2033-03-01', ate='2033-03-13')['operacoes_interrompidas'] == 0
        finally:
            self._limpar(aloc)

    def test_duas_paradas_na_mesma_operacao_contam_uma_operacao_interrompida(self, client):
        aloc, maq = self._preparar()
        try:
            self._parada(aloc, maq, self.SEG.replace(hour=8), self.SEG.replace(hour=9))
            self._parada(aloc, maq, self.SEG.replace(hour=13), self.SEG.replace(hour=15))
            d = self._indicadores(client, de='2033-03-14', ate='2033-03-14')
            assert d['producao_perdida_min']['total'] == 180 and d['operacoes_interrompidas'] == 1
        finally:
            self._limpar(aloc)

    def test_parada_aberta_conta_ate_agora(self, client):
        aloc, maq = self._preparar()
        try:
            ini = datetime.now() - timedelta(days=1)
            self._parada(aloc, maq, ini, None)
            esperado = app_module.minutos_de_expediente(ini, datetime.now())
            d = self._indicadores(client, de=ini.strftime('%Y-%m-%d'))
            por = {m['nome']: m['minutos'] for m in d['producao_perdida_min']['por_maquina']}
            assert por['Torno Vertical'] >= esperado - 1
        finally:
            self._limpar(aloc)

    def test_sem_paradas_a_resposta_tem_zeros(self, client):
        d = self._indicadores(client, de='2032-01-01', ate='2032-01-31')
        assert d['producao_perdida_min']['total'] == 0 and d['operacoes_interrompidas'] == 0
        assert all(m['minutos'] == 0 for m in d['producao_perdida_min']['por_maquina'])
        assert len(d['producao_perdida_min']['por_maquina']) == d['total']

    def test_datas_invalidas_retornam_400(self, client):
        for params in ({'de': '10/03/2031'}, {'ate': 'ontem'}):
            r = client.get('/api/indicadores/manutencao', query_string=params, headers=_auth_papel(client, 'gestor'))
            assert r.status_code == 400

class TestOperacaoPossivelmenteEsquecida:
    """EXECUTANDO há muito mais que o planejado é sinalizada (Programação, bot, Ver Mais)."""

    def test_regra_pura(self):
        f = app_module.possivelmente_esquecida
        assert app_module.OPERACAO_ESQUECIDA_FATOR == 2
        assert f('EXECUTANDO', 301, 150) is True
        assert f('EXECUTANDO', 300, 150) is False          # exatamente o dobro ainda não sinaliza
        assert f('CONCLUIDO', 4000, 150) is False           # concluída não é "esquecida"
        assert f('INTERROMPIDA', 4000, 150) is False
        assert f('LIBERADO', 4000, 150) is False
        assert f('EXECUTANDO', 4000, None) is False         # sem planejado não há como comparar
        assert f('EXECUTANDO', 4000, 0) is False
        assert f('EXECUTANDO', None, 150) is False

    @pytest.fixture
    def relogio(self, monkeypatch):
        class R:
            agora = datetime(2031, 3, 10, 9, 0)
        r = R()
        monkeypatch.setattr(app_module, '_agora', lambda: r.agora)
        return r

    @staticmethod
    def _op1_em_execucao(client):
        r = client.post('/api/notas', data=json.dumps({'peca_codigo': '40-091799', 'quantidade': 1}),
                        content_type='application/json')
        os_id = json.loads(r.data)['processamento']['os_id']
        ops = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)
        assert client.post(f'/api/alocacoes/{ops[0]["id"]}/iniciar', headers=_auth_papel(client, 'operador')).status_code == 200
        return os_id, ops[0]['id'], ops[0]['tempo_planejado_min']

    def test_operacao_que_passa_do_dobro_e_sinalizada(self, client, relogio):
        os_id, aloc, planejado = self._op1_em_execucao(client)
        assert planejado == 120
        relogio.agora = datetime(2031, 3, 10, 13, 0)                       # 240 min = exatamente o dobro
        op = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)[0]
        assert op['possivelmente_esquecida'] is False and op['limite_esquecida_min'] == 240
        relogio.agora = datetime(2031, 3, 10, 13, 1)                        # 241 min
        op = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)[0]
        assert op['status'] == 'EXECUTANDO' and op['possivelmente_esquecida'] is True

    def test_fator_e_configuravel(self, client, relogio, monkeypatch):
        monkeypatch.setattr(app_module, 'OPERACAO_ESQUECIDA_FATOR', 3.0)
        os_id, aloc, planejado = self._op1_em_execucao(client)
        relogio.agora = datetime(2031, 3, 10, 15, 30)                       # 390 min > 360 (3x o planejado)
        op = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)[0]
        assert op['limite_esquecida_min'] == 360 and op['possivelmente_esquecida'] is True
        relogio.agora = datetime(2031, 3, 10, 14, 30)                       # 330 min: dentro de 3x
        op = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)[0]
        assert op['possivelmente_esquecida'] is False

    def test_conta_em_minutos_de_expediente_nao_corridos(self, client, relogio):
        """Iniciada às 16h e vista às 8h do dia seguinte: 60 + 60 = 120 min de expediente, não é esquecida."""
        os_id, aloc, _ = self._op1_em_execucao(client)
        relogio.agora = datetime(2031, 3, 10, 16, 0)
        conn = app_module.get_db()
        try:
            conn.execute('UPDATE alocacao_maquinas SET inicio_real = ?, retomada_em = ? WHERE id = ?',
                         (relogio.agora.isoformat(), relogio.agora.isoformat(), aloc))
            conn.commit()
        finally:
            conn.close()
        relogio.agora = datetime(2031, 3, 11, 8, 0)
        op = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)[0]
        assert op['tempo_usinagem_min'] == 120 and op['possivelmente_esquecida'] is False

    def test_interrompida_e_concluida_nao_sao_esquecidas(self, client, relogio):
        os_id, aloc, _ = self._op1_em_execucao(client)
        relogio.agora = datetime(2031, 3, 10, 12, 0)
        r = client.post(f'/api/alocacoes/{aloc}/concluir', headers=_auth_papel(client, 'operador'),
                        data=json.dumps({}), content_type='application/json')
        assert r.status_code == 200
        op = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)[0]
        assert op['status'] == 'CONCLUIDO' and op['possivelmente_esquecida'] is False

    def test_programacao_marca_a_barra(self, client, relogio):
        os_id, aloc, _ = self._op1_em_execucao(client)
        relogio.agora = datetime(2031, 3, 10, 15, 0)                        # 360 min > 240
        prog = json.loads(client.get('/api/programacao?data=2031-03-10').data)
        barra = next(b for m in prog['maquinas'] for b in m['barras'] if b['alocacao_id'] == aloc)
        assert barra['status'] == 'EXECUTANDO' and barra['possivelmente_esquecida'] is True

    def test_programacao_nao_marca_operacao_dentro_do_prazo(self, client, relogio):
        os_id, aloc, _ = self._op1_em_execucao(client)
        relogio.agora = datetime(2031, 3, 10, 10, 0)
        prog = json.loads(client.get('/api/programacao?data=2031-03-10').data)
        barra = next(b for m in prog['maquinas'] for b in m['barras'] if b['alocacao_id'] == aloc)
        assert barra['possivelmente_esquecida'] is False

    def test_ver_mais_traz_a_sinalizacao(self, client, relogio):
        r = client.post('/api/notas', data=json.dumps({'peca_codigo': '40-091799', 'quantidade': 1}),
                        content_type='application/json')
        d = json.loads(r.data)
        ops = json.loads(client.get(f'/api/ordens-servico/{d["processamento"]["os_id"]}/operacoes').data)
        client.post(f'/api/alocacoes/{ops[0]["id"]}/iniciar', headers=_auth_papel(client, 'operador'))
        relogio.agora = datetime(2031, 3, 10, 16, 0)                        # 420 min
        det = json.loads(client.get(f'/api/notas/{d["nota_id"]}/detalhes', headers=_auth_papel(client, 'operador')).data)
        aloc = det['alocacoes'][0]
        assert aloc['possivelmente_esquecida'] is True and aloc['limite_esquecida_min'] == 240
        assert aloc['tempo_planejado_min'] == 120


class TestIndicadoresSemForaDoExpediente:
    """Tempo médio e desvio (Estatísticas) deixam de fora as operações concluídas fora do expediente."""

    SEG = datetime(2031, 3, 10)

    @staticmethod
    def _inserir(ini, fim, realizado, corrido, planejado=100):
        conn = app_module.get_db()
        try:
            maquina_id = conn.execute("SELECT id FROM maquinas WHERE nome = 'Torno Vertical'").fetchone()[0]
            os_id = conn.execute('SELECT id FROM ordens_servico ORDER BY id DESC LIMIT 1').fetchone()[0]
            cur = conn.execute('''INSERT INTO alocacao_maquinas
                                  (ordem_servico_id, maquina_id, sequencia, status, inicio_real, fim_real,
                                   tempo_realizado_min, tempo_realizado_corrido_min, tempo_planejado_min)
                                  VALUES (?, ?, 97, 'CONCLUIDO', ?, ?, ?, ?, ?)''',
                               (os_id, maquina_id, ini.isoformat(), fim.isoformat(), realizado, corrido, planejado))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    @staticmethod
    def _limpar(*ids):
        conn = app_module.get_db()
        try:
            for i in ids:
                conn.execute('DELETE FROM alocacao_maquinas WHERE id = ?', (i,))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _stats(client):
        r = client.get('/api/estatisticas', headers=_auth_papel(client, 'gestor'))
        assert r.status_code == 200, r.data
        return json.loads(r.data)

    @staticmethod
    def _esperado_do_banco():
        """Média do realizado e desvio médio do Torno Vertical, recalculados em Python a partir das linhas."""
        limiar = app_module.FORA_EXPEDIENTE_LIMIAR_MIN
        conn = app_module.get_db()
        try:
            linhas = conn.execute('''SELECT am.tempo_realizado_min r, am.tempo_realizado_corrido_min c,
                                            COALESCE(am.tempo_planejado_min,
                                                     (julianday(am.fim_planejado) - julianday(am.inicio_planejado)) * 1440) p
                                     FROM alocacao_maquinas am JOIN maquinas m ON m.id = am.maquina_id
                                     WHERE m.nome = 'Torno Vertical' ''').fetchall()
        finally:
            conn.close()
        fator = app_module.OPERACAO_ESQUECIDA_FATOR

        def excluida(x):
            fora = x['c'] is not None and x['c'] - x['r'] >= limiar
            acima = bool(x['p']) and x['r'] > fator * x['p']
            return fora or acima
        incluidas = [x for x in linhas if x['r'] is not None and not excluida(x)]
        media = round(sum(x['r'] for x in incluidas) / len(incluidas), 1) if incluidas else None
        desvios = [x['r'] - x['p'] for x in incluidas if x['p'] is not None]
        desvio = round(sum(desvios) / len(desvios), 1) if desvios else None
        return media, desvio

    def test_operacao_fora_do_expediente_nao_entra_na_media_nem_no_desvio(self, client):
        antes = self._stats(client)['operacoes_fora_do_calculo']['total']
        normal = self._inserir(self.SEG.replace(hour=9), self.SEG.replace(hour=10), realizado=60, corrido=60)
        esquecida = self._inserir(self.SEG + timedelta(days=4, hours=16), self.SEG + timedelta(days=7, hours=8),
                                  realizado=120, corrido=3840, planejado=100)
        try:
            d = self._stats(client)
            torno = next(m for m in d['desempenho_por_maquina'] if m['maquina'] == 'Torno Vertical')
            media, desvio = self._esperado_do_banco()
            assert torno['tempo_realizado_medio_min'] == media
            assert torno['desvio_medio_min'] == desvio
            assert torno['operacoes_fora_do_calculo'] >= 1
            assert d['operacoes_fora_do_calculo']['total'] == antes + 1
        finally:
            self._limpar(normal, esquecida)

    def test_sem_a_exclusao_a_media_seria_puxada_para_cima(self, client):
        """Prova de que a exclusão faz diferença: a operação esquecida tem 10x o tempo da normal."""
        normal = self._inserir(self.SEG.replace(hour=9), self.SEG.replace(hour=10), realizado=60, corrido=60)
        base = next(m for m in self._stats(client)['desempenho_por_maquina'] if m['maquina'] == 'Torno Vertical')
        esquecida = self._inserir(self.SEG + timedelta(days=4, hours=16), self.SEG + timedelta(days=7, hours=8),
                                  realizado=6000, corrido=9000)
        try:
            depois = next(m for m in self._stats(client)['desempenho_por_maquina'] if m['maquina'] == 'Torno Vertical')
            assert depois['tempo_realizado_medio_min'] == base['tempo_realizado_medio_min']
            assert depois['desvio_medio_min'] == base['desvio_medio_min']
        finally:
            self._limpar(normal, esquecida)

    def test_lista_de_excluidas_traz_os_dados_e_o_motivo(self, client):
        esquecida = self._inserir(self.SEG + timedelta(days=4, hours=16), self.SEG + timedelta(days=7, hours=8),
                                  realizado=120, corrido=3847, planejado=100)
        try:
            fora = self._stats(client)['operacoes_fora_do_calculo']
            assert fora['limiar_min'] == app_module.FORA_EXPEDIENTE_LIMIAR_MIN
            assert 'fora do expediente' in fora['motivos']['fora_do_expediente']
            assert 'muito acima do planejado' in fora['motivos']['muito_acima_do_planejado']
            item = next(o for o in fora['operacoes'] if o['corrido_min'] == 3847)
            assert item['expediente_min'] == 120 and item['planejado_min'] == 100 and item['maquina'] == 'Torno Vertical'
            assert {'os_numero', 'sequencia'} <= set(item)
        finally:
            self._limpar(esquecida)

    def test_hora_extra_pequena_continua_no_calculo(self, client):
        antes = self._stats(client)['operacoes_fora_do_calculo']['total']
        pequena = self._inserir(self.SEG.replace(hour=16, minute=30), self.SEG.replace(hour=17, minute=30),
                                realizado=30, corrido=60)          # diferença de 30 < 60
        try:
            assert self._stats(client)['operacoes_fora_do_calculo']['total'] == antes
        finally:
            self._limpar(pequena)

    def test_linha_antiga_sem_corrido_nao_e_excluida(self, client):
        antes = self._stats(client)['operacoes_fora_do_calculo']['total']
        conn = app_module.get_db()
        try:
            maquina_id = conn.execute("SELECT id FROM maquinas WHERE nome = 'Torno Vertical'").fetchone()[0]
            os_id = conn.execute('SELECT id FROM ordens_servico ORDER BY id DESC LIMIT 1').fetchone()[0]
            cur = conn.execute('''INSERT INTO alocacao_maquinas (ordem_servico_id, maquina_id, sequencia, status, tempo_realizado_min)
                                  VALUES (?, ?, 96, 'CONCLUIDO', 500)''', (os_id, maquina_id))
            conn.commit()
            aloc = cur.lastrowid
        finally:
            conn.close()
        try:
            assert self._stats(client)['operacoes_fora_do_calculo']['total'] == antes
        finally:
            self._limpar(aloc)

    def test_operacoes_endpoint_marca_a_excluida(self, client, monkeypatch):
        r = client.post('/api/notas', data=json.dumps({'peca_codigo': '40-091799', 'quantidade': 1}),
                        content_type='application/json')
        os_id = json.loads(r.data)['processamento']['os_id']
        ops = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)
        conn = app_module.get_db()
        try:
            conn.execute('''UPDATE alocacao_maquinas SET status='CONCLUIDO', inicio_real='2031-03-14T16:00:00',
                            fim_real='2031-03-17T08:00:00', tempo_realizado_min=120, tempo_realizado_corrido_min=3840
                            WHERE id = ?''', (ops[0]['id'],))
            conn.commit()
        finally:
            conn.close()
        op = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)[0]
        assert op['fora_do_expediente'] is True and op['excluida_dos_indicadores'] is True
        assert op['possivelmente_esquecida'] is False


class TestExclusaoPorTempoMuitoAcimaDoPlanejado:
    """O critério é a confiabilidade do dado, não o horário: 16 h de expediente numa operação
    de 2 h é tão suspeito quanto uma que atravessou a noite."""

    SEG = datetime(2031, 3, 10)
    _inserir = staticmethod(TestIndicadoresSemForaDoExpediente._inserir)
    _limpar = staticmethod(TestIndicadoresSemForaDoExpediente._limpar)
    _stats = staticmethod(TestIndicadoresSemForaDoExpediente._stats)

    def test_regra_pura_de_motivos(self):
        m = app_module.motivos_de_exclusao
        assert m('CONCLUIDO', 120, 120, 120) == []
        assert m('CONCLUIDO', 240, 240, 120) == []                                   # exatamente 2x: entra
        assert m('CONCLUIDO', 241, 241, 120) == ['muito_acima_do_planejado']         # dentro do expediente
        assert m('CONCLUIDO', 90, 930, 120) == ['fora_do_expediente']                # atravessou a noite, tempo normal
        assert m('CONCLUIDO', 1711, 4231, 150) == ['fora_do_expediente', 'muito_acima_do_planejado']   # o caso da OP 278
        assert m('EXECUTANDO', 1711, 4231, 150) == []                                # só concluída é excluída
        assert m('CONCLUIDO', 5000, 5000, None) == [] and m('CONCLUIDO', 5000, 5000, 0) == []
        assert m('CONCLUIDO', None, None, 120) == []

    def test_16h_de_expediente_numa_operacao_de_2h_sai_do_calculo_sem_atravessar_a_noite(self, client):
        antes = self._stats(client)['operacoes_fora_do_calculo']
        aloc = self._inserir(self.SEG.replace(hour=7), self.SEG + timedelta(days=1, hours=17), realizado=960, corrido=960,
                             planejado=120)
        try:
            d = self._stats(client)
            fora = d['operacoes_fora_do_calculo']
            assert fora['total'] == antes['total'] + 1
            assert fora['por_motivo']['muito_acima_do_planejado'] == antes['por_motivo']['muito_acima_do_planejado'] + 1
            assert fora['por_motivo']['fora_do_expediente'] == antes['por_motivo']['fora_do_expediente']   # corrido == expediente
            item = next(o for o in fora['operacoes'] if o['expediente_min'] == 960)
            assert item['motivos'] == ['muito_acima_do_planejado']
        finally:
            self._limpar(aloc)

    def test_nao_entra_na_media_nem_no_desvio(self, client):
        normal = self._inserir(self.SEG.replace(hour=9), self.SEG.replace(hour=10), realizado=60, corrido=60, planejado=60)
        base = next(m for m in self._stats(client)['desempenho_por_maquina'] if m['maquina'] == 'Torno Vertical')
        suspeita = self._inserir(self.SEG.replace(hour=7), self.SEG + timedelta(days=1, hours=17), realizado=960, corrido=960,
                                 planejado=120)
        try:
            depois = next(m for m in self._stats(client)['desempenho_por_maquina'] if m['maquina'] == 'Torno Vertical')
            assert depois['tempo_realizado_medio_min'] == base['tempo_realizado_medio_min']
            assert depois['desvio_medio_min'] == base['desvio_medio_min']
            assert depois['operacoes_fora_do_calculo'] == base['operacoes_fora_do_calculo'] + 1
        finally:
            self._limpar(normal, suspeita)

    def test_operacao_com_os_dois_motivos_conta_uma_vez_e_aparece_nos_dois(self, client):
        antes = self._stats(client)['operacoes_fora_do_calculo']
        aloc = self._inserir(self.SEG + timedelta(days=4, hours=16), self.SEG + timedelta(days=7, hours=8),
                             realizado=1711, corrido=4231, planejado=150)
        try:
            fora = self._stats(client)['operacoes_fora_do_calculo']
            assert fora['total'] == antes['total'] + 1
            assert fora['por_motivo']['fora_do_expediente'] == antes['por_motivo']['fora_do_expediente'] + 1
            assert fora['por_motivo']['muito_acima_do_planejado'] == antes['por_motivo']['muito_acima_do_planejado'] + 1
            item = next(o for o in fora['operacoes'] if o['corrido_min'] == 4231 and o['expediente_min'] == 1711)
            assert item['motivos'] == ['fora_do_expediente', 'muito_acima_do_planejado']
        finally:
            self._limpar(aloc)

    def test_exatamente_o_dobro_continua_no_calculo(self, client):
        antes = self._stats(client)['operacoes_fora_do_calculo']['total']
        aloc = self._inserir(self.SEG.replace(hour=7), self.SEG.replace(hour=11), realizado=240, corrido=240, planejado=120)
        try:
            assert self._stats(client)['operacoes_fora_do_calculo']['total'] == antes
        finally:
            self._limpar(aloc)

    def test_fator_configuravel_muda_a_exclusao(self, client, monkeypatch):
        aloc = self._inserir(self.SEG.replace(hour=7), self.SEG.replace(hour=14), realizado=420, corrido=420, planejado=120)   # 3,5x
        try:
            monkeypatch.setattr(app_module, 'OPERACAO_ESQUECIDA_FATOR', 4.0)
            antes = self._stats(client)['operacoes_fora_do_calculo']['total']
            monkeypatch.setattr(app_module, 'OPERACAO_ESQUECIDA_FATOR', 3.0)
            assert self._stats(client)['operacoes_fora_do_calculo']['total'] == antes + 1
        finally:
            self._limpar(aloc)

    def test_operacoes_endpoint_traz_os_motivos(self, client):
        r = client.post('/api/notas', data=json.dumps({'peca_codigo': '40-091799', 'quantidade': 1}),
                        content_type='application/json')
        os_id = json.loads(r.data)['processamento']['os_id']
        ops = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)
        conn = app_module.get_db()
        try:
            conn.execute("""UPDATE alocacao_maquinas SET status='CONCLUIDO', inicio_real='2031-03-10T07:00:00',
                            fim_real='2031-03-11T17:00:00', tempo_realizado_min=960, tempo_realizado_corrido_min=960
                            WHERE id = ?""", (ops[0]['id'],))
            conn.commit()
        finally:
            conn.close()
        op = json.loads(client.get(f'/api/ordens-servico/{os_id}/operacoes').data)[0]
        assert op['excluida_dos_indicadores'] is True and op['motivos_de_exclusao'] == ['muito_acima_do_planejado']
        assert op['fora_do_expediente'] is False          # o horário não é o motivo aqui
