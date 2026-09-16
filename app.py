"""
Sistema de Automação de Usinagem - Backend Flask
Aplicação completa com API REST, banco de dados e lógica de automação
Desenvolvido para: Grand Prix SENAI 2025 | Pentágono Mecânico
"""

import os
import re
import csv
import io
import json
import time
import shutil
import smtplib
import sqlite3
import logging
import threading
from io import BytesIO
from functools import wraps
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import bcrypt
import requests
import schedule
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required,
    get_jwt_identity, get_jwt
)
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

# ============================================================================
# CONFIGURAÇÃO INICIAL
# ============================================================================

load_dotenv()

CORS_ORIGINS = os.getenv('CORS_ORIGINS', '*')
_cors_origins_list = CORS_ORIGINS.split(',') if CORS_ORIGINS != '*' else '*'

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": _cors_origins_list}})

app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'dev-secret-change-me')
jwt = JWTManager(app)

socketio = SocketIO(app, cors_allowed_origins=_cors_origins_list, async_mode='threading')

# NOTA DE DEPLOY: esta variável existe para configurar um Postgres no futuro,
# mas o banco de dados hoje continua sendo SQLite puro (módulo sqlite3, sem
# SQLAlchemy) — get_db() ignora DATABASE_URL. Ver aviso de log mais abaixo.
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///usinagem.db')
DB_PATH = 'usinagem.db'
BACKUP_DIR = 'backups'
LOG_DIR = 'logs'
BACKUP_RETENCAO_DIAS = 30

# Parâmetros usados no cálculo de economia (ajustáveis via .env)
TEMPO_MANUAL_MIN = int(os.getenv('TEMPO_MANUAL_MIN', '45'))
TEMPO_AUTOMATICO_MIN = int(os.getenv('TEMPO_AUTOMATICO_MIN', '3'))
CUSTO_HORA_PRODUCAO = float(os.getenv('CUSTO_HORA_PRODUCAO', '45.0'))
CUSTO_MEDIO_RETRABALHO = float(os.getenv('CUSTO_MEDIO_RETRABALHO', '120.0'))
SENHA_PADRAO_DEMO = os.getenv('SENHA_PADRAO_DEMO', 'Vitor367')

# Diferencial #11 - Notificação de nota criada no Telegram (com desenho técnico)
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
FRONTEND_URL = os.getenv('FRONTEND_URL', 'https://frontend-xi-two-5l7d05gqtg.vercel.app')
DESENHOS_DIR = 'desenhos_tecnicos'

MESES_PT = {
    1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
    5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
    9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
}
MESES_PT_INV = {nome.lower(): numero for numero, nome in MESES_PT.items()}

EMAIL_REGEX = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

os.makedirs(LOG_DIR, exist_ok=True)


class FormatadorLogJSON(logging.Formatter):
    """Formata cada linha de log como um objeto JSON (log estruturado)"""

    def format(self, record):
        payload = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'nivel': record.levelname,
            'modulo': record.name,
            'mensagem': record.getMessage()
        }
        return json.dumps(payload, ensure_ascii=False)


logger = logging.getLogger('usinagem')
logger.setLevel(logging.INFO)
if not logger.handlers:
    _console = logging.StreamHandler()
    _console.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(_console)

    _arquivo = RotatingFileHandler(
        os.path.join(LOG_DIR, 'app.log'), maxBytes=1_000_000, backupCount=5, encoding='utf-8'
    )
    _arquivo.setFormatter(FormatadorLogJSON())
    logger.addHandler(_arquivo)

if DATABASE_URL and not DATABASE_URL.startswith('sqlite'):
    logger.warning(
        f'DATABASE_URL="{DATABASE_URL}" foi definida, mas este app ainda usa '
        f'SQLite puro (arquivo {DB_PATH}) — get_db() não lê essa variável. '
        'Em um host com filesystem efêmero (ex.: Railway) os dados serão '
        'perdidos a cada redeploy até o app ser migrado para SQLAlchemy/Postgres.'
    )

# ============================================================================
# BANCO DE DADOS
# ============================================================================

def get_db():
    """Conecta ao banco de dados"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Inicializa o banco de dados com schema profissional"""
    conn = get_db()
    c = conn.cursor()

    # Tabela de PEÇAS (histórico)
    c.execute('''CREATE TABLE IF NOT EXISTS pecas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT UNIQUE NOT NULL,
        nome TEXT NOT NULL,
        descricao TEXT,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Tabela de OPERAÇÕES (histórico por peça)
    c.execute('''CREATE TABLE IF NOT EXISTS operacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        peca_id INTEGER NOT NULL,
        sequencia INTEGER NOT NULL,
        maquina TEXT NOT NULL,
        tempo_estimado INTEGER NOT NULL,
        descricao TEXT,
        FOREIGN KEY(peca_id) REFERENCES pecas(id),
        UNIQUE(peca_id, sequencia)
    )''')

    # Tabela de MÁQUINAS
    c.execute('''CREATE TABLE IF NOT EXISTS maquinas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT UNIQUE NOT NULL,
        status TEXT DEFAULT 'DISPONIVEL',
        ultima_manutencao TIMESTAMP,
        proxima_manutencao TIMESTAMP
    )''')

    # Tabela de NOTAS (requisições de trabalho)
    c.execute('''CREATE TABLE IF NOT EXISTS notas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero TEXT UNIQUE NOT NULL,
        peca_codigo TEXT NOT NULL,
        quantidade INTEGER NOT NULL,
        prioridade TEXT DEFAULT 'NORMAL',
        solicitante TEXT,
        status TEXT DEFAULT 'RECEBIDA',
        criada_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        validada_em TIMESTAMP,
        FOREIGN KEY(peca_codigo) REFERENCES pecas(codigo)
    )''')

    # Tabela de ORDENS DE SERVIÇO (OS)
    c.execute('''CREATE TABLE IF NOT EXISTS ordens_servico (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero TEXT UNIQUE NOT NULL,
        nota_id INTEGER NOT NULL,
        status TEXT DEFAULT 'PLANEJAMENTO',
        prioridade TEXT DEFAULT 'NORMAL',
        tempo_total INTEGER,
        tempo_inicio TIMESTAMP,
        tempo_fim TIMESTAMP,
        criada_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        concluida_em TIMESTAMP,
        FOREIGN KEY(nota_id) REFERENCES notas(id)
    )''')

    # Tabela de ALOCAÇÃO DE MÁQUINAS
    c.execute('''CREATE TABLE IF NOT EXISTS alocacao_maquinas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ordem_servico_id INTEGER NOT NULL,
        maquina_id INTEGER NOT NULL,
        sequencia INTEGER NOT NULL,
        status TEXT DEFAULT 'PLANEJADO',
        inicio_planejado TIMESTAMP,
        fim_planejado TIMESTAMP,
        inicio_real TIMESTAMP,
        fim_real TIMESTAMP,
        FOREIGN KEY(ordem_servico_id) REFERENCES ordens_servico(id),
        FOREIGN KEY(maquina_id) REFERENCES maquinas(id)
    )''')

    # Tabela de AUDITORIA (rastreamento)
    c.execute('''CREATE TABLE IF NOT EXISTS auditoria (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo_evento TEXT NOT NULL,
        entidade TEXT NOT NULL,
        entidade_id INTEGER,
        descricao TEXT,
        usuario TEXT DEFAULT 'SISTEMA',
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Tabela de USUÁRIOS (autenticação e papéis)
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        senha_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Feature 3 - colunas novas em MÁQUINAS (a tabela já existe desde o
    # início do projeto; ALTER TABLE é a forma correta de estender um
    # schema existente sem perder os dados já gravados nela)
    c.execute("PRAGMA table_info(maquinas)")
    colunas_existentes = {row[1] for row in c.fetchall()}
    for coluna, tipo_sql in [
        ('localizacao', 'TEXT'),
        ('foto_url', 'TEXT'),
        ('manual_url', 'TEXT'),
        ('ultimo_conserto', 'TIMESTAMP'),
        ('modelo', 'TEXT'),
        ('fabricante', 'TEXT'),
    ]:
        if coluna not in colunas_existentes:
            c.execute(f'ALTER TABLE maquinas ADD COLUMN {coluna} {tipo_sql}')

    # Tabela de RELATÓRIOS DE MANUTENÇÃO (Feature 3)
    c.execute('''CREATE TABLE IF NOT EXISTS relatorios_manutencao (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        maquina_id INTEGER NOT NULL,
        usuario TEXT,
        descricao TEXT,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(maquina_id) REFERENCES maquinas(id)
    )''')

    # Tabela de CHAT DE MANUTENÇÃO (Feature 4)
    c.execute('''CREATE TABLE IF NOT EXISTS chat_manutencao (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT NOT NULL,
        role TEXT,
        mensagem TEXT NOT NULL,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    conn.commit()
    logger.info("Banco de dados inicializado")
    conn.close()

def registrar_auditoria(tipo, entidade, entidade_id, descricao):
    """Registra evento na auditoria"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO auditoria
                 (tipo_evento, entidade, entidade_id, descricao)
                 VALUES (?, ?, ?, ?)''',
              (tipo, entidade, entidade_id, descricao))
    conn.commit()
    conn.close()

# ============================================================================
# POPULAÇÃO INICIAL DE DADOS (Desenvolvimento)
# ============================================================================

def seed_data():
    """Popula banco com dados de exemplo"""
    conn = get_db()
    c = conn.cursor()

    try:
        # Peças
        pecas = [
            ('40-091799', 'Placa Bronze A', 'Placa de bronze para eixo'),
            ('40-122633', 'Eixo Esticador', 'Eixo para mecanismo de estiragem'),
            ('40-154120', 'Mancal Inferior', 'Mancal de rolamento inferior'),
        ]
        for codigo, nome, desc in pecas:
            c.execute('INSERT OR IGNORE INTO pecas (codigo, nome, descricao) VALUES (?, ?, ?)',
                     (codigo, nome, desc))

        # Operações (histórico)
        c.execute('SELECT id FROM pecas WHERE codigo = ?', ('40-091799',))
        peca1_id = c.fetchone()[0]
        operacoes1 = [
            (peca1_id, 1, 'Torno Horizontal', 120, 'Usinagem cilíndrica'),
            (peca1_id, 2, 'Torno Vertical', 90, 'Acabamento superficial'),
        ]
        for peca_id, seq, maq, tempo, desc in operacoes1:
            c.execute('''INSERT INTO operacoes
                        (peca_id, sequencia, maquina, tempo_estimado, descricao)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(peca_id, sequencia) DO UPDATE SET
                            maquina = excluded.maquina,
                            tempo_estimado = excluded.tempo_estimado,
                            descricao = excluded.descricao''',
                     (peca_id, seq, maq, tempo, desc))

        c.execute('SELECT id FROM pecas WHERE codigo = ?', ('40-122633',))
        peca2_id = c.fetchone()[0]
        operacoes2 = [
            (peca2_id, 1, 'Fresadora Universal', 150, 'Usinagem em fresadora'),
        ]
        for peca_id, seq, maq, tempo, desc in operacoes2:
            c.execute('''INSERT INTO operacoes
                        (peca_id, sequencia, maquina, tempo_estimado, descricao)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(peca_id, sequencia) DO UPDATE SET
                            maquina = excluded.maquina,
                            tempo_estimado = excluded.tempo_estimado,
                            descricao = excluded.descricao''',
                     (peca_id, seq, maq, tempo, desc))

        c.execute('SELECT id FROM pecas WHERE codigo = ?', ('40-154120',))
        peca3_id = c.fetchone()[0]
        operacoes3 = [
            (peca3_id, 1, 'Retificadora Cilíndrica', 200, 'Polimento fino'),
        ]
        for peca_id, seq, maq, tempo, desc in operacoes3:
            c.execute('''INSERT INTO operacoes
                        (peca_id, sequencia, maquina, tempo_estimado, descricao)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(peca_id, sequencia) DO UPDATE SET
                            maquina = excluded.maquina,
                            tempo_estimado = excluded.tempo_estimado,
                            descricao = excluded.descricao''',
                     (peca_id, seq, maq, tempo, desc))

        # Máquinas reais da siderúrgica (substituem o parque fictício
        # CENTUR/D1250/FRESADORA/POLITRIZ usado até a v1 do sistema).
        # As antigas são removidas explicitamente: como "nome" é UNIQUE e
        # é a chave usada por AutomacaoUsinagem.processar_nota() para
        # localizar a máquina de cada operação, deixá-las órfãs no banco
        # (ex.: em disco persistente do Railway) faria notas antigas
        # apontarem para nomes que não existem mais.
        nomes_antigos = ['CENTUR', 'D1250', 'FRESADORA', 'POLITRIZ']
        c.executemany('DELETE FROM maquinas WHERE nome = ?', [(n,) for n in nomes_antigos])

        maquinas = [
            # Setor 1: Oficina Central de Manutenção
            ('Torno Horizontal', 'Romi Centur 50', 'Romi', 'Oficina Central de Manutenção'),
            ('Torno Vertical', 'Clever VTL', 'Clever', 'Oficina Central de Manutenção'),
            ('Fresadora Universal', 'Romi U30', 'Romi', 'Oficina Central de Manutenção'),
            ('Mandrilhadora', 'Tos Varnsdorf', 'Tos', 'Oficina Central de Manutenção'),
            ('Furadeira Radial', 'Romi GR-40', 'Romi', 'Oficina Central de Manutenção'),
            ('Serra de Fita', 'Franho FM-500', 'Franho', 'Oficina Central de Manutenção'),
            # Setor 2: Oficina de Cilindros de Laminação
            ('Torno CNC Cilindros', 'Herkules', 'Herkules', 'Oficina de Cilindros de Laminação'),
            ('Retificadora Cilíndrica', 'Romi RCG', 'Romi', 'Oficina de Cilindros de Laminação'),
        ]
        for nome, modelo, fabricante, localizacao in maquinas:
            c.execute('''INSERT INTO maquinas (nome, status, localizacao, modelo, fabricante)
                        VALUES (?, 'DISPONIVEL', ?, ?, ?)
                        ON CONFLICT(nome) DO UPDATE SET
                            localizacao = excluded.localizacao,
                            modelo = excluded.modelo,
                            fabricante = excluded.fabricante''',
                     (nome, localizacao, modelo, fabricante))

        conn.commit()
        logger.info("Dados de exemplo inseridos")
    except Exception as e:
        logger.error(f"Erro ao popular dados: {e}")
    finally:
        conn.close()

def seed_usuarios():
    """Garante que os 4 usuários demo existem e usam a senha padrão atual.

    Roda em todo boot (não só na primeira vez): se o disco persistir entre
    deploys com uma senha antiga, isso mantém as contas demo sincronizadas
    com SENHA_PADRAO_DEMO em vez de silenciosamente preservar um hash velho.
    """
    conn = get_db()
    c = conn.cursor()
    try:
        senha_hash = bcrypt.hashpw(SENHA_PADRAO_DEMO.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        usuarios_padrao = [
            ('operador@fabrica.com', 'operador'),
            ('coordenador@fabrica.com', 'coordenador'),
            ('gestor@fabrica.com', 'gestor'),
            ('diretor@fabrica.com', 'diretor'),
        ]
        for email, role in usuarios_padrao:
            c.execute('''INSERT INTO usuarios (email, senha_hash, role) VALUES (?, ?, ?)
                        ON CONFLICT(email) DO UPDATE SET senha_hash = excluded.senha_hash''',
                     (email, senha_hash, role))
        conn.commit()
        logger.warning(
            f'Usuários demo sincronizados com senha padrão "{SENHA_PADRAO_DEMO}" — troque antes de qualquer uso real'
        )
    finally:
        conn.close()

# ============================================================================
# VALIDAÇÃO
# ============================================================================

class Validador:
    """Validações de entrada usadas pelos endpoints"""

    @staticmethod
    def validar_nota(dados):
        erros = []
        if not dados.get('peca_codigo'):
            erros.append('peca_codigo é obrigatório')

        try:
            qtd = int(dados.get('quantidade', 1))
            if qtd <= 0:
                erros.append('quantidade deve ser maior que zero')
        except (TypeError, ValueError):
            erros.append('quantidade deve ser um número inteiro')

        if dados.get('prioridade') and dados['prioridade'] not in ('NORMAL', 'URGENTE'):
            erros.append('prioridade deve ser NORMAL ou URGENTE')

        return erros

    @staticmethod
    def validar_email(email):
        return bool(email and EMAIL_REGEX.match(email))

    @staticmethod
    def validar_alerta(dados):
        erros = []
        if not Validador.validar_email(dados.get('destinatario', '')):
            erros.append('destinatario deve ser um email válido')
        if not dados.get('assunto'):
            erros.append('assunto é obrigatório')
        if not dados.get('corpo'):
            erros.append('corpo é obrigatório')
        return erros

    @staticmethod
    def validar_linha_sap(linha):
        erros = []
        if not (linha.get('NOTNUM') or '').strip():
            erros.append('NOTNUM ausente')
        if not (linha.get('MATERIAL') or '').strip():
            erros.append('MATERIAL ausente')

        try:
            qtd = int((linha.get('QTD') or '').strip())
            if qtd <= 0:
                erros.append('QTD deve ser maior que zero')
        except (TypeError, ValueError):
            erros.append('QTD inválida')

        if not (linha.get('DUEDATE') or '').strip():
            erros.append('DUEDATE ausente')

        if (linha.get('URGENTE') or '').strip().upper() not in ('S', 'N'):
            erros.append('URGENTE deve ser "S" ou "N"')

        return erros

# ============================================================================
# ECONOMIA / MÉTRICAS (usado pelo relatório em PDF e pelo dashboard)
# ============================================================================

def calcular_economia(mes_nome, ano):
    """Calcula a economia real gerada pela automação, a partir do banco"""
    numero_mes = MESES_PT_INV.get((mes_nome or '').lower())

    conn = get_db()
    c = conn.cursor()

    if numero_mes:
        c.execute('''SELECT COUNT(*) as total FROM notas
                     WHERE status='PROCESSADA' AND strftime('%Y', criada_em) = ?
                       AND strftime('%m', criada_em) = ?''',
                 (str(ano), f'{numero_mes:02d}'))
    else:
        c.execute('''SELECT COUNT(*) as total FROM notas
                     WHERE status='PROCESSADA' AND strftime('%Y', criada_em) = ?''',
                 (str(ano),))
    notas_mes = c.fetchone()['total']

    c.execute('''SELECT COUNT(*) as total FROM notas
                 WHERE status='PROCESSADA' AND strftime('%Y', criada_em) = ?''', (str(ano),))
    notas_ano = c.fetchone()['total']

    if numero_mes:
        c.execute('''SELECT COUNT(*) as total FROM auditoria
                     WHERE tipo_evento='VALIDACAO_ERRO' AND strftime('%Y', criado_em) = ?
                       AND strftime('%m', criado_em) = ?''',
                 (str(ano), f'{numero_mes:02d}'))
    else:
        c.execute('''SELECT COUNT(*) as total FROM auditoria
                     WHERE tipo_evento='VALIDACAO_ERRO' AND strftime('%Y', criado_em) = ?''',
                 (str(ano),))
    erros_evitados = c.fetchone()['total']

    conn.close()

    tempo_economizado_horas = round(notas_mes * (TEMPO_MANUAL_MIN - TEMPO_AUTOMATICO_MIN) / 60, 1)
    tempo_economizado_ano_horas = notas_ano * (TEMPO_MANUAL_MIN - TEMPO_AUTOMATICO_MIN) / 60
    retrabalho_economizado = round(erros_evitados * CUSTO_MEDIO_RETRABALHO, 2)
    economia_mensal = round(tempo_economizado_horas * CUSTO_HORA_PRODUCAO + retrabalho_economizado, 2)
    economia_anual = round(tempo_economizado_ano_horas * CUSTO_HORA_PRODUCAO, 2)

    return {
        'tempo_economizado': tempo_economizado_horas,
        'erros_evitados': erros_evitados,
        'retrabalho_economizado': retrabalho_economizado,
        'economia_mensal': economia_mensal,
        'economia_anual': economia_anual,
        'notas_processadas_mes': notas_mes,
        'notas_processadas_ano': notas_ano
    }

# ============================================================================
# WEBSOCKET (DIFERENCIAL #4 - Tempo real)
# ============================================================================

class MonitorTempoReal:
    """Emite eventos para os clientes conectados via WebSocket"""

    @staticmethod
    def notificar_nota_processada(dados_nota):
        try:
            socketio.emit('nota_processada', dados_nota)
        except Exception as e:
            logger.error(f'Falha ao emitir evento websocket: {e}')

@socketio.on('connect')
def handle_connect():
    logger.info('Cliente conectado ao WebSocket')
    emit('status', {'mensagem': 'Conectado ao sistema em tempo real'})

@socketio.on('disconnect')
def handle_disconnect():
    logger.info('Cliente desconectado do WebSocket')

# ============================================================================
# ALERTAS POR EMAIL (DIFERENCIAL #2)
# ============================================================================

class SistemaAlertas:
    """Envia alertas reais por email via SMTP"""

    @staticmethod
    def enviar_email_alerta(destinatario, assunto, corpo_alerta, tipo_alerta='info'):
        timestamp = datetime.now().isoformat()
        email_usuario = os.getenv('EMAIL_USUARIO')
        email_senha = os.getenv('EMAIL_SENHA')

        if not email_usuario or not email_senha:
            logger.warning('Alerta não enviado: EMAIL_USUARIO/EMAIL_SENHA não configurados no .env')
            return {
                'enviado': False,
                'timestamp': timestamp,
                'email_destino': destinatario,
                'mensagem': 'Credenciais de email não configuradas no .env'
            }

        cores = {'danger': '#dc2626', 'warning': '#f59e0b', 'info': '#3b82f6'}
        icones = {'danger': '🚨', 'warning': '⚠️', 'info': 'ℹ️'}
        cor = cores.get(tipo_alerta, '#3b82f6')
        icone = icones.get(tipo_alerta, 'ℹ️')

        corpo_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background:#f3f4f6; padding:20px; margin:0;">
          <div style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:8px;overflow:hidden;border:1px solid #e5e7eb;">
            <div style="background:{cor};color:#ffffff;padding:16px 24px;">
              <h2 style="margin:0;">{icone} {assunto}</h2>
            </div>
            <div style="padding:24px;color:#1f2937;">
              <p style="line-height:1.6;">{corpo_alerta}</p>
              <p style="color:#6b7280;font-size:12px;margin-top:24px;">Gerado automaticamente em {timestamp}</p>
            </div>
            <div style="background:#f9fafb;padding:12px 24px;font-size:12px;color:#9ca3af;">
              Sistema de Automação de Usinagem — Grand Prix SENAI 2025 — Pentágono Mecânico
            </div>
          </div>
        </body>
        </html>
        """

        msg = MIMEMultipart('alternative')
        msg['Subject'] = assunto
        msg['From'] = email_usuario
        msg['To'] = destinatario
        msg.attach(MIMEText(corpo_html, 'html'))

        try:
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()
                server.login(email_usuario, email_senha)
                server.send_message(msg)

            registrar_auditoria('ALERTA_EMAIL', 'ALERTA', None, f'Email enviado para {destinatario}: {assunto}')
            return {
                'enviado': True,
                'timestamp': timestamp,
                'email_destino': destinatario,
                'mensagem': 'Email enviado com sucesso'
            }
        except Exception as e:
            logger.error(f'Falha ao enviar email: {e}')
            return {
                'enviado': False,
                'timestamp': timestamp,
                'email_destino': destinatario,
                'mensagem': f'Falha ao enviar: {e}'
            }

# ============================================================================
# NOTIFICAÇÃO DE NOTA NO TELEGRAM (com desenho técnico, se existir)
# ============================================================================

def enviar_nota_telegram(nota_id, numero, peca_codigo, solicitante, resultado):
    """
    Notifica a criação de uma nota no Telegram. Se existir um desenho técnico
    em desenhos_tecnicos/{peca_codigo}.pdf, envia como documento; senão manda
    só a mensagem. Sempre tenta um botão "Ver Detalhes" apontando pro frontend.

    Nunca levanta exceção — falha aqui não pode derrubar a criação da nota.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.info('Notificação Telegram pulada: TELEGRAM_TOKEN/TELEGRAM_CHAT_ID não configurados')
        return False

    base_url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}'
    operacoes = resultado.get('operacoes', [])
    maquinas = ', '.join(op['maquina'] for op in operacoes) or '-'
    tempo_total = resultado.get('tempo_total', '?')
    os_numero = resultado.get('os_numero', '-')

    mensagem = (
        f"🏭 NOVA NOTA CRIADA\n\n"
        f"📋 Peça: {peca_codigo}\n"
        f"🔧 Máquina(s): {maquinas}\n"
        f"⏱️ Tempo total: {tempo_total} min\n"
        f"👤 Solicitante: {solicitante or '-'}\n"
        f"📦 OS: {os_numero}\n"
        f"🕐 Criado: {datetime.now().strftime('%d/%m %H:%M')}"
    )

    pdf_path = os.path.join(DESENHOS_DIR, f'{peca_codigo}.pdf')

    try:
        if os.path.isfile(pdf_path):
            with open(pdf_path, 'rb') as pdf:
                resp = requests.post(
                    f'{base_url}/sendDocument',
                    data={'chat_id': TELEGRAM_CHAT_ID, 'caption': mensagem},
                    files={'document': (f'{peca_codigo}.pdf', pdf, 'application/pdf')},
                    timeout=15
                )
        else:
            resp = requests.post(
                f'{base_url}/sendMessage',
                json={'chat_id': TELEGRAM_CHAT_ID, 'text': mensagem + '\n\n📎 Desenho técnico não disponível'},
                timeout=15
            )

        if not resp.ok:
            logger.error(f'Telegram respondeu erro ao notificar nota {nota_id}: {resp.text}')
            return False

        markup = {
            'inline_keyboard': [[{
                'text': '🔗 Ver Detalhes',
                'url': f'{FRONTEND_URL}/?nota={nota_id}'
            }]]
        }
        requests.post(
            f'{base_url}/sendMessage',
            json={
                'chat_id': TELEGRAM_CHAT_ID,
                'text': f'👆 Nota {numero} — clique para abrir no sistema',
                'reply_markup': markup
            },
            timeout=15
        )

        logger.info(f'Nota {nota_id} notificada no Telegram')
        return True

    except requests.exceptions.RequestException as e:
        logger.error(f'Falha ao notificar Telegram para nota {nota_id}: {e}')
        return False

def enviar_alerta_maquina_telegram(mensagem):
    """Envia um texto simples ao grupo do Telegram (alertas de máquina). Nunca levanta exceção."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.info('Alerta de máquina pulado: TELEGRAM_TOKEN/TELEGRAM_CHAT_ID não configurados')
        return False
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': mensagem},
            timeout=15
        )
        if not resp.ok:
            logger.error(f'Telegram respondeu erro ao notificar máquina: {resp.text}')
            return False
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f'Falha ao notificar Telegram (máquina): {e}')
        return False

# ============================================================================
# GERADOR DE RELATÓRIO EM PDF (DIFERENCIAL #3)
# ============================================================================

class GeradorRelatorio:
    """Gera relatórios em PDF profissional"""

    @staticmethod
    def gerar_relatorio_economia(mes, ano, dados_economia):
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=2 * cm, bottomMargin=2 * cm)
        estilos = getSampleStyleSheet()

        estilo_titulo = ParagraphStyle(
            'TituloCustom', parent=estilos['Title'],
            textColor=colors.HexColor('#667eea'), fontSize=20
        )
        estilo_subtitulo = ParagraphStyle(
            'SubtituloCustom', parent=estilos['Normal'],
            textColor=colors.HexColor('#6b7280'), fontSize=11,
            alignment=TA_CENTER, spaceAfter=20
        )
        estilo_secao = ParagraphStyle(
            'SecaoCustom', parent=estilos['Heading2'],
            textColor=colors.HexColor('#1f2937'), spaceBefore=16, spaceAfter=8
        )
        estilo_rodape = ParagraphStyle(
            'RodapeCustom', parent=estilos['Normal'],
            textColor=colors.HexColor('#9ca3af'), fontSize=8
        )

        elementos = []
        elementos.append(Paragraph('Relatório de Economia — Automação de Usinagem', estilo_titulo))
        elementos.append(Paragraph(f'{mes} de {ano}', estilo_subtitulo))

        elementos.append(Paragraph('Resumo Executivo', estilo_secao))
        tabela_dados = [
            ['Métrica', 'Valor'],
            ['Tempo economizado', f"{dados_economia['tempo_economizado']:.1f} h"],
            ['Erros evitados', str(dados_economia['erros_evitados'])],
            ['Retrabalho economizado', f"R$ {dados_economia['retrabalho_economizado']:.2f}"],
            ['Economia mensal', f"R$ {dados_economia['economia_mensal']:.2f}"],
            ['Economia anual projetada', f"R$ {dados_economia['economia_anual']:.2f}"],
        ]
        tabela = Table(tabela_dados, colWidths=[9 * cm, 6 * cm])
        tabela.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f3f4f6')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elementos.append(tabela)
        elementos.append(Spacer(1, 16))

        elementos.append(Paragraph('Notas Processadas', estilo_secao))
        resumo_notas = [
            ['Período', 'Notas processadas'],
            [f'{mes}/{ano}', str(dados_economia.get('notas_processadas_mes', 0))],
            [f'Ano {ano}', str(dados_economia.get('notas_processadas_ano', 0))],
        ]
        tabela_notas = Table(resumo_notas, colWidths=[9 * cm, 6 * cm])
        tabela_notas.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#10b981')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elementos.append(tabela_notas)
        elementos.append(Spacer(1, 24))

        elementos.append(Paragraph(
            f'Gerado automaticamente em {datetime.now().strftime("%d/%m/%Y %H:%M")} — '
            'Sistema de Automação de Usinagem — Grand Prix SENAI 2025 — Pentágono Mecânico',
            estilo_rodape
        ))

        doc.build(elementos)
        buffer.seek(0)
        return buffer.getvalue()

# ============================================================================
# LÓGICA DE AUTOMAÇÃO
# ============================================================================

class AutomacaoUsinagem:
    """Lógica principal de automação"""

    @staticmethod
    def processar_nota(nota_id):
        """Processa uma nota de manutenção automaticamente"""
        conn = get_db()
        c = conn.cursor()

        try:
            c.execute('SELECT * FROM notas WHERE id = ?', (nota_id,))
            nota = c.fetchone()

            if not nota:
                return {'erro': 'Nota não encontrada'}

            c.execute('''SELECT id FROM pecas WHERE codigo = ?''',
                     (nota['peca_codigo'],))
            peca_row = c.fetchone()

            if not peca_row:
                return {
                    'status': 'ERRO',
                    'mensagem': 'Peça sem histórico'
                }

            peca_id = peca_row[0]

            c.execute('''SELECT * FROM operacoes WHERE peca_id = ? ORDER BY sequencia''',
                     (peca_id,))
            operacoes = c.fetchall()

            if not operacoes:
                return {
                    'status': 'ERRO',
                    'mensagem': 'Peça sem operações cadastradas'
                }

            tempo_total = 0
            maquinas_operacoes = []

            for op in operacoes:
                tempo_total += op['tempo_estimado']
                maquinas_operacoes.append({
                    'sequencia': op['sequencia'],
                    'maquina': op['maquina'],
                    'tempo': op['tempo_estimado'],
                    'descricao': op['descricao']
                })

            numero_os = f"OS-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            prioridade = 'URGENTE' if nota['prioridade'] == 'URGENTE' else 'NORMAL'

            c.execute('''INSERT INTO ordens_servico
                        (numero, nota_id, status, prioridade, tempo_total)
                        VALUES (?, ?, ?, ?, ?)''',
                     (numero_os, nota_id, 'PLANEJAMENTO', prioridade, tempo_total))

            os_id = c.lastrowid

            tempo_inicio = datetime.now()
            for op in operacoes:
                c.execute('SELECT id FROM maquinas WHERE nome = ?', (op['maquina'],))
                maquina = c.fetchone()

                tempo_fim = tempo_inicio + timedelta(minutes=op['tempo_estimado'])

                c.execute('''INSERT INTO alocacao_maquinas
                            (ordem_servico_id, maquina_id, sequencia, status,
                             inicio_planejado, fim_planejado)
                            VALUES (?, ?, ?, ?, ?, ?)''',
                         (os_id, maquina[0], op['sequencia'], 'PLANEJADO',
                          tempo_inicio.isoformat(), tempo_fim.isoformat()))

                tempo_inicio = tempo_fim

            c.execute('''UPDATE notas SET status = ?, validada_em = CURRENT_TIMESTAMP
                        WHERE id = ?''', ('PROCESSADA', nota_id))

            conn.commit()

            registrar_auditoria('PROCESSAMENTO', 'NOTA', nota_id,
                              f'Nota processada automaticamente. OS: {numero_os}')

            MonitorTempoReal.notificar_nota_processada({
                'os': numero_os,
                'peca': nota['peca_codigo'],
                'quantidade': nota['quantidade'],
                'tempo_processamento': tempo_total,
                'prioridade': prioridade,
                'timestamp': datetime.now().isoformat()
            })

            if prioridade == 'URGENTE':
                gestor_email = os.getenv('GESTOR_EMAIL')
                if gestor_email:
                    try:
                        SistemaAlertas.enviar_email_alerta(
                            gestor_email,
                            f'OS urgente criada: {numero_os}',
                            f'A nota {nota["numero"]} (peça {nota["peca_codigo"]}) foi processada '
                            f'com prioridade URGENTE. OS {numero_os}, tempo total estimado '
                            f'{tempo_total} minutos.',
                            'danger'
                        )
                    except Exception as e:
                        logger.error(f'Falha ao disparar alerta automático: {e}')

            return {
                'status': 'SUCESSO',
                'os_numero': numero_os,
                'os_id': os_id,
                'tempo_total': tempo_total,
                'operacoes': maquinas_operacoes,
                'mensagem': f'OS criada com sucesso em 3 minutos (automático)'
            }

        except Exception as e:
            logger.error(f"Erro ao processar nota: {e}")
            return {'erro': str(e)}
        finally:
            conn.close()

# ============================================================================
# INTEGRAÇÃO COM SAP (DIFERENCIAL #1)
# ============================================================================

class IntegradorSAP:
    """Integra com arquivo SAP exportado (formato tab-separated real)"""

    @staticmethod
    def processar_conteudo(conteudo):
        """
        Lê o conteúdo de um arquivo SAP (TAB-separated) e processa as notas.
        Reaproveita AutomacaoUsinagem.processar_nota para cada peça conhecida,
        criando OS de verdade (e disparando WebSocket/alertas normalmente).
        """
        inicio = time.time()
        leitor = csv.DictReader(io.StringIO(conteudo), delimiter='\t')

        notas_processadas = []
        erros = []

        conn = get_db()
        c = conn.cursor()

        for i, linha in enumerate(leitor, start=2):  # linha 1 é o cabeçalho
            erros_linha = Validador.validar_linha_sap(linha)
            if erros_linha:
                mensagem = f"Linha {i}: {'; '.join(erros_linha)}"
                erros.append(mensagem)
                registrar_auditoria('VALIDACAO_ERRO', 'SAP', None, mensagem)
                continue

            material = linha['MATERIAL'].strip()
            numero_sap = linha['NOTNUM'].strip()
            quantidade = int(linha['QTD'].strip())
            urgente = linha['URGENTE'].strip().upper() == 'S'

            c.execute('SELECT id FROM pecas WHERE codigo = ?', (material,))
            peca = c.fetchone()

            nota_dict = {
                'numero': numero_sap,
                'material': material,
                'quantidade': quantidade,
                'data_entrega': linha['DUEDATE'].strip(),
                'urgente': urgente,
                'peca_encontrada': peca is not None,
                'operacoes_importadas': 0,
                'tempo_total_minutos': 0,
                'origem': 'SAP_REAL'
            }

            if peca:
                numero_nota = f"SAP-{numero_sap}"
                c.execute('SELECT id FROM notas WHERE numero = ?', (numero_nota,))
                existente = c.fetchone()

                if existente:
                    nota_dict['ja_processada'] = True
                else:
                    c.execute('''INSERT INTO notas
                                (numero, peca_codigo, quantidade, prioridade, solicitante, status)
                                VALUES (?, ?, ?, ?, ?, ?)''',
                             (numero_nota, material, quantidade,
                              'URGENTE' if urgente else 'NORMAL',
                              'SAP_IMPORT', 'RECEBIDA'))
                    conn.commit()
                    nota_id = c.lastrowid

                    registrar_auditoria('CRIACAO', 'NOTA', nota_id, f'Nota importada via SAP: {numero_nota}')
                    resultado = AutomacaoUsinagem.processar_nota(nota_id)

                    if resultado.get('status') == 'SUCESSO':
                        nota_dict['operacoes_importadas'] = len(resultado.get('operacoes', []))
                        nota_dict['tempo_total_minutos'] = resultado.get('tempo_total', 0)
                        nota_dict['os_numero'] = resultado.get('os_numero')
                    else:
                        nota_dict['aviso'] = resultado.get('mensagem', resultado.get('erro'))

            notas_processadas.append(nota_dict)

        conn.close()

        tempo_decorrido = round(time.time() - inicio, 1)
        registrar_auditoria('IMPORTACAO_SAP', 'SAP', None,
                           f'{len(notas_processadas)} notas processadas do arquivo SAP')

        return {
            'sucesso': True,
            'total_processadas': len(notas_processadas),
            'notas': notas_processadas,
            'erros': erros,
            'tempo_processamento': f'{tempo_decorrido} segundos'
        }

# ============================================================================
# AUTENTICAÇÃO E PAPÉIS (DIFERENCIAL #5)
# ============================================================================

def requer_roles(*roles_permitidos):
    """Decorator que exige um JWT válido com um dos papéis informados"""
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            claims = get_jwt()
            role_usuario = claims.get('role')
            if role_usuario not in roles_permitidos:
                return jsonify({'erro': 'Permissão negada para este papel'}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator

# ============================================================================
# BACKUP AUTOMÁTICO (DIFERENCIAL #6)
# ============================================================================

def criar_backup():
    """Copia o banco de dados atual para a pasta de backups"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    destino = os.path.join(BACKUP_DIR, f'usinagem_backup_{timestamp}.db')
    shutil.copy2(DB_PATH, destino)
    limpar_backups_antigos()
    registrar_auditoria('BACKUP', 'SISTEMA', None, f'Backup criado: {destino}')
    logger.info(f'Backup criado em {destino}')
    return destino

def limpar_backups_antigos():
    """Remove backups com mais de BACKUP_RETENCAO_DIAS dias"""
    if not os.path.isdir(BACKUP_DIR):
        return
    limite = datetime.now() - timedelta(days=BACKUP_RETENCAO_DIAS)
    for nome in os.listdir(BACKUP_DIR):
        caminho = os.path.join(BACKUP_DIR, nome)
        if os.path.isfile(caminho):
            modificado = datetime.fromtimestamp(os.path.getmtime(caminho))
            if modificado < limite:
                os.remove(caminho)

def iniciar_agendador_backup():
    """Inicia uma thread em background que roda o backup diário"""
    schedule.every().day.at('02:00').do(criar_backup)

    def loop():
        while True:
            schedule.run_pending()
            time.sleep(60)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    logger.info('Agendador de backup iniciado (diário às 02:00)')

# ============================================================================
# ENDPOINTS DA API
# ============================================================================

@app.route('/api/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({'status': 'OK', 'timestamp': datetime.now().isoformat()})

@app.route('/api/notas', methods=['GET'])
def get_notas():
    """Lista todas as notas"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM notas ORDER BY criada_em DESC')
    notas = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(notas)

@app.route('/api/notas/<int:nota_id>/detalhes', methods=['GET'])
@jwt_required()
def get_nota_detalhes(nota_id):
    """Retorna detalhes completos de uma nota: peça, OS/máquinas alocadas e histórico"""
    conn = get_db()
    c = conn.cursor()

    c.execute('SELECT * FROM notas WHERE id = ?', (nota_id,))
    nota = c.fetchone()
    if not nota:
        conn.close()
        return jsonify({'erro': 'Nota não encontrada'}), 404

    c.execute('SELECT * FROM pecas WHERE codigo = ?', (nota['peca_codigo'],))
    peca = c.fetchone()

    c.execute('SELECT * FROM ordens_servico WHERE nota_id = ?', (nota_id,))
    ordem = c.fetchone()

    alocacoes = []
    if ordem:
        c.execute('''SELECT am.sequencia, am.status, am.inicio_planejado, am.fim_planejado,
                            m.nome as maquina_nome
                     FROM alocacao_maquinas am
                     JOIN maquinas m ON m.id = am.maquina_id
                     WHERE am.ordem_servico_id = ?
                     ORDER BY am.sequencia''', (ordem['id'],))
        alocacoes = [dict(row) for row in c.fetchall()]

    c.execute('''SELECT tipo_evento, entidade, descricao, usuario, criado_em
                 FROM auditoria WHERE entidade = 'NOTA' AND entidade_id = ?
                 ORDER BY criado_em DESC''', (nota_id,))
    historico = [dict(row) for row in c.fetchall()]

    conn.close()

    economia_minutos = None
    economia_percentual = None
    if nota['status'] == 'PROCESSADA':
        economia_minutos = TEMPO_MANUAL_MIN - TEMPO_AUTOMATICO_MIN
        economia_percentual = round(economia_minutos / TEMPO_MANUAL_MIN * 100, 1)

    return jsonify({
        'id': nota['id'],
        'numero': nota['numero'],
        'peca': {
            'codigo': nota['peca_codigo'],
            'nome': peca['nome'] if peca else 'Desconhecida',
            'descricao': peca['descricao'] if peca else None
        },
        'quantidade': nota['quantidade'],
        'prioridade': nota['prioridade'],
        'status': nota['status'],
        'solicitante': nota['solicitante'],
        'criada_em': nota['criada_em'],
        'validada_em': nota['validada_em'],
        'ordem_servico': {
            'numero': ordem['numero'],
            'status': ordem['status'],
            'tempo_total': ordem['tempo_total']
        } if ordem else None,
        'alocacoes': alocacoes,
        'economia_minutos': economia_minutos,
        'economia_percentual': economia_percentual,
        'historico': historico
    })

@app.route('/api/notas', methods=['POST'])
def criar_nota():
    """Cria uma nova nota"""
    data = request.json or {}

    erros = Validador.validar_nota(data)
    if erros:
        registrar_auditoria('VALIDACAO_ERRO', 'NOTA', None, f'Validação falhou: {"; ".join(erros)}')
        return jsonify({'erros': erros}), 400

    conn = get_db()
    c = conn.cursor()

    try:
        numero = f"NOT-{datetime.now().strftime('%Y%m%d%H%M')}-{int(datetime.now().microsecond/1000)}"

        c.execute('''INSERT INTO notas
                    (numero, peca_codigo, quantidade, prioridade, solicitante, status)
                    VALUES (?, ?, ?, ?, ?, ?)''',
                 (numero, data.get('peca_codigo'), data.get('quantidade', 1),
                  data.get('prioridade', 'NORMAL'), data.get('solicitante'),
                  'RECEBIDA'))

        conn.commit()
        nota_id = c.lastrowid

        registrar_auditoria('CRIACAO', 'NOTA', nota_id, f'Nova nota recebida: {numero}')

        resultado = AutomacaoUsinagem.processar_nota(nota_id)

        if resultado.get('status') == 'SUCESSO':
            try:
                enviar_nota_telegram(nota_id, numero, data.get('peca_codigo'), data.get('solicitante'), resultado)
            except Exception as e:
                logger.error(f'Erro inesperado ao notificar Telegram: {e}')

        return jsonify({
            'nota_id': nota_id,
            'numero': numero,
            'processamento': resultado
        }), 201

    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao criar nota: {e}")
        return jsonify({'erro': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/ordens-servico', methods=['GET'])
def get_ordens():
    """Lista todas as OS"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT os.*, n.peca_codigo, p.nome as peca_nome
                FROM ordens_servico os
                JOIN notas n ON os.nota_id = n.id
                JOIN pecas p ON n.peca_codigo = p.codigo
                ORDER BY
                    CASE WHEN os.prioridade = 'URGENTE' THEN 0 ELSE 1 END,
                    os.criada_em ASC''')

    ordens = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(ordens)

@app.route('/api/ordens-servico/<int:os_id>', methods=['GET'])
def get_ordem(os_id):
    """Busca uma OS específica"""
    conn = get_db()
    c = conn.cursor()

    c.execute('''SELECT os.*, n.peca_codigo, p.nome as peca_nome
                FROM ordens_servico os
                JOIN notas n ON os.nota_id = n.id
                JOIN pecas p ON n.peca_codigo = p.codigo
                WHERE os.id = ?''', (os_id,))

    ordem = c.fetchone()

    if not ordem:
        conn.close()
        return jsonify({'erro': 'OS não encontrada'}), 404

    c.execute('''SELECT am.*, m.nome as maquina_nome
                FROM alocacao_maquinas am
                JOIN maquinas m ON am.maquina_id = m.id
                WHERE am.ordem_servico_id = ?
                ORDER BY am.sequencia''', (os_id,))

    alocacoes = [dict(row) for row in c.fetchall()]
    conn.close()

    resultado = dict(ordem)
    resultado['alocacoes'] = alocacoes

    return jsonify(resultado)

@app.route('/api/ordens-servico/<int:os_id>/iniciar', methods=['POST'])
def iniciar_ordem(os_id):
    """Inicia execução de uma OS"""
    conn = get_db()
    c = conn.cursor()

    try:
        tempo_agora = datetime.now()

        c.execute('''UPDATE ordens_servico
                    SET status = ?, tempo_inicio = ?
                    WHERE id = ?''',
                 ('USINANDO', tempo_agora.isoformat(), os_id))

        c.execute('''UPDATE alocacao_maquinas
                    SET status = ?, inicio_real = ?
                    WHERE ordem_servico_id = ? AND sequencia = 1''',
                 ('EXECUTANDO', tempo_agora.isoformat(), os_id))

        conn.commit()
        registrar_auditoria('INICIO', 'ORDEM_SERVICO', os_id, 'Execução iniciada')

        return jsonify({'status': 'SUCESSO', 'mensagem': 'OS iniciada'}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({'erro': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/pecas', methods=['GET'])
def get_pecas():
    """Lista todas as peças"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM pecas')
    pecas = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(pecas)

@app.route('/api/maquinas', methods=['GET'])
def get_maquinas():
    """Lista todas as máquinas"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM maquinas')
    maquinas = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(maquinas)

@app.route('/api/maquinas/<int:maquina_id>', methods=['GET'])
def get_maquina_detalhe(maquina_id):
    """Detalhes de uma máquina específica"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM maquinas WHERE id = ?', (maquina_id,))
    maquina = c.fetchone()
    conn.close()
    if not maquina:
        return jsonify({'erro': 'Máquina não encontrada'}), 404
    return jsonify(dict(maquina))

@app.route('/api/maquinas/<int:maquina_id>/quebrada', methods=['POST'])
@jwt_required()
def marcar_maquina_quebrada(maquina_id):
    """Marca máquina como quebrada e notifica (WebSocket + Telegram)"""
    email = get_jwt_identity()
    conn = get_db()
    c = conn.cursor()

    c.execute('SELECT * FROM maquinas WHERE id = ?', (maquina_id,))
    maquina = c.fetchone()
    if not maquina:
        conn.close()
        return jsonify({'erro': 'Máquina não encontrada'}), 404

    c.execute("UPDATE maquinas SET status = 'QUEBRADA' WHERE id = ?", (maquina_id,))
    conn.commit()
    conn.close()

    registrar_auditoria('MAQUINA_QUEBRADA', 'MAQUINA', maquina_id, f'Máquina marcada como quebrada por {email}')

    socketio.emit('maquina_quebrada', {
        'id': maquina_id,
        'nome': maquina['nome'],
        'localizacao': maquina['localizacao'],
        'status': 'QUEBRADA'
    })

    enviar_alerta_maquina_telegram(
        f"🚨 MÁQUINA QUEBRADA 🚨\n\n"
        f"🔧 Máquina: {maquina['nome']}\n"
        f"📍 Local: {maquina['localizacao'] or '-'}\n"
        f"⏰ Hora: {datetime.now().strftime('%d/%m %H:%M')}\n"
        f"👤 Reportado por: {email}\n\n"
        f"👥 AVISO PARA:\n"
        f"- RH - Registrar paralisação\n"
        f"- PCP - Replanejar produção\n"
        f"- PCM - Manutenção urgente\n"
        f"- Almoxarifado - Preparar peças\n\n"
        f"⚙️ Aguardando conserto..."
    )

    return jsonify({'status': 'ok'}), 200

@app.route('/api/maquinas/<int:maquina_id>/consertada', methods=['POST'])
@jwt_required()
def marcar_maquina_consertada(maquina_id):
    """Marca máquina como consertada, salva o relatório e notifica"""
    email = get_jwt_identity()
    dados = request.json or {}
    relatorio = dados.get('relatorio', '')

    conn = get_db()
    c = conn.cursor()

    c.execute('SELECT * FROM maquinas WHERE id = ?', (maquina_id,))
    maquina = c.fetchone()
    if not maquina:
        conn.close()
        return jsonify({'erro': 'Máquina não encontrada'}), 404

    c.execute("UPDATE maquinas SET status = 'DISPONIVEL', ultimo_conserto = CURRENT_TIMESTAMP WHERE id = ?",
             (maquina_id,))
    c.execute('INSERT INTO relatorios_manutencao (maquina_id, usuario, descricao) VALUES (?, ?, ?)',
             (maquina_id, email, relatorio))
    conn.commit()
    conn.close()

    registrar_auditoria('MAQUINA_CONSERTADA', 'MAQUINA', maquina_id, f'Máquina consertada por {email}: {relatorio}')

    socketio.emit('maquina_consertada', {
        'id': maquina_id,
        'nome': maquina['nome'],
        'status': 'DISPONIVEL'
    })

    enviar_alerta_maquina_telegram(
        f"✅ MÁQUINA OPERACIONAL\n\n"
        f"🔧 Máquina: {maquina['nome']}\n"
        f"⏰ Consertada em: {datetime.now().strftime('%d/%m %H:%M')}\n"
        f"👤 Consertada por: {email}\n\n"
        f"📝 Relatório: {relatorio or '-'}\n\n"
        f"Produção pode continuar normalmente."
    )

    return jsonify({'status': 'ok'}), 200

@app.route('/api/chat/manutencao', methods=['GET'])
@jwt_required()
def get_chat_manutencao():
    """Histórico do chat entre operador/coordenador/gestor/diretor sobre manutenção"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM chat_manutencao ORDER BY criado_em ASC LIMIT 100')
    mensagens = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(mensagens)

@app.route('/api/chat/manutencao/enviar', methods=['POST'])
@jwt_required()
def enviar_chat_manutencao():
    """Envia uma mensagem no chat de manutenção e notifica via WebSocket"""
    email = get_jwt_identity()
    claims = get_jwt()
    role = claims.get('role', '')

    dados = request.json or {}
    mensagem = (dados.get('mensagem') or '').strip()
    if not mensagem:
        return jsonify({'erro': 'Mensagem vazia'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO chat_manutencao (usuario, role, mensagem) VALUES (?, ?, ?)',
             (email, role, mensagem))
    conn.commit()
    msg_id = c.lastrowid
    c.execute('SELECT * FROM chat_manutencao WHERE id = ?', (msg_id,))
    nova_msg = dict(c.fetchone())
    conn.close()

    registrar_auditoria('CHAT_MANUTENCAO', 'CHAT', msg_id, f'{email} ({role}): {mensagem}')

    socketio.emit('chat_msg', nova_msg)

    return jsonify(nova_msg), 201

@app.route('/api/metricas', methods=['GET'])
def get_metricas():
    """Retorna métricas do sistema, calculadas em tempo real a partir do banco"""
    conn = get_db()
    c = conn.cursor()

    c.execute('SELECT COUNT(*) as total FROM notas')
    total_notas = c.fetchone()['total']

    c.execute('SELECT COUNT(*) as total FROM ordens_servico WHERE status = "CONCLUIDA"')
    os_concluidas = c.fetchone()['total']

    c.execute('SELECT COUNT(*) as total FROM ordens_servico')
    os_total = c.fetchone()['total']

    conn.close()

    taxa_aderencia = round((os_concluidas / os_total) * 100, 1) if os_total else 0.0

    agora = datetime.now()
    economia = calcular_economia(MESES_PT[agora.month], agora.year)

    return jsonify({
        'total_notas': total_notas,
        'os_concluidas': os_concluidas,
        'taxa_aderencia': taxa_aderencia,
        'economia_mensal': economia['economia_mensal'],
        'tempo_economizado_horas': economia['tempo_economizado'],
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/auditoria', methods=['GET'])
def get_auditoria():
    """Lista eventos de auditoria"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT * FROM auditoria ORDER BY criado_em DESC LIMIT 100''')
    eventos = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(eventos)

# --- Diferencial #1: Integração com SAP ------------------------------------

@app.route('/api/sap/importar', methods=['POST'])
def importar_sap_arquivo():
    """Recebe um arquivo SAP (tab-separated) via multipart/form-data e processa"""
    if 'arquivo' not in request.files:
        return jsonify({'erro': 'Nenhum arquivo enviado (campo "arquivo" obrigatório)'}), 400

    arquivo = request.files['arquivo']
    if arquivo.filename == '':
        return jsonify({'erro': 'Nome do arquivo vazio'}), 400

    try:
        conteudo = arquivo.read().decode('utf-8')
    except UnicodeDecodeError:
        return jsonify({'erro': 'Arquivo precisa estar em UTF-8'}), 400

    resultado = IntegradorSAP.processar_conteudo(conteudo)
    return jsonify(resultado), 200

# --- Diferencial #2: Alertas por email --------------------------------------

@app.route('/api/alerta/email', methods=['POST'])
def enviar_alerta_email():
    """Envia um alerta real por email"""
    dados = request.json or {}

    erros = Validador.validar_alerta(dados)
    if erros:
        return jsonify({'erros': erros}), 400

    resultado = SistemaAlertas.enviar_email_alerta(
        dados['destinatario'], dados['assunto'], dados['corpo'], dados.get('tipo', 'info')
    )
    status_code = 200 if resultado['enviado'] else 502
    return jsonify(resultado), status_code

# --- Diferencial #3: Relatório em PDF ---------------------------------------

@app.route('/api/relatorio/economia', methods=['GET'])
def gerar_relatorio_economia():
    """Gera e retorna um PDF com a economia real gerada pela automação"""
    agora = datetime.now()
    mes = request.args.get('mes', MESES_PT[agora.month])
    try:
        ano = int(request.args.get('ano', agora.year))
    except ValueError:
        return jsonify({'erro': 'ano deve ser um número'}), 400

    dados = calcular_economia(mes, ano)
    pdf_bytes = GeradorRelatorio.gerar_relatorio_economia(mes, ano, dados)

    registrar_auditoria('RELATORIO', 'PDF', None, f'Relatório de economia gerado: {mes}/{ano}')

    return send_file(
        BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'Relatorio_Economia_{mes}_{ano}.pdf'
    )

# --- Diferencial #5: Autenticação JWT + papéis ------------------------------

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Autentica um usuário e devolve um JWT com o papel (role) dele"""
    dados = request.json or {}
    email = (dados.get('email') or '').strip().lower()
    senha = dados.get('senha') or ''

    if not email or not senha:
        return jsonify({'erro': 'Email e senha são obrigatórios'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM usuarios WHERE email = ?', (email,))
    usuario = c.fetchone()
    conn.close()

    if not usuario or not bcrypt.checkpw(senha.encode('utf-8'), usuario['senha_hash'].encode('utf-8')):
        return jsonify({'erro': 'Email ou senha inválidos'}), 401

    token = create_access_token(identity=email, additional_claims={'role': usuario['role']})
    registrar_auditoria('LOGIN', 'USUARIO', usuario['id'], f'Login realizado: {email}')

    return jsonify({'token': token, 'role': usuario['role'], 'usuario': email})

@app.route('/api/painel/operador', methods=['GET'])
@requer_roles('operador', 'coordenador', 'gestor', 'diretor')
def painel_operador():
    """Fila de produção visível para qualquer papel autenticado"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT os.numero, os.status, os.prioridade, os.tempo_total, n.peca_codigo
                FROM ordens_servico os
                JOIN notas n ON os.nota_id = n.id
                WHERE os.status IN ('PLANEJAMENTO', 'USINANDO')
                ORDER BY CASE WHEN os.prioridade = 'URGENTE' THEN 0 ELSE 1 END, os.criada_em ASC''')
    fila = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify({'usuario': get_jwt_identity(), 'fila_producao': fila})

@app.route('/api/painel/gestor', methods=['GET'])
@requer_roles('gestor', 'diretor')
def painel_gestor():
    """Painel de economia/gestão, restrito a gestor e diretor"""
    agora = datetime.now()
    dados = calcular_economia(MESES_PT[agora.month], agora.year)
    return jsonify({'usuario': get_jwt_identity(), 'economia': dados})

# --- Diferencial #6: Backup automático --------------------------------------

@app.route('/api/backup/criar', methods=['POST'])
def criar_backup_endpoint():
    """Dispara um backup manual do banco de dados"""
    try:
        caminho = criar_backup()
        return jsonify({'sucesso': True, 'arquivo': os.path.basename(caminho)}), 201
    except Exception as e:
        logger.error(f'Erro ao criar backup: {e}')
        return jsonify({'erro': str(e)}), 500

@app.route('/api/backup/listar', methods=['GET'])
def listar_backups():
    """Lista os backups existentes"""
    if not os.path.isdir(BACKUP_DIR):
        return jsonify([])

    arquivos = []
    for nome in sorted(os.listdir(BACKUP_DIR), reverse=True):
        caminho = os.path.join(BACKUP_DIR, nome)
        if os.path.isfile(caminho):
            arquivos.append({
                'arquivo': nome,
                'tamanho_kb': round(os.path.getsize(caminho) / 1024, 1),
                'criado_em': datetime.fromtimestamp(os.path.getmtime(caminho)).isoformat()
            })
    return jsonify(arquivos)

# --- Diferencial #7: Logs estruturados --------------------------------------

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Lê o arquivo de log estruturado (JSON por linha), filtrando por nível"""
    nivel = request.args.get('nivel', '').upper()
    try:
        limite = int(request.args.get('limite', 50))
    except ValueError:
        limite = 50

    caminho = os.path.join(LOG_DIR, 'app.log')
    if not os.path.isfile(caminho):
        return jsonify([])

    entradas = []
    with open(caminho, 'r', encoding='utf-8') as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                entrada = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if nivel and entrada.get('nivel') != nivel:
                continue
            entradas.append(entrada)

    return jsonify(entradas[-limite:])

# --- Diferencial #10: Estatísticas customizadas -----------------------------

@app.route('/api/estatisticas', methods=['GET'])
def get_estatisticas():
    """Estatísticas de desempenho por máquina, por solicitante e economia semanal"""
    conn = get_db()
    c = conn.cursor()

    c.execute('''SELECT m.nome as maquina, COUNT(am.id) as operacoes,
                        AVG((julianday(am.fim_planejado) - julianday(am.inicio_planejado)) * 24 * 60) as tempo_medio_min
                 FROM alocacao_maquinas am
                 JOIN maquinas m ON am.maquina_id = m.id
                 GROUP BY m.nome''')
    desempenho_maquinas = []
    for row in c.fetchall():
        item = dict(row)
        item['tempo_medio_min'] = round(item['tempo_medio_min'], 1) if item['tempo_medio_min'] else 0
        desempenho_maquinas.append(item)

    c.execute('''SELECT COALESCE(solicitante, 'NAO_INFORMADO') as operador,
                        COUNT(*) as total_notas,
                        SUM(CASE WHEN status != 'PROCESSADA' THEN 1 ELSE 0 END) as pendentes
                 FROM notas GROUP BY solicitante''')
    por_operador = [dict(row) for row in c.fetchall()]

    c.execute('''SELECT strftime('%W', criada_em) as semana, COUNT(*) as notas
                 FROM notas
                 WHERE status = 'PROCESSADA' AND strftime('%Y', criada_em) = strftime('%Y', 'now')
                 GROUP BY semana ORDER BY semana''')
    economia_semanal = []
    for row in c.fetchall():
        notas_semana = row['notas']
        valor = round(notas_semana * (TEMPO_MANUAL_MIN - TEMPO_AUTOMATICO_MIN) / 60 * CUSTO_HORA_PRODUCAO, 2)
        economia_semanal.append({
            'semana': row['semana'],
            'notas_processadas': notas_semana,
            'economia_estimada': valor
        })

    conn.close()

    return jsonify({
        'desempenho_por_maquina': desempenho_maquinas,
        'notas_por_operador': por_operador,
        'economia_semanal': economia_semanal,
        'gerado_em': datetime.now().isoformat()
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({'erro': 'Endpoint não encontrado'}), 404

# Roda sempre que o módulo é importado — tanto via `python app.py` (dev)
# quanto via um servidor WSGI real (gunicorn etc. importam `app:app` e NUNCA
# executam o bloco `if __name__ == '__main__':` abaixo, então a inicialização
# não pode depender dele, senão o banco fica sem tabelas em produção).
init_db()
seed_data()
seed_usuarios()
iniciar_agendador_backup()
logger.info('Sistema de Automação de Usinagem iniciado')

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
