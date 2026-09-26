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
import secrets
import logging
import threading
from io import BytesIO
from functools import lru_cache, wraps
from datetime import date, datetime, timedelta
from logging.handlers import RotatingFileHandler
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import bcrypt
import requests
import schedule
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_file, send_from_directory
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
# Tempo até uma máquina QUEBRADA voltar, contado a partir de agora ao planejar nela
FOLGA_MAQUINA_PARADA_MIN = int(os.getenv('FOLGA_MAQUINA_PARADA_MIN', '60'))
# Execução "fora do expediente": corridos - expediente >= este limite (minutos).
FORA_EXPEDIENTE_LIMIAR_MIN = int(os.getenv('FORA_EXPEDIENTE_LIMIAR_MIN', '60'))
# Operação EXECUTANDO cujo tempo de usinagem (expediente) passou de FATOR x o
# planejado é sinalizada como possivelmente esquecida em aberto.
OPERACAO_ESQUECIDA_FATOR = float(os.getenv('OPERACAO_ESQUECIDA_FATOR', '2'))
# Expediente da oficina, de segunda a sexta. O planejador só conta minutos
# dentro dele (ver somar_expediente).
EXPEDIENTE_INICIO_H = int(os.getenv('EXPEDIENTE_INICIO_H', '7'))
EXPEDIENTE_FIM_H = int(os.getenv('EXPEDIENTE_FIM_H', '17'))
if not 0 <= EXPEDIENTE_INICIO_H < EXPEDIENTE_FIM_H <= 24:
    raise ValueError(
        f'Expediente inválido: EXPEDIENTE_INICIO_H={EXPEDIENTE_INICIO_H}, '
        f'EXPEDIENTE_FIM_H={EXPEDIENTE_FIM_H} (precisa 0 <= início < fim <= 24)')
SENHA_PADRAO_DEMO = os.getenv('SENHA_PADRAO_DEMO', 'Vitor367')

# Diferencial #11 - Notificação de nota criada no Telegram (com desenho técnico)
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
FRONTEND_URL = os.getenv('FRONTEND_URL', 'https://frontend-xi-two-5l7d05gqtg.vercel.app')
DESENHOS_DIR = 'desenhos_tecnicos'

# Ficha técnica da peça (colunas opcionais de `pecas`) e o rótulo de cada uma.
FICHA_CAMPOS = ('material', 'dimensoes', 'tolerancia', 'aplicacao', 'observacoes_tecnicas')
FICHA_ROTULOS = {'material': 'Material', 'dimensoes': 'Dimensões', 'tolerancia': 'Tolerância',
                 'aplicacao': 'Aplicação', 'observacoes_tecnicas': 'Observações técnicas'}
CODIGO_PECA_REGEX = re.compile(r'^[A-Za-z0-9_-]+$')


def tem_desenho(codigo):
    """True se existe desenhos_tecnicos/<codigo>.pdf (e o código é seguro)."""
    return bool(codigo) and bool(CODIGO_PECA_REGEX.match(codigo)) and \
        os.path.isfile(os.path.join(DESENHOS_DIR, f'{codigo}.pdf'))


def desenho_provisorio(codigo):
    """True se o PDF da peça é só um placeholder (código listado em
    desenhos_tecnicos/PLACEHOLDERS.txt): existe arquivo, mas não é o desenho
    oficial. Sem o arquivo de marcadores, nenhum PDF é tratado como provisório."""
    try:
        with open(os.path.join(DESENHOS_DIR, 'PLACEHOLDERS.txt'), encoding='utf-8') as f:
            marcados = {l.strip() for l in f if l.strip() and not l.lstrip().startswith('#')}
    except OSError:
        return False
    return tem_desenho(codigo) and codigo in marcados


def ficha_da_peca(linha):
    """Ficha técnica de uma linha de `pecas`: só os campos preenchidos, mais
    quais faltam. Campo vazio não vira texto nenhum."""
    preenchidos = {c: linha[c].strip() for c in FICHA_CAMPOS
                   if c in linha.keys() and linha[c] and str(linha[c]).strip()}
    return {'ficha': preenchidos,
            'ficha_faltando': [c for c in FICHA_CAMPOS if c not in preenchidos]}

# Bot do Telegram (Etapa 1) - token de serviço bot->API, nunca o token do
# BotFather (esse é do bot_telegram.py). Sem isto configurado, /vincular e
# /token recusam qualquer chamada (ver _bot_autorizado).
BOT_SERVICE_TOKEN = os.getenv('BOT_SERVICE_TOKEN')
BOT_JWT_EXPIRES_MIN = int(os.getenv('BOT_JWT_EXPIRES_MIN', '15'))
VINCULO_CODIGO_EXPIRA_MIN = int(os.getenv('VINCULO_CODIGO_EXPIRA_MIN', '10'))
VINCULO_MAX_TENTATIVAS = int(os.getenv('VINCULO_MAX_TENTATIVAS', '5'))
VINCULO_BLOQUEIO_MIN = int(os.getenv('VINCULO_BLOQUEIO_MIN', '15'))

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

    # --- Fase 1: hora da quebra, para calcular MTTR de manutenção ------------
    c.execute("PRAGMA table_info(maquinas)")
    colunas_maquinas = {row[1] for row in c.fetchall()}
    if 'quebrada_em' not in colunas_maquinas:
        c.execute('ALTER TABLE maquinas ADD COLUMN quebrada_em TIMESTAMP')

    # --- Fase 1: execução real das operações ---------------------------------
    c.execute("PRAGMA table_info(alocacao_maquinas)")
    colunas_alocacao = {row[1] for row in c.fetchall()}
    for coluna, tipo_sql in [
        ('tempo_realizado_min', 'INTEGER'),   # medido: fim_real - inicio_real
        ('operador', 'TEXT'),                 # quem executou
        ('observacao', 'TEXT'),               # o que o operador registrou
        # duração planejada em minutos de trabalho. fim - início não serve mais:
        # uma operação que atravessa a noite tem fim - início > duração.
        ('tempo_planejado_min', 'INTEGER'),
        # Etapa 3A: máquina que quebra interrompe a operação em execução.
        # tempo_acumulado_min = minutos de usinagem já feitos antes de uma
        # interrupção; retomada_em = quando a execução ATUAL começou (inicio_real
        # continua sendo a primeira vez que a operação começou).
        ('tempo_acumulado_min', 'INTEGER'),
        ('retomada_em', 'TIMESTAMP'),
        # Unidade do tempo: tempo_realizado_min e tempo_acumulado_min são em
        # minutos de EXPEDIENTE (mesma régua do planejado); as colunas
        # *_corrido_min guardam os minutos corridos, para auditoria.
        ('tempo_realizado_corrido_min', 'INTEGER'),
        ('tempo_acumulado_corrido_min', 'INTEGER'),
    ]:
        if coluna not in colunas_alocacao:
            c.execute(f'ALTER TABLE alocacao_maquinas ADD COLUMN {coluna} {tipo_sql}')

    # Uma linha por interrupção (uma operação pode ser interrompida mais de
    # uma vez). fim NULL = máquina ainda parada.
    c.execute('''CREATE TABLE IF NOT EXISTS paradas_operacao (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alocacao_id INTEGER NOT NULL,
        maquina_id INTEGER NOT NULL,
        inicio TIMESTAMP NOT NULL,
        fim TIMESTAMP,
        relatorio_manutencao_id INTEGER,
        criado_em TIMESTAMP DEFAULT (datetime('now','localtime')),
        FOREIGN KEY(alocacao_id) REFERENCES alocacao_maquinas(id),
        FOREIGN KEY(maquina_id) REFERENCES maquinas(id)
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_paradas_alocacao ON paradas_operacao(alocacao_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_paradas_maquina ON paradas_operacao(maquina_id)')

    # --- Fase 1: duração de cada intervenção de manutenção -------------------
    c.execute("PRAGMA table_info(relatorios_manutencao)")
    colunas_relatorio = {row[1] for row in c.fetchall()}
    for coluna, tipo_sql in [
        ('quebrada_em', 'TIMESTAMP'),
        ('tempo_reparo_min', 'INTEGER'),
    ]:
        if coluna not in colunas_relatorio:
            c.execute(f'ALTER TABLE relatorios_manutencao ADD COLUMN {coluna} {tipo_sql}')

    # --- Ficha técnica da peça: todos opcionais, preenchidos por quem tem o
    # desenho em mãos (CSV do importar_pecas.py). O sistema não gera medidas.
    c.execute("PRAGMA table_info(pecas)")
    colunas_pecas = {row[1] for row in c.fetchall()}
    for coluna in FICHA_CAMPOS:
        if coluna not in colunas_pecas:
            c.execute(f'ALTER TABLE pecas ADD COLUMN {coluna} TEXT')

    # --- Origem do dado: 'REAL' (medido no chão de fábrica) ou 'DEMONSTRACAO'
    # (gerado por seed_demo.py). Fica em notas e em relatorios_manutencao, as
    # duas tabelas que nascem do registro humano. OS e alocações herdam a
    # origem pela nota. Linhas anteriores a esta coluna leem 'REAL'.
    for tabela in ('notas', 'relatorios_manutencao'):
        c.execute(f"PRAGMA table_info({tabela})")
        if 'origem' not in {row[1] for row in c.fetchall()}:
            c.execute(f"ALTER TABLE {tabela} ADD COLUMN origem TEXT DEFAULT 'REAL'")

    # --- Canal de onde a ação partiu: 'WEB' (todas até aqui) ou 'TELEGRAM'
    # (a partir do bot, Etapa 1). registrar_auditoria() grava isso.
    c.execute("PRAGMA table_info(auditoria)")
    if 'canal' not in {row[1] for row in c.fetchall()}:
        c.execute("ALTER TABLE auditoria ADD COLUMN canal TEXT DEFAULT 'WEB'")

    # Tabela de CHAT DE MANUTENÇÃO (Feature 4)
    c.execute('''CREATE TABLE IF NOT EXISTS chat_manutencao (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT NOT NULL,
        role TEXT,
        mensagem TEXT NOT NULL,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # --- Bot do Telegram, Etapa 1: vínculo de conta ---------------------------
    c.execute("PRAGMA table_info(usuarios)")
    if 'telegram_id' not in {row[1] for row in c.fetchall()}:
        c.execute('ALTER TABLE usuarios ADD COLUMN telegram_id INTEGER')
    # Índice único à parte: SQLite não deixa declarar UNIQUE num ADD COLUMN.
    # NULL não conflita com NULL, então usuários ainda não vinculados convivem.
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_telegram_id ON usuarios(telegram_id)')

    # Código de 6 dígitos gerado no site e trocado pelo vínculo no bot. Um por
    # usuário: gerar de novo apaga o anterior (ver gerar_codigo_telegram).
    c.execute('''CREATE TABLE IF NOT EXISTS vinculos_pendentes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        codigo TEXT NOT NULL,
        criado_em TIMESTAMP DEFAULT (datetime('now','localtime')),
        expira_em TIMESTAMP NOT NULL,
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_vinculos_codigo ON vinculos_pendentes(codigo)')

    # Tentativas erradas de /vincular, por telegram_id (não por código: um
    # palpite errado não bate em nenhuma linha de vinculos_pendentes, então
    # não dá pra contar tentativa ali). Bloqueia esse telegram_id por um
    # tempo depois de VINCULO_MAX_TENTATIVAS erros seguidos.
    c.execute('''CREATE TABLE IF NOT EXISTS tentativas_vinculo_telegram (
        telegram_id INTEGER PRIMARY KEY,
        tentativas INTEGER DEFAULT 0,
        bloqueado_ate TIMESTAMP
    )''')

    # Migração: LIBERADO passou a significar "pode começar", e a 1ª operação
    # nasce assim (ver processar_nota). Operações de sequência 1 já gravadas
    # como PLANEJADO, em OS ainda não iniciadas, passam a LIBERADO. Idempotente.
    c.execute('''UPDATE alocacao_maquinas SET status = 'LIBERADO'
                 WHERE sequencia = 1 AND status = 'PLANEJADO' AND inicio_real IS NULL
                   AND ordem_servico_id IN (SELECT id FROM ordens_servico WHERE status = 'PLANEJAMENTO')''')

    conn.commit()
    _migrar_realizado_para_expediente(conn)
    logger.info("Banco de dados inicializado")
    conn.close()

def registrar_auditoria(tipo, entidade, entidade_id, descricao, usuario='SISTEMA', canal=None):
    """Registra evento na auditoria.

    `usuario` é o e-mail de quem agiu (get_jwt_identity() no chamador); fica
    'SISTEMA' para o que não tem requisição autenticada por trás (SAP,
    backup agendado, notas criadas sem login).

    `canal`, quando não informado explicitamente, vem do claim 'canal' do
    JWT da requisição atual: 'WEB' nos tokens do site (não têm esse claim,
    então cai no padrão), 'TELEGRAM' nos tokens emitidos por
    /api/telegram/token. As rotas que o bot chama (iniciar/concluir
    operação, quebra, conserto, chat) são as MESMAS do site e não sabem
    nada disso — é essa leitura implícita que faz o canal aparecer certo
    sem tocar em nenhuma delas.
    """
    if canal is None:
        canal = 'WEB'
        try:
            canal = get_jwt().get('canal', 'WEB')
        except Exception:
            pass  # rota pública ou fora de contexto de requisição (ex.: backup agendado)

    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO auditoria
                 (tipo_evento, entidade, entidade_id, descricao, usuario, canal, criado_em)
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (tipo, entidade, entidade_id, descricao, usuario, canal, datetime.now().isoformat()))
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

        # Roteiros de exemplo (sequência, máquina, tempo estimado, descrição).
        # Só semeia a peça que AINDA NÃO TEM roteiro: quem já tem, inclusive
        # por importação de catálogo (importar_pecas.py), não é sobrescrito a
        # cada partida do app.
        roteiros = {
            '40-091799': [(1, 'Torno Horizontal', 120, 'Usinagem cilíndrica'),
                          (2, 'Torno Vertical', 90, 'Acabamento superficial')],
            '40-122633': [(1, 'Fresadora Universal', 150, 'Usinagem em fresadora')],
            '40-154120': [(1, 'Retificadora Cilíndrica', 200, 'Polimento fino')],
        }
        for codigo, ops in roteiros.items():
            peca_id = c.execute('SELECT id FROM pecas WHERE codigo = ?', (codigo,)).fetchone()[0]
            if c.execute('SELECT COUNT(*) FROM operacoes WHERE peca_id = ?', (peca_id,)).fetchone()[0]:
                continue
            for seq, maq, tempo, desc in ops:
                c.execute('''INSERT INTO operacoes
                            (peca_id, sequencia, maquina, tempo_estimado, descricao)
                            VALUES (?, ?, ?, ?, ?)''', (peca_id, seq, maq, tempo, desc))

        # Bancos de antes da troca do parque de máquinas (abaixo) ainda têm os
        # nomes antigos nos roteiros; processar_nota acha a máquina pelo nome.
        for antigo, novo in (('CENTUR', 'Torno Horizontal'), ('D1250', 'Torno Vertical'),
                             ('FRESADORA', 'Fresadora Universal'),
                             ('POLITRIZ', 'Retificadora Cilíndrica')):
            c.execute('UPDATE operacoes SET maquina = ? WHERE maquina = ?', (novo, antigo))

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

ORIGENS_VALIDAS = ('REAL', 'DEMONSTRACAO', 'TODAS')


def _origem_da_requisicao():
    """Lê ?origem=REAL|DEMONSTRACAO|TODAS (padrão TODAS).

    Devolve (origem, None) ou (None, resposta_400) para o endpoint repassar.
    """
    origem = (request.args.get('origem') or 'TODAS').strip().upper()
    if origem not in ORIGENS_VALIDAS:
        return None, (jsonify({'erro': 'origem inválida. Use REAL, DEMONSTRACAO ou TODAS'}), 400)
    return origem, None


def _sql_origem(origem, coluna):
    """Fragmento SQL e parâmetros que filtram `coluna` pela origem.

    'DEMONSTRACAO' é a marca explícita; REAL é todo o resto (inclusive NULL,
    de linhas anteriores à coluna).
    """
    if origem == 'DEMONSTRACAO':
        return f"COALESCE({coluna}, 'REAL') = 'DEMONSTRACAO'", ()
    if origem == 'REAL':
        return f"COALESCE({coluna}, 'REAL') != 'DEMONSTRACAO'", ()
    return '1 = 1', ()


def _contar_origens(cursor, tabela, origem):
    """{'real': N, 'demonstracao': M}: registros de `tabela` que passam no
    filtro, ou seja, os que de fato entram no cálculo."""
    if tabela not in ('notas', 'relatorios_manutencao'):
        raise ValueError(f'tabela sem coluna origem: {tabela}')
    filtro, params = _sql_origem(origem, 'origem')
    cursor.execute(f'''SELECT COALESCE(origem, 'REAL') = 'DEMONSTRACAO' AS demo, COUNT(*) AS n
                       FROM {tabela} WHERE {filtro} GROUP BY demo''', params)
    contagem = {bool(r['demo']): r['n'] for r in cursor.fetchall()}
    return {'real': contagem.get(False, 0), 'demonstracao': contagem.get(True, 0)}


def _origem_das_notas(alocacoes):
    """Mesmo bloco de _contar_origens, para linhas já em memória (dicts com
    nota_id e nota_origem): conta notas distintas, não operações."""
    notas = {a['nota_id']: (a['nota_origem'] or 'REAL') == 'DEMONSTRACAO' for a in alocacoes}
    demo = sum(notas.values())
    return {'real': len(notas) - demo, 'demonstracao': demo}


def calcular_economia(mes_nome, ano, origem='TODAS'):
    """Calcula a economia real gerada pela automação, a partir do banco"""
    numero_mes = MESES_PT_INV.get((mes_nome or '').lower())
    filtro, params_origem = _sql_origem(origem, 'origem')

    conn = get_db()
    c = conn.cursor()

    if numero_mes:
        c.execute(f'''SELECT COUNT(*) as total FROM notas
                     WHERE status='PROCESSADA' AND strftime('%Y', criada_em) = ?
                       AND strftime('%m', criada_em) = ? AND {filtro}''',
                 (str(ano), f'{numero_mes:02d}') + params_origem)
    else:
        c.execute(f'''SELECT COUNT(*) as total FROM notas
                     WHERE status='PROCESSADA' AND strftime('%Y', criada_em) = ?
                       AND {filtro}''',
                 (str(ano),) + params_origem)
    notas_mes = c.fetchone()['total']

    c.execute(f'''SELECT COUNT(*) as total FROM notas
                 WHERE status='PROCESSADA' AND strftime('%Y', criada_em) = ?
                   AND {filtro}''', (str(ano),) + params_origem)
    notas_ano = c.fetchone()['total']

    # Erros evitados vêm da auditoria, que não guarda origem: o gerador de
    # demonstração nunca escreve nela, então todo evento ali é real.
    if origem == 'DEMONSTRACAO':
        erros_evitados = 0
    elif numero_mes:
        c.execute('''SELECT COUNT(*) as total FROM auditoria
                     WHERE tipo_evento='VALIDACAO_ERRO' AND strftime('%Y', criado_em) = ?
                       AND strftime('%m', criado_em) = ?''',
                 (str(ano), f'{numero_mes:02d}'))
        erros_evitados = c.fetchone()['total']
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

# Feriados nacionais de data fixa, como (mês, dia).
FERIADOS_FIXOS = ((1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (12, 25))
# Dia da Consciência Negra: feriado nacional a partir de 2024 (Lei 14.759/2023).
# Antes disso era só estadual/municipal, então não entra nos anos anteriores.
CONSCIENCIA_NEGRA = (11, 20)
CONSCIENCIA_NEGRA_DESDE = 2024


def _pascoa(ano):
    """Domingo de Páscoa no calendário gregoriano (Meeus/Jones/Butcher)."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


@lru_cache(maxsize=None)
def feriados_do_ano(ano):
    """Feriados nacionais do ano: os de data fixa e os que dependem da Páscoa.

    Fixos: os de FERIADOS_FIXOS mais o Dia da Consciência Negra (20/11) a
    partir de 2024. Móveis: Carnaval (segunda e terça, 48 e 47 dias antes), Sexta-feira Santa
    (2 dias antes) e Corpus Christi (60 dias depois). Não há feriados
    estaduais nem municipais.
    """
    pascoa = _pascoa(ano)
    moveis = [pascoa + timedelta(days=n) for n in (-48, -47, -2, 60)]
    fixos = list(FERIADOS_FIXOS)
    if ano >= CONSCIENCIA_NEGRA_DESDE:
        fixos.append(CONSCIENCIA_NEGRA)
    return frozenset(date(ano, mes, dia) for mes, dia in fixos) | frozenset(moveis)


def eh_feriado(d):
    """`d` pode ser date ou datetime."""
    d = d.date() if isinstance(d, datetime) else d
    return d in feriados_do_ano(d.year)


def eh_dia_util(d):
    """Segunda a sexta, exceto feriados nacionais (ver feriados_do_ano)."""
    return d.weekday() < 5 and not eh_feriado(d)


def abertura_do_dia(d):
    return datetime(d.year, d.month, d.day) + timedelta(hours=EXPEDIENTE_INICIO_H)


def fechamento_do_dia(d):
    return datetime(d.year, d.month, d.day) + timedelta(hours=EXPEDIENTE_FIM_H)


def proxima_abertura(d):
    """Abertura do primeiro dia útil DEPOIS do dia `d` (um date)."""
    d += timedelta(days=1)
    while not eh_dia_util(d):
        d += timedelta(days=1)
    return abertura_do_dia(d)


def alinhar_ao_expediente(t):
    """Primeiro instante >= t que cai dentro do expediente.

    Fora do horário, em fim de semana ou em feriado, empurra para a próxima
    abertura.
    O fechamento em si já é "fora": 17:00 vira 07:00 do dia útil seguinte.
    """
    d = t.date()
    if not eh_dia_util(d):
        return proxima_abertura(d)
    if t < abertura_do_dia(d):
        return abertura_do_dia(d)
    if t >= fechamento_do_dia(d):
        return proxima_abertura(d)
    return t


def somar_expediente(inicio, minutos):
    """Instante em que termina uma tarefa de `minutos` que começa em `inicio`,
    consumindo SÓ minutos de expediente.

    120 min começando às 16h (fecha às 17h) terminam às 8h do dia útil
    seguinte: 60 hoje, 60 amanhã. Se `inicio` cai fora do expediente, a
    contagem começa na próxima abertura. Terminar exatamente no fechamento
    termina naquele dia, não na manhã seguinte.
    """
    t = alinhar_ao_expediente(inicio)
    restante = timedelta(minutes=minutos)
    while True:
        disponivel = fechamento_do_dia(t.date()) - t
        if restante <= disponivel:
            return t + restante
        restante -= disponivel
        t = proxima_abertura(t.date())


def _agora():
    """Relógio do sistema. Existe para os testes poderem fixar a hora: as
    contas de expediente (Etapa 3A) dependem de que hora é agora."""
    return datetime.now()


def minutos_de_expediente(inicio, fim):
    """Minutos de EXPEDIENTE entre `inicio` e `fim` (datetimes).

    Só conta o que cai entre a abertura e o fechamento de dias úteis
    (eh_dia_util / abertura_do_dia / fechamento_do_dia): uma máquina parada de
    madrugada, no fim de semana ou num feriado não representa produção
    perdida. É o inverso de somar_expediente. 0 se fim <= inicio.
    """
    if fim <= inicio:
        return 0
    total = timedelta(0)
    dia = inicio.date()
    while dia <= fim.date():
        if eh_dia_util(dia):
            ini = max(inicio, abertura_do_dia(dia))
            fi = min(fim, fechamento_do_dia(dia))
            if fi > ini:
                total += fi - ini
        dia += timedelta(days=1)
    return int(total.total_seconds() / 60)


def _minutos_desde(inicio_str, agora):
    """Minutos corridos (inteiros) de um timestamp do banco até `agora`; 0 se ilegível."""
    ini = _parse_ts(inicio_str)
    return max(int((agora - ini).total_seconds() / 60), 0) if ini else 0


def _minutos_expediente_desde(inicio_str, agora):
    """Minutos de EXPEDIENTE de um timestamp do banco até `agora`; 0 se ilegível."""
    ini = _parse_ts(inicio_str)
    return minutos_de_expediente(ini, agora) if ini else 0


def _trecho(inicio_str, agora):
    """(expediente, corrido) do trecho de execução que começou em `inicio_str`.

    O realizado e o acumulado ficam em minutos de EXPEDIENTE, a mesma régua do
    planejado e da produção perdida; os minutos corridos são guardados à parte
    (auditoria e sinalização de execução fora do expediente)."""
    return _minutos_expediente_desde(inicio_str, agora), _minutos_desde(inicio_str, agora)


def fora_do_expediente(corrido, expediente):
    """True quando uma parte relevante da execução caiu fora do expediente
    (hora extra, fim de semana ou operação deixada aberta): corridos maiores
    que os de expediente por pelo menos FORA_EXPEDIENTE_LIMIAR_MIN minutos."""
    return corrido is not None and expediente is not None and corrido - expediente >= FORA_EXPEDIENTE_LIMIAR_MIN


def _interromper_operacoes(c, maquina_id, agora):
    """A máquina quebrou: toda operação EXECUTANDO nela vira INTERROMPIDA.

    Soma em tempo_acumulado_min os minutos de EXPEDIENTE da execução atual
    (desde retomada_em, ou inicio_real na primeira execução) e em
    tempo_acumulado_corrido_min os corridos, e abre uma linha em
    paradas_operacao. inicio_real não muda. Devolve as operações afetadas.
    """
    afetadas = c.execute('''SELECT am.id, am.sequencia, am.inicio_real, am.retomada_em,
                                   am.tempo_acumulado_min, am.tempo_acumulado_corrido_min,
                                   os.numero AS os_numero, os.id AS os_id
                            FROM alocacao_maquinas am
                            JOIN ordens_servico os ON os.id = am.ordem_servico_id
                            WHERE am.maquina_id = ? AND am.status = 'EXECUTANDO' ''',
                         (maquina_id,)).fetchall()
    resultado = []
    for a in afetadas:
        expediente, corrido = _trecho(a['retomada_em'] or a['inicio_real'], agora)
        acumulado = (a['tempo_acumulado_min'] or 0) + expediente
        acumulado_corrido = (a['tempo_acumulado_corrido_min'] or 0) + corrido
        c.execute('''UPDATE alocacao_maquinas
                     SET status = 'INTERROMPIDA', tempo_acumulado_min = ?,
                         tempo_acumulado_corrido_min = ?, retomada_em = NULL
                     WHERE id = ?''', (acumulado, acumulado_corrido, a['id']))
        c.execute('''INSERT INTO paradas_operacao (alocacao_id, maquina_id, inicio)
                     VALUES (?, ?, ?)''', (a['id'], maquina_id, agora.isoformat()))
        resultado.append({'alocacao_id': a['id'], 'os_id': a['os_id'], 'os_numero': a['os_numero'],
                          'sequencia': a['sequencia'], 'tempo_acumulado_min': acumulado})
    return resultado


def _liberar_operacoes_interrompidas(c, maquina_id, agora, relatorio_id=None):
    """A máquina foi consertada: as operações INTERROMPIDAS voltam a LIBERADO
    (o operador decide quando retomar) e as paradas abertas dela são fechadas."""
    liberadas = c.execute('''SELECT am.id, am.sequencia, os.numero AS os_numero, os.id AS os_id
                             FROM alocacao_maquinas am
                             JOIN ordens_servico os ON os.id = am.ordem_servico_id
                             WHERE am.maquina_id = ? AND am.status = 'INTERROMPIDA' ''',
                          (maquina_id,)).fetchall()
    c.execute('''UPDATE alocacao_maquinas SET status = 'LIBERADO'
                 WHERE maquina_id = ? AND status = 'INTERROMPIDA' ''', (maquina_id,))
    c.execute('''UPDATE paradas_operacao SET fim = ?, relatorio_manutencao_id = ?
                 WHERE maquina_id = ? AND fim IS NULL''', (agora.isoformat(), relatorio_id, maquina_id))
    return [{'alocacao_id': a['id'], 'os_id': a['os_id'], 'os_numero': a['os_numero'],
             'sequencia': a['sequencia']} for a in liberadas]


def _migrar_realizado_para_expediente(conn):
    """Unidade do tempo realizado: de minutos corridos para minutos de EXPEDIENTE.

    Antes desta migração tempo_realizado_min era fim_real - inicio_real em
    minutos corridos; o planejado sempre foi em expediente. Para cada
    operação concluída ainda sem tempo_realizado_corrido_min:
      - o valor gravado vira o corrido (auditoria);
      - se há inicio_real e fim_real e o cálculo em expediente difere do
        corrido, tempo_realizado_min é recalculado em expediente. Se nada
        difere (operação inteira dentro do expediente), o valor não muda.
    Idempotente (só toca linhas sem a coluna dos corridos). Antes de mudar
    qualquer valor, faz um backup do banco. Devolve quantas linhas recalculou.
    """
    c = conn.cursor()
    linhas = c.execute('''SELECT am.id, am.inicio_real, am.fim_real, am.tempo_realizado_min,
                                 (SELECT COUNT(*) FROM paradas_operacao p WHERE p.alocacao_id = am.id) AS n_paradas
                          FROM alocacao_maquinas am
                          WHERE am.status = 'CONCLUIDO' AND am.tempo_realizado_min IS NOT NULL
                            AND am.tempo_realizado_corrido_min IS NULL''').fetchall()
    recalcular = []
    for r in linhas:
        ini, fim = _parse_ts(r['inicio_real']), _parse_ts(r['fim_real'])
        if ini and fim and fim > ini and not r['n_paradas']:
            expediente = minutos_de_expediente(ini, fim)
            if expediente != int((fim - ini).total_seconds() / 60):
                recalcular.append((r['id'], expediente))
    acumulados = c.execute('''SELECT id FROM alocacao_maquinas
                              WHERE tempo_acumulado_min IS NOT NULL AND tempo_acumulado_corrido_min IS NULL''').fetchall()
    if not linhas and not acumulados:
        return 0
    if recalcular:
        try:
            criar_backup()
        except Exception as e:      # sem backup não se recalcula
            logger.error(f'Migração do tempo realizado adiada: backup falhou ({e})')
            return 0
    for r in linhas:
        c.execute('UPDATE alocacao_maquinas SET tempo_realizado_corrido_min = tempo_realizado_min WHERE id = ?', (r['id'],))
    for alocacao_id, expediente in recalcular:
        c.execute('UPDATE alocacao_maquinas SET tempo_realizado_min = ? WHERE id = ?', (expediente, alocacao_id))
    # acumulado de operação ainda interrompida, gravado antes da coluna dos corridos
    for r in acumulados:
        c.execute('UPDATE alocacao_maquinas SET tempo_acumulado_corrido_min = tempo_acumulado_min WHERE id = ?', (r['id'],))
    conn.commit()
    if recalcular:
        logger.info(f'Tempo realizado recalculado em minutos de expediente: {len(recalcular)} operação(ões) '
                    f"({', '.join(str(a) for a, _ in recalcular)})")
    return len(recalcular)


def _fim_da_fila(cursor, maquina_id, agora):
    """Quando a máquina fica livre, pelo que já está planejado nela.

    É o maior fim_planejado FUTURO entre as operações dela que ainda não foram
    concluídas; se não há nenhuma, a máquina está livre na abertura do
    expediente mais próxima de `agora` (agora mesmo, se estiver aberto).
    Operação CONCLUIDO não ocupa mais a máquina, mesmo que o fim planejado
    seja futuro. Os fim_planejado gravados já são de expediente. Os timestamps
    são lidos em Python (_parse_ts) para não depender da comparação de texto
    entre formatos diferentes.
    """
    cursor.execute('''SELECT fim_planejado FROM alocacao_maquinas
                      WHERE maquina_id = ? AND status != 'CONCLUIDO' ''', (maquina_id,))
    fins = [f for f in (_parse_ts(r[0]) for r in cursor.fetchall()) if f and f > agora]
    return max(fins) if fins else alinhar_ao_expediente(agora)


def _proximo_numero(cursor, tabela, prefixo):
    """Próximo número sequencial do ano no formato PREFIXO-AAAA-NNNN.

    Só olha números já no formato novo do ano corrente (os antigos, como
    OS-20260919124204794201, não casam com o padrão e não são tocados).
    CHAMAR DENTRO DE UMA TRANSAÇÃO COM LOCK DE ESCRITA (BEGIN IMMEDIATE), e
    gravar o número na mesma transação: é isso que impede dois pedidos
    simultâneos de calcularem o mesmo. A restrição UNIQUE de `numero` é a
    segunda barreira.
    """
    if tabela not in ('ordens_servico', 'notas'):
        raise ValueError(f'tabela inválida para numeração: {tabela}')
    base = f'{prefixo}-{datetime.now().year}-'
    cursor.execute(
        f'SELECT MAX(CAST(SUBSTR(numero, ?) AS INTEGER)) FROM {tabela} WHERE numero LIKE ?',
        (len(base) + 1, base + '%'))
    ultimo = cursor.fetchone()[0] or 0
    return f'{base}{ultimo + 1:04d}'


class AutomacaoUsinagem:
    """Lógica principal de automação"""

    @staticmethod
    def processar_nota(nota_id):
        """Processa uma nota de manutenção automaticamente"""
        conn = get_db()
        c = conn.cursor()

        try:
            # Lock de escrita já no início: ler a fila das máquinas e gravar as
            # alocações precisa ser uma etapa só, senão dois pedidos simultâneos
            # leem a mesma fila e planejam sobrepostos.
            c.execute('BEGIN IMMEDIATE')

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

            numero_os = _proximo_numero(c, 'ordens_servico', 'OS')
            prioridade = 'URGENTE' if nota['prioridade'] == 'URGENTE' else 'NORMAL'

            c.execute('''INSERT INTO ordens_servico
                        (numero, nota_id, status, prioridade, tempo_total, criada_em)
                        VALUES (?, ?, ?, ?, ?, ?)''',
                     (numero_os, nota_id, 'PLANEJAMENTO', prioridade, tempo_total,
                      datetime.now().isoformat()))

            os_id = c.lastrowid

            agora = datetime.now()
            fim_operacao_anterior = agora
            alocacoes_em_maquina_parada = []
            for op in operacoes:
                c.execute('SELECT id, status FROM maquinas WHERE nome = ?', (op['maquina'],))
                maquina = c.fetchone()

                # Começa depois da fila da máquina e nunca antes do fim da
                # operação anterior da mesma OS. A duração continua sendo a de
                # operacoes.tempo_estimado, mas contada só em minutos de
                # expediente: a operação que não cabe no dia continua no
                # seguinte.
                fim_fila = _fim_da_fila(c, maquina['id'], agora)

                # Máquina parada: o roteiro da peça define a máquina, então não
                # se troca de máquina. A folga é o tempo até ela voltar, um
                # evento único contado a partir de AGORA (não se soma à fila
                # a cada OS): a máquina só fica disponível depois da folga, e
                # dali em diante a fila corre normal. A folga também conta em
                # minutos de expediente, como todo o resto do planejamento. O
                # fato fica na auditoria (gravada depois do commit).
                disponivel_em = agora
                if maquina['status'] == 'QUEBRADA':
                    disponivel_em = somar_expediente(agora, FOLGA_MAQUINA_PARADA_MIN)

                tempo_inicio = alinhar_ao_expediente(
                    max(fim_operacao_anterior, fim_fila, disponivel_em))
                tempo_fim = somar_expediente(tempo_inicio, op['tempo_estimado'])

                if maquina['status'] == 'QUEBRADA':
                    alocacoes_em_maquina_parada.append(
                        (op['sequencia'], op['maquina'], tempo_inicio))

                c.execute('''INSERT INTO alocacao_maquinas
                            (ordem_servico_id, maquina_id, sequencia, status,
                             inicio_planejado, fim_planejado, tempo_planejado_min)
                            VALUES (?, ?, ?, ?, ?, ?, ?)''',
                         (os_id, maquina[0], op['sequencia'],
                          # LIBERADO = "pode começar": só a 1ª operação nasce assim;
                          # as demais são liberadas quando a anterior é concluída.
                          'LIBERADO' if op['sequencia'] == 1 else 'PLANEJADO',
                          tempo_inicio.isoformat(), tempo_fim.isoformat(),
                          op['tempo_estimado']))

                fim_operacao_anterior = tempo_fim

            c.execute('''UPDATE notas SET status = ?, validada_em = ?
                        WHERE id = ?''',
                     ('PROCESSADA', datetime.now().isoformat(), nota_id))

            conn.commit()

            registrar_auditoria('PROCESSAMENTO', 'NOTA', nota_id,
                              f'Nota processada automaticamente. OS: {numero_os}')

            for sequencia, nome_maquina, inicio_deslocado in alocacoes_em_maquina_parada:
                registrar_auditoria(
                    'ALOCACAO_EM_MAQUINA_PARADA', 'ORDEM_SERVICO', os_id,
                    f'{numero_os}: operação {sequencia} planejada na máquina '
                    f'{nome_maquina}, que está QUEBRADA; início deslocado para '
                    f'{inicio_deslocado.strftime("%d/%m %H:%M")}'
                )

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
                                (numero, peca_codigo, quantidade, prioridade, solicitante, status, criada_em)
                                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                             (numero_nota, material, quantidade,
                              'URGENTE' if urgente else 'NORMAL',
                              'SAP_IMPORT', 'RECEBIDA', datetime.now().isoformat()))
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
        c.execute('''SELECT am.id, am.sequencia, am.status, am.inicio_planejado, am.fim_planejado,
                            am.inicio_real, am.fim_real, am.tempo_realizado_min,
                            am.tempo_acumulado_min, am.retomada_em, am.tempo_planejado_min,
                            am.tempo_realizado_corrido_min, am.tempo_acumulado_corrido_min,
                            m.nome as maquina_nome
                     FROM alocacao_maquinas am
                     JOIN maquinas m ON m.id = am.maquina_id
                     WHERE am.ordem_servico_id = ?
                     ORDER BY am.sequencia''', (ordem['id'],))
        agora = _agora()
        for row in c.fetchall():
            aloc = dict(row)
            aloc['paradas'] = _paradas_da_alocacao(c, aloc['id'], agora)
            aloc.update(_tempos_da_operacao(aloc, aloc['paradas'], agora, _planejado_da_operacao(aloc)))
            alocacoes.append(aloc)

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
            'descricao': peca['descricao'] if peca else None,
            **(ficha_da_peca(peca) if peca else {'ficha': {}, 'ficha_faltando': list(FICHA_CAMPOS)}),
            'tem_desenho': tem_desenho(nota['peca_codigo']),
            'desenho_provisorio': desenho_provisorio(nota['peca_codigo']),
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
        # Lock de escrita antes de calcular o número: o cálculo e o INSERT
        # viram uma etapa só, e dois pedidos simultâneos não pegam o mesmo.
        c.execute('BEGIN IMMEDIATE')
        numero = _proximo_numero(c, 'notas', 'NT')

        c.execute('''INSERT INTO notas
                    (numero, peca_codigo, quantidade, prioridade, solicitante, status, criada_em)
                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                 (numero, data.get('peca_codigo'), data.get('quantidade', 1),
                  data.get('prioridade', 'NORMAL'), data.get('solicitante'),
                  'RECEBIDA', datetime.now().isoformat()))

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

# Busca de OS: colunas de ordenação aceitas (nome do parâmetro -> expressão SQL).
ORDENACOES_OS = {
    'numero': 'os.numero', 'nota': 'n.numero', 'peca': 'p.nome COLLATE NOCASE',
    'status': 'os.status', 'prioridade': 'os.prioridade', 'criada_em': 'os.criada_em',
    'concluida_em': 'os.concluida_em', 'maquina_atual': 'maquina_atual COLLATE NOCASE',
    'planejado_min': 'planejado_min', 'realizado_min': 'realizado_min', 'atraso_min': 'atraso_min',
}
STATUS_OS = ('PLANEJAMENTO', 'USINANDO', 'CONCLUIDA')
POR_PAGINA_PADRAO, POR_PAGINA_MAX = 20, 100


def _data_param(nome, fim_do_dia=False):
    """?nome=YYYY-MM-DD -> (limite_iso, None); com fim_do_dia, o limite é o
    início do dia SEGUINTE (uso: coluna < limite). (None, None) se ausente."""
    valor = (request.args.get(nome) or '').strip()
    if not valor:
        return None, None
    try:
        dia = datetime.strptime(valor, '%Y-%m-%d')
    except ValueError:
        return None, f'{nome} inválida. Use YYYY-MM-DD'
    if fim_do_dia:
        dia += timedelta(days=1)
    return dia.strftime('%Y-%m-%dT%H:%M:%S'), None


def _int_param(nome, padrao, minimo, maximo):
    bruto = (request.args.get(nome) or '').strip()
    if not bruto:
        return padrao, None
    if not re.fullmatch(r'[0-9]+', bruto) or not (minimo <= int(bruto) <= maximo):
        return None, f'{nome} inválido. Use um inteiro de {minimo} a {maximo}'
    return int(bruto), None


@app.route('/api/ordens-servico', methods=['GET'])
def get_ordens():
    """Lista/busca OS.

    Sem parâmetros: todas as OS, do jeito de sempre (urgentes primeiro, mais
    antigas antes), como uma lista JSON.

    Filtros (combináveis, todos opcionais):
      q             texto livre: nº da OS, nº da nota, código ou nome da peça, solicitante
      maquina_id    OS com alguma operação nessa máquina
      status        PLANEJAMENTO | USINANDO | CONCLUIDA
      prioridade    NORMAL | URGENTE
      criada_de / criada_ate / concluida_de / concluida_ate   YYYY-MM-DD (inclusivos)
      operador      parte do e-mail de quem executou alguma operação
      em_atraso     1 = OS aberta com operação não concluída cujo fim planejado já passou
      origem        REAL | DEMONSTRACAO | TODAS (padrão)
    Ordenação: ordenar=<coluna> & direcao=asc|desc (ver ORDENACOES_OS).
    Paginação: pagina e/ou por_pagina (padrão 20, máx. 100) trocam a resposta
    para {itens, total, pagina, por_pagina, paginas}.

    Cada OS traz maquina_atual, planejado_min, realizado_min (só das
    operações concluídas), operadores, em_atraso e atraso_min.
    """
    args = request.args
    onde, params = [], []

    q = (args.get('q') or '').strip()
    if q:
        padrao = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        onde.append('''(os.numero LIKE ? ESCAPE '\\' OR n.numero LIKE ? ESCAPE '\\'
                        OR n.peca_codigo LIKE ? ESCAPE '\\' OR p.nome LIKE ? ESCAPE '\\'
                        OR n.solicitante LIKE ? ESCAPE '\\')''')
        params += [padrao] * 5

    maquina_id = (args.get('maquina_id') or '').strip()
    if maquina_id:
        if not re.fullmatch(r'[0-9]+', maquina_id):
            return jsonify({'erro': 'maquina_id inválido'}), 400
        onde.append('EXISTS (SELECT 1 FROM alocacao_maquinas a WHERE a.ordem_servico_id = os.id AND a.maquina_id = ?)')
        params.append(int(maquina_id))

    status = (args.get('status') or '').strip().upper()
    if status:
        if status not in STATUS_OS:
            return jsonify({'erro': f"status inválido. Use {', '.join(STATUS_OS)}"}), 400
        onde.append('os.status = ?')
        params.append(status)

    prioridade = (args.get('prioridade') or '').strip().upper()
    if prioridade:
        if prioridade not in ('NORMAL', 'URGENTE'):
            return jsonify({'erro': 'prioridade inválida. Use NORMAL ou URGENTE'}), 400
        onde.append('os.prioridade = ?')
        params.append(prioridade)

    for nome, coluna, operador, fim in [('criada_de', 'os.criada_em', '>=', False),
                                        ('criada_ate', 'os.criada_em', '<', True),
                                        ('concluida_de', 'os.concluida_em', '>=', False),
                                        ('concluida_ate', 'os.concluida_em', '<', True)]:
        limite, erro = _data_param(nome, fim_do_dia=fim)
        if erro:
            return jsonify({'erro': erro}), 400
        if limite:
            # replace(' ', 'T'): linhas antigas gravaram 'YYYY-MM-DD HH:MM:SS'
            onde.append(f"replace({coluna}, ' ', 'T') {operador} ?")
            params.append(limite)

    operador_txt = (args.get('operador') or '').strip()
    if operador_txt:
        padrao = '%' + operador_txt.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        onde.append('''EXISTS (SELECT 1 FROM alocacao_maquinas a WHERE a.ordem_servico_id = os.id
                                AND a.operador LIKE ? ESCAPE '\\')''')
        params.append(padrao)

    origem, resposta_erro = _origem_da_requisicao()
    if resposta_erro:
        return resposta_erro
    sql_origem, params_origem = _sql_origem(origem, 'n.origem')
    if sql_origem:
        onde.append(sql_origem.lstrip().removeprefix('AND ').strip())
        params += params_origem

    agora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # Operação em atraso: não concluída, em OS aberta, com o fim planejado já passado.
    sql_atrasada = '''a.ordem_servico_id = os.id AND a.status != 'CONCLUIDO'
                      AND a.fim_planejado IS NOT NULL AND julianday(a.fim_planejado) < julianday(?)'''
    if (args.get('em_atraso') or '').strip().lower() in ('1', 'true', 'sim'):
        onde.append(f"os.status != 'CONCLUIDA' AND EXISTS (SELECT 1 FROM alocacao_maquinas a WHERE {sql_atrasada})")
        params.append(agora)

    ordenar = (args.get('ordenar') or '').strip()
    if ordenar and ordenar not in ORDENACOES_OS:
        return jsonify({'erro': f"ordenar inválido. Use {', '.join(ORDENACOES_OS)}"}), 400
    direcao = (args.get('direcao') or 'asc').strip().lower()
    if direcao not in ('asc', 'desc'):
        return jsonify({'erro': 'direcao inválida. Use asc ou desc'}), 400
    if ordenar:
        # NULLs por último nos dois sentidos, e desempate estável por id
        ordem_sql = f'{ORDENACOES_OS[ordenar]} IS NULL, {ORDENACOES_OS[ordenar]} {direcao.upper()}, os.id ASC'
    else:
        ordem_sql = "CASE WHEN os.prioridade = 'URGENTE' THEN 0 ELSE 1 END, os.criada_em ASC"

    paginado = 'pagina' in args or 'por_pagina' in args
    pagina, erro = _int_param('pagina', 1, 1, 10**6)
    if erro:
        return jsonify({'erro': erro}), 400
    por_pagina, erro = _int_param('por_pagina', POR_PAGINA_PADRAO, 1, POR_PAGINA_MAX)
    if erro:
        return jsonify({'erro': erro}), 400

    filtro = ('WHERE ' + ' AND '.join(onde)) if onde else ''
    base = f'''FROM ordens_servico os
               JOIN notas n ON os.nota_id = n.id
               JOIN pecas p ON n.peca_codigo = p.codigo
               {filtro}'''

    conn = get_db()
    c = conn.cursor()
    total = c.execute(f'SELECT COUNT(*) {base}', params).fetchone()[0]

    c.execute(f'''SELECT os.*, n.numero AS nota_numero, n.peca_codigo, p.nome AS peca_nome,
                         n.solicitante, n.origem,
                         (SELECT m.nome FROM alocacao_maquinas a JOIN maquinas m ON m.id = a.maquina_id
                           WHERE a.ordem_servico_id = os.id AND a.status IN ('EXECUTANDO', 'LIBERADO', 'INTERROMPIDA')
                           ORDER BY CASE a.status WHEN 'EXECUTANDO' THEN 0 ELSE 1 END, a.sequencia
                           LIMIT 1) AS maquina_atual,
                         (SELECT SUM(a.tempo_planejado_min) FROM alocacao_maquinas a
                           WHERE a.ordem_servico_id = os.id) AS planejado_min,
                         (SELECT SUM(a.tempo_realizado_min) FROM alocacao_maquinas a
                           WHERE a.ordem_servico_id = os.id AND a.status = 'CONCLUIDO') AS realizado_min,
                         (SELECT GROUP_CONCAT(DISTINCT a.operador) FROM alocacao_maquinas a
                           WHERE a.ordem_servico_id = os.id AND a.operador IS NOT NULL) AS operadores,
                         CASE WHEN os.status = 'CONCLUIDA' THEN NULL ELSE
                           (SELECT CAST(MAX((julianday(?) - julianday(a.fim_planejado)) * 1440) AS INTEGER)
                              FROM alocacao_maquinas a WHERE {sql_atrasada}) END AS atraso_min
                  {base}
                  ORDER BY {ordem_sql}''' + (' LIMIT ? OFFSET ?' if paginado else ''),
              [agora, agora] + params + ([por_pagina, (pagina - 1) * por_pagina] if paginado else []))
    ordens = []
    for row in c.fetchall():
        o = dict(row)
        o['em_atraso'] = o['atraso_min'] is not None
        ordens.append(o)
    conn.close()

    if not paginado:
        return jsonify(ordens)
    return jsonify({'itens': ordens, 'total': total, 'pagina': pagina, 'por_pagina': por_pagina,
                    'paginas': max(1, -(-total // por_pagina))})

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
@requer_roles('operador', 'coordenador')
def iniciar_ordem(os_id):
    """Inicia execução de uma OS"""
    email = get_jwt_identity()
    conn = get_db()
    c = conn.cursor()

    try:
        # Máquina parada não recebe produção: confere antes de mudar qualquer coisa.
        c.execute('''SELECT m.nome AS maquina_nome, m.status AS maquina_status
                     FROM alocacao_maquinas am
                     JOIN maquinas m ON m.id = am.maquina_id
                     WHERE am.ordem_servico_id = ? AND am.sequencia = 1''', (os_id,))
        primeira = c.fetchone()
        if primeira and primeira['maquina_status'] == 'QUEBRADA':
            return jsonify({
                'erro': f"Máquina {primeira['maquina_nome']} está parada"
            }), 409

        tempo_agora = _agora()

        c.execute('''UPDATE ordens_servico
                    SET status = ?, tempo_inicio = ?
                    WHERE id = ?''',
                 ('USINANDO', tempo_agora.isoformat(), os_id))

        c.execute('''UPDATE alocacao_maquinas
                    SET status = ?, inicio_real = ?, retomada_em = ?, operador = ?
                    WHERE ordem_servico_id = ? AND sequencia = 1''',
                 ('EXECUTANDO', tempo_agora.isoformat(), tempo_agora.isoformat(), email, os_id))

        conn.commit()
        registrar_auditoria('INICIO', 'ORDEM_SERVICO', os_id, 'Execução iniciada', usuario=email)

        return jsonify({'status': 'SUCESSO', 'mensagem': 'OS iniciada'}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({'erro': str(e)}), 400
    finally:
        conn.close()

def possivelmente_esquecida(status, usinagem_min, planejado_min):
    """Operação EXECUTANDO cujo tempo de usinagem já passou de
    OPERACAO_ESQUECIDA_FATOR x o planejado (ambos em minutos de expediente):
    quase sempre é operação deixada em aberto, não produção."""
    return (status == 'EXECUTANDO' and bool(planejado_min) and usinagem_min is not None
            and usinagem_min > OPERACAO_ESQUECIDA_FATOR * planejado_min)


def _planejado_da_operacao(op):
    """Duração planejada em minutos de trabalho: a gravada no planejamento; só
    linhas anteriores à coluna caem na diferença fim - início."""
    planejado = op.get('tempo_planejado_min')
    if planejado is None and op.get('inicio_planejado') and op.get('fim_planejado'):
        try:
            planejado = int((datetime.fromisoformat(op['fim_planejado'])
                             - datetime.fromisoformat(op['inicio_planejado'])).total_seconds() / 60)
        except (ValueError, TypeError):
            planejado = None
    return planejado


def _paradas_da_alocacao(c, alocacao_id, agora):
    """Interrupções de uma operação, em ordem: início, fim (None se a máquina
    ainda está parada), duração em minutos corridos e em minutos de
    EXPEDIENTE (a que representa produção perdida). Parada aberta conta até agora."""
    paradas = []
    for r in c.execute('''SELECT id, inicio, fim FROM paradas_operacao
                          WHERE alocacao_id = ? ORDER BY inicio''', (alocacao_id,)):
        ini, fim = _parse_ts(r['inicio']), _parse_ts(r['fim'])
        ate = fim or agora
        paradas.append({
            'id': r['id'], 'inicio': r['inicio'], 'fim': r['fim'], 'aberta': fim is None,
            'duracao_min': max(int((ate - ini).total_seconds() / 60), 0) if ini else 0,
            'expediente_min': minutos_de_expediente(ini, ate) if ini else 0,
        })
    return paradas


def _tempos_da_operacao(op, paradas, agora, planejado=None):
    """tempo_usinagem_min (só máquina rodando), tempo parado (corrido e de
    expediente) de uma operação. op traz status, tempo_acumulado_min,
    retomada_em, inicio_real e tempo_realizado_min."""
    if op.get('tempo_realizado_min') is not None and op.get('status') == 'CONCLUIDO':
        usinagem = op['tempo_realizado_min']
        # linha anterior à coluna dos corridos: o valor gravado era corrido
        corrido = op.get('tempo_realizado_corrido_min')
        if corrido is None:
            corrido = usinagem
    elif op.get('inicio_real'):
        usinagem = op.get('tempo_acumulado_min') or 0
        corrido = op.get('tempo_acumulado_corrido_min') or 0
        if op.get('status') == 'EXECUTANDO':
            exp, corr = _trecho(op.get('retomada_em') or op['inicio_real'], agora)
            usinagem += exp
            corrido += corr
    else:
        usinagem = corrido = None
    if planejado is None:
        planejado = _planejado_da_operacao(op)
    fora = fora_do_expediente(corrido, usinagem)
    return {'tempo_usinagem_min': usinagem,               # minutos de expediente
            'tempo_usinagem_corrido_min': corrido,        # minutos corridos
            # EXECUTANDO passou muito do planejado: possivelmente esquecida em aberto
            'possivelmente_esquecida': possivelmente_esquecida(op.get('status'), usinagem, planejado),
            'limite_esquecida_min': int(OPERACAO_ESQUECIDA_FATOR * planejado) if planejado else None,
            # concluída fora do expediente: fica fora do tempo médio e do desvio
            'excluida_dos_indicadores': op.get('status') == 'CONCLUIDO' and fora,
            'fora_do_expediente': fora,
            'fora_do_expediente_min': (corrido - usinagem) if fora_do_expediente(corrido, usinagem) else 0,
            'tempo_parado_min': sum(p['duracao_min'] for p in paradas),
            'tempo_parado_expediente_min': sum(p['expediente_min'] for p in paradas)}


@app.route('/api/ordens-servico/<int:os_id>/operacoes', methods=['GET'])
def get_operacoes_os(os_id):
    """Operações de uma OS com planejado x realizado."""
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT am.id, am.sequencia, am.status,
                        am.inicio_planejado, am.fim_planejado, am.tempo_planejado_min,
                        am.inicio_real, am.fim_real,
                        am.tempo_realizado_min, am.operador, am.observacao,
                        am.tempo_acumulado_min, am.retomada_em,
                        am.tempo_realizado_corrido_min, am.tempo_acumulado_corrido_min,
                        m.nome AS maquina_nome, m.status AS maquina_status
                 FROM alocacao_maquinas am
                 JOIN maquinas m ON m.id = am.maquina_id
                 WHERE am.ordem_servico_id = ?
                 ORDER BY am.sequencia''', (os_id,))
    operacoes = []
    agora = _agora()
    for row in c.fetchall():
        op = dict(row)
        op['paradas'] = _paradas_da_alocacao(c, op['id'], agora)

        # Tempo planejado é a duração gravada no planejamento (minutos de
        # trabalho): com expediente, fim - início inclui a noite. O realizado
        # só existe se a operação foi de fato concluída. Os dois campos vão
        # separados de propósito: a tela precisa poder dizer qual é medido.
        planejado = _planejado_da_operacao(op)
        op.update(_tempos_da_operacao(op, op['paradas'], agora, planejado))
        op['tempo_planejado_min'] = planejado
        op['desvio_min'] = (
            op['tempo_realizado_min'] - planejado
            if planejado is not None and op['tempo_realizado_min'] is not None
            else None
        )
        operacoes.append(op)

    conn.close()
    return jsonify(operacoes)


def _parse_ts(valor):
    """Lê um timestamp do banco aceitando os dois formatos que existem lá.

    Registros novos gravam '2026-09-19T12:56:36' (isoformat).
    Registros antigos, de antes da Fase 1, gravam '2026-09-15 23:54:12'
    (CURRENT_TIMESTAMP do SQLite). Os dois precisam funcionar enquanto
    houver histórico anterior à migração.
    """
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace(' ', 'T'))
    except (ValueError, TypeError):
        return None


@app.route('/api/programacao', methods=['GET'])
def get_programacao():
    """Programação da oficina num dia, máquina por máquina.

    Query string:
        data=YYYY-MM-DD  (padrão: hoje)

    Devolve, para cada máquina, as operações alocadas naquele dia, com a
    posição de cada barra já calculada em porcentagem da janela (o
    expediente do dia). O frontend só desenha — não faz conta de horário.
    """
    data_str = request.args.get('data') or datetime.now().strftime('%Y-%m-%d')

    try:
        dia = datetime.strptime(data_str, '%Y-%m-%d')
    except ValueError:
        return jsonify({'erro': 'Data inválida. Use YYYY-MM-DD'}), 400

    dia_inicio = dia.replace(hour=0, minute=0, second=0, microsecond=0)
    dia_fim = dia_inicio + timedelta(days=1)

    conn = get_db()
    c = conn.cursor()

    c.execute('''SELECT m.id, m.nome, m.status, m.localizacao, m.quebrada_em
                 FROM maquinas m
                 ORDER BY m.id''')
    maquinas_rows = c.fetchall()

    c.execute('''SELECT am.id, am.maquina_id, am.sequencia, am.status,
                        am.inicio_planejado, am.fim_planejado,
                        am.inicio_real, am.fim_real,
                        am.tempo_realizado_min, am.operador,
                        am.tempo_acumulado_min, am.retomada_em, am.tempo_planejado_min,
                        am.tempo_acumulado_corrido_min, am.tempo_realizado_corrido_min,
                        os.id AS os_id, os.numero AS os_numero,
                        os.prioridade,
                        n.id AS nota_id, n.origem AS nota_origem,
                        n.peca_codigo, p.nome AS peca_nome
                 FROM alocacao_maquinas am
                 JOIN ordens_servico os ON os.id = am.ordem_servico_id
                 JOIN notas n ON n.id = os.nota_id
                 LEFT JOIN pecas p ON p.codigo = n.peca_codigo
                 ORDER BY am.maquina_id, am.inicio_planejado''')
    todas = [dict(r) for r in c.fetchall()]
    agora_dt = _agora()
    paradas_por_aloc = {}
    for r in c.execute('SELECT alocacao_id, inicio, fim FROM paradas_operacao ORDER BY inicio'):
        paradas_por_aloc.setdefault(r['alocacao_id'], []).append(dict(r))
    conn.close()

    # O planejado só existe em expediente: num sábado, domingo ou feriado não
    # há trabalho planejado, mesmo que o intervalo contínuo de uma operação
    # que atravessa o fim de semana "cubra" o dia.
    planejado_no_dia = eh_dia_util(dia.date())

    # Fica só o que encosta no dia pedido, pelo planejado ou pelo realizado.
    def toca_o_dia(a):
        pares = [('inicio_real', 'fim_real')]
        if planejado_no_dia:
            pares.insert(0, ('inicio_planejado', 'fim_planejado'))
        for campo_ini, campo_fim in pares:
            ini = _parse_ts(a[campo_ini])
            fim = _parse_ts(a[campo_fim]) or ini
            if ini and fim and ini < dia_fim and fim >= dia_inicio:
                return True
        return False

    do_dia = [a for a in todas if toca_o_dia(a)]

    # Janela do eixo: o expediente do dia pedido. Uma operação que atravessa
    # a noite aparece recortada em cada dia. Execução REAL fora do expediente
    # não some da tela: o eixo se estende, só naquele dia, o bastante para
    # mostrá-la.
    janela_ini = abertura_do_dia(dia.date())
    janela_fim = fechamento_do_dia(dia.date())
    for a in do_dia:
        ini_r = _parse_ts(a['inicio_real'])
        # (operação com paradas ainda não concluída: o realizado chega até agora)
        fim_r = _parse_ts(a['fim_real']) or (agora_dt if paradas_por_aloc.get(a['id']) else ini_r)
        # A operação pode estar no dia só pelo planejado e ter sido executada
        # em outro: essa execução não conta para o eixo deste dia.
        if not ini_r or not (ini_r < dia_fim and fim_r >= dia_inicio):
            continue
        for ts in (max(ini_r, dia_inicio), min(fim_r, dia_fim)):
            hora_cheia = ts.replace(minute=0, second=0, microsecond=0)
            janela_ini = min(janela_ini, hora_cheia)
            if hora_cheia < ts:
                hora_cheia += timedelta(hours=1)
            janela_fim = max(janela_fim, min(hora_cheia, dia_fim))

    total_min = max(int((janela_fim - janela_ini).total_seconds() / 60), 1)

    def faixa(ini_str, fim_str):
        """Converte um par de timestamps em posição e largura, em %.

        Horário e minutos devolvidos são os do trecho visível no dia, não os
        da operação inteira: uma barra 16h→8h mostra 16:00–17:00 num dia e
        07:00–08:00 no outro.
        """
        ini = _parse_ts(ini_str)
        fim = _parse_ts(fim_str)
        if not ini:
            return None
        if not fim:
            fim = ini + timedelta(minutes=1)
        ini_rec = max(ini, janela_ini)
        fim_rec = min(fim, janela_fim)
        if fim_rec <= ini_rec:
            return None
        esquerda = (ini_rec - janela_ini).total_seconds() / 60 / total_min * 100
        largura = (fim_rec - ini_rec).total_seconds() / 60 / total_min * 100
        return {
            'esquerda_pct': round(esquerda, 3),
            'largura_pct': round(max(largura, 0.6), 3),  # piso para não sumir
            'inicio': ini_rec.strftime('%H:%M'),
            'fim': fim_rec.strftime('%H:%M'),
            'minutos': int((fim_rec - ini_rec).total_seconds() / 60),
        }

    por_maquina = {}
    for a in do_dia:
        por_maquina.setdefault(a['maquina_id'], []).append(a)

    conflitos = []
    maquinas = []

    for m in maquinas_rows:
        alocs = por_maquina.get(m['id'], [])
        barras = []

        for a in alocs:
            planejado = (faixa(a['inicio_planejado'], a['fim_planejado'])
                         if planejado_no_dia else None)
            # Operação com paradas (Etapa 3A) e ainda não concluída: o realizado
            # vai de inicio_real até agora, e cada trecho parado é desenhado à parte.
            paradas_op = paradas_por_aloc.get(a['id'], [])
            realizado = faixa(a['inicio_real'],
                              a['fim_real'] or (agora_dt.isoformat() if paradas_op else a['inicio_real']))
            faixas_paradas = []
            for pa in paradas_op:
                f = faixa(pa['inicio'], pa['fim'] or agora_dt.isoformat())
                if f:
                    f['aberta'] = pa['fim'] is None
                    faixas_paradas.append(f)

            barras.append({
                'alocacao_id': a['id'],
                'os_id': a['os_id'],
                'os_numero': a['os_numero'],
                'sequencia': a['sequencia'],
                'status': a['status'],
                'prioridade': a['prioridade'],
                'peca_codigo': a['peca_codigo'],
                'peca_nome': a['peca_nome'],
                'operador': a['operador'],
                'planejado': planejado,
                'realizado': realizado,
                'tempo_realizado_min': a['tempo_realizado_min'],
                'tempo_acumulado_min': a['tempo_acumulado_min'],
                'paradas': faixas_paradas,
                # EXECUTANDO há muito mais que o planejado: possivelmente esquecida em aberto
                'possivelmente_esquecida': _tempos_da_operacao(a, [], agora_dt)['possivelmente_esquecida'],
            })

        # Conflito: duas operações planejadas na mesma máquina com horário
        # sobreposto. É o que o coordenador não enxerga numa tabela.
        for i in range(len(alocs)):
            for j in range(i + 1, len(alocs)):
                a1, a2 = alocs[i], alocs[j]
                i1, f1 = _parse_ts(a1['inicio_planejado']), _parse_ts(a1['fim_planejado'])
                i2, f2 = _parse_ts(a2['inicio_planejado']), _parse_ts(a2['fim_planejado'])
                if not (i1 and f1 and i2 and f2):
                    continue
                if i1 < f2 and i2 < f1:
                    sobreposicao = int(
                        (min(f1, f2) - max(i1, i2)).total_seconds() / 60
                    )
                    conflitos.append({
                        'maquina_id': m['id'],
                        'maquina_nome': m['nome'],
                        'os_a': a1['os_numero'],
                        'os_b': a2['os_numero'],
                        'sobreposicao_min': sobreposicao,
                    })

        maquinas.append({
            'id': m['id'],
            'nome': m['nome'],
            'status': m['status'],
            'localizacao': m['localizacao'],
            'parada': m['status'] == 'QUEBRADA',
            'barras': barras,
        })

    # Marcas de hora do eixo
    marcas = []
    cursor = janela_ini
    while cursor <= janela_fim:
        marcas.append({
            'hora': cursor.strftime('%H:%M'),
            'esquerda_pct': round(
                (cursor - janela_ini).total_seconds() / 60 / total_min * 100, 3
            ),
        })
        cursor += timedelta(hours=1)

    # Linha do "agora", só se o dia pedido for hoje
    agora = _agora()
    agora_pct = None
    if janela_ini <= agora <= janela_fim:
        agora_pct = round(
            (agora - janela_ini).total_seconds() / 60 / total_min * 100, 3
        )

    return jsonify({
        'data': data_str,
        'janela_inicio': janela_ini.strftime('%H:%M'),
        'janela_fim': janela_fim.strftime('%H:%M'),
        'marcas': marcas,
        'agora_pct': agora_pct,
        'maquinas': maquinas,
        'conflitos': conflitos,
        'total_operacoes': len(do_dia),
        # Notas por trás das operações mostradas neste dia. Não há filtro
        # aqui: a tela mostra tudo e só avisa quando há demonstração.
        'origem_dados': _origem_das_notas(do_dia),
    })


@app.route('/api/alocacoes/<int:alocacao_id>/iniciar', methods=['POST'])
@requer_roles('operador', 'coordenador')
def iniciar_alocacao(alocacao_id):
    """Operador assume uma operação liberada e começa a executá-la."""
    email = get_jwt_identity()
    conn = get_db()
    c = conn.cursor()

    try:
        c.execute('''SELECT am.*, m.nome AS maquina_nome, m.status AS maquina_status,
                            os.numero AS os_numero
                     FROM alocacao_maquinas am
                     JOIN maquinas m ON m.id = am.maquina_id
                     JOIN ordens_servico os ON os.id = am.ordem_servico_id
                     WHERE am.id = ?''', (alocacao_id,))
        aloc = c.fetchone()

        if not aloc:
            return jsonify({'erro': 'Operação não encontrada'}), 404
        # Uma operação que já começou só pode ser iniciada de novo se foi
        # interrompida por quebra e a máquina já foi consertada (LIBERADO): é
        # uma RETOMADA, que preserva inicio_real e o tempo já acumulado.
        if aloc['inicio_real']:
            if aloc['status'] == 'INTERROMPIDA':
                return jsonify({
                    'erro': f"Operação interrompida: a máquina {aloc['maquina_nome']} está parada. "
                            f"Aguarde o conserto para retomar"
                }), 409
            if aloc['status'] != 'LIBERADO':
                return jsonify({'erro': 'Operação já iniciada'}), 400
        retomada = bool(aloc['inicio_real'])
        # Sequência de fabricação: só começa depois que a anterior terminou.
        if aloc['sequencia'] > 1:
            anterior = c.execute('''SELECT status FROM alocacao_maquinas
                                    WHERE ordem_servico_id = ? AND sequencia = ?''',
                                 (aloc['ordem_servico_id'], aloc['sequencia'] - 1)).fetchone()
            if anterior and anterior['status'] != 'CONCLUIDO':
                return jsonify({
                    'erro': f"A operação anterior (OP {aloc['sequencia'] - 1}) da {aloc['os_numero']} "
                            f"ainda não foi concluída. Conclua-a antes de iniciar a OP {aloc['sequencia']}"
                }), 409
        if aloc['maquina_status'] == 'QUEBRADA':
            return jsonify({
                'erro': f"Máquina {aloc['maquina_nome']} está parada"
            }), 409

        agora = _agora().isoformat()
        if retomada:
            c.execute('''UPDATE alocacao_maquinas
                         SET status = 'EXECUTANDO', retomada_em = ?
                         WHERE id = ?''', (agora, alocacao_id))
        else:
            c.execute('''UPDATE alocacao_maquinas
                         SET status = 'EXECUTANDO', inicio_real = ?, retomada_em = ?, operador = ?
                         WHERE id = ?''', (agora, agora, email, alocacao_id))
        # Iniciar a 1ª operação é iniciar a OS (o que /ordens-servico/<id>/iniciar
        # já faz): sem isto a OS ficava em PLANEJAMENTO com a operação rodando.
        if aloc['sequencia'] == 1:
            c.execute('''UPDATE ordens_servico
                         SET status = 'USINANDO', tempo_inicio = COALESCE(tempo_inicio, ?)
                         WHERE id = ? AND status = 'PLANEJAMENTO' ''',
                      (agora, aloc['ordem_servico_id']))
        conn.commit()

        registrar_auditoria(
            'OPERACAO_RETOMADA' if retomada else 'OPERACAO_INICIADA', 'ALOCACAO', alocacao_id,
            f"OP {aloc['sequencia']} da {aloc['os_numero']} {'retomada' if retomada else 'iniciada'} por {email} "
            f"na {aloc['maquina_nome']}"
            + (f" ({aloc['tempo_acumulado_min'] or 0} min de usinagem já feitos)" if retomada else ''),
            usuario=email
        )

        socketio.emit('operacao_iniciada', {
            'alocacao_id': alocacao_id,
            'os_numero': aloc['os_numero'],
            'sequencia': aloc['sequencia'],
            'maquina': aloc['maquina_nome'],
            'operador': email,
            'retomada': retomada,
        })

        return jsonify({'status': 'ok', 'inicio_real': aloc['inicio_real'] or agora,
                        'retomada_em': agora, 'retomada': retomada}), 200

    except Exception as e:
        conn.rollback()
        logger.error(f'Erro ao iniciar operação {alocacao_id}: {e}')
        return jsonify({'erro': str(e)}), 400
    finally:
        conn.close()


@app.route('/api/alocacoes/<int:alocacao_id>/concluir', methods=['POST'])
@requer_roles('operador', 'coordenador')
def concluir_alocacao(alocacao_id):
    """Conclui uma operação, mede o tempo gasto e libera a seguinte.

    É aqui que fim_real passa a existir. Todo indicador de tempo realizado
    do sistema depende deste endpoint ser chamado.
    """
    email = get_jwt_identity()
    dados = request.json or {}
    observacao = (dados.get('observacao') or '').strip()

    conn = get_db()
    c = conn.cursor()

    try:
        c.execute('''SELECT am.*, m.nome AS maquina_nome,
                            os.numero AS os_numero, os.id AS os_id,
                            n.peca_codigo
                     FROM alocacao_maquinas am
                     JOIN maquinas m ON m.id = am.maquina_id
                     JOIN ordens_servico os ON os.id = am.ordem_servico_id
                     JOIN notas n ON n.id = os.nota_id
                     WHERE am.id = ?''', (alocacao_id,))
        aloc = c.fetchone()

        if not aloc:
            return jsonify({'erro': 'Operação não encontrada'}), 404
        if aloc['fim_real']:
            return jsonify({'erro': 'Operação já concluída'}), 400
        if not aloc['inicio_real']:
            return jsonify({'erro': 'Operação ainda não foi iniciada'}), 400
        if aloc['status'] == 'INTERROMPIDA':
            return jsonify({'erro': f"Operação interrompida: a máquina {aloc['maquina_nome']} está parada. "
                                    f"Aguarde o conserto e retome a operação antes de concluir"}), 409
        if aloc['status'] == 'LIBERADO':
            return jsonify({'erro': 'Operação ainda não foi retomada. Inicie-a de novo antes de concluir'}), 409

        agora = _agora()

        # Tempo de usinagem = o que já estava acumulado antes de interrupções
        # + a execução atual (desde retomada_em; inicio_real nas linhas de
        # antes da Etapa 3A). O tempo de máquina parada fica de fora. Em
        # minutos de EXPEDIENTE (a régua do planejado); os corridos vão para
        # tempo_realizado_corrido_min.
        realizado = realizado_corrido = None
        if _parse_ts(aloc['retomada_em'] or aloc['inicio_real']):
            expediente, corrido = _trecho(aloc['retomada_em'] or aloc['inicio_real'], agora)
            realizado = (aloc['tempo_acumulado_min'] or 0) + expediente
            realizado_corrido = (aloc['tempo_acumulado_corrido_min'] or 0) + corrido

        c.execute('''UPDATE alocacao_maquinas
                     SET status = 'CONCLUIDO', fim_real = ?,
                         tempo_realizado_min = ?, tempo_realizado_corrido_min = ?,
                         observacao = ?, operador = COALESCE(operador, ?)
                     WHERE id = ?''',
                  (agora.isoformat(), realizado, realizado_corrido, observacao or None,
                   email, alocacao_id))

        # A próxima operação da mesma OS fica disponível para ser assumida.
        c.execute('''SELECT id, sequencia, maquina_id
                     FROM alocacao_maquinas
                     WHERE ordem_servico_id = ? AND sequencia = ?''',
                  (aloc['ordem_servico_id'], aloc['sequencia'] + 1))
        proxima = c.fetchone()

        os_concluida = False
        if proxima:
            c.execute('''UPDATE alocacao_maquinas SET status = 'LIBERADO'
                         WHERE id = ?''', (proxima['id'],))
        else:
            # Era a última operação: a OS terminou.
            c.execute('''UPDATE ordens_servico
                         SET status = 'CONCLUIDA', tempo_fim = ?, concluida_em = ?
                         WHERE id = ?''',
                      (agora.isoformat(), agora.isoformat(),
                       aloc['ordem_servico_id']))
            os_concluida = True

        conn.commit()

        registrar_auditoria(
            'OPERACAO_CONCLUIDA', 'ALOCACAO', alocacao_id,
            f"OP {aloc['sequencia']} da {aloc['os_numero']} concluída por {email} "
            f"em {realizado if realizado is not None else '?'} min"
            + (f". Observação: {observacao}" if observacao else ''),
            usuario=email
        )

        if os_concluida:
            registrar_auditoria(
                'OS_CONCLUIDA', 'ORDEM_SERVICO', aloc['ordem_servico_id'],
                f"{aloc['os_numero']} concluída — peça {aloc['peca_codigo']}",
                usuario=email
            )

        socketio.emit('operacao_concluida', {
            'alocacao_id': alocacao_id,
            'os_id': aloc['ordem_servico_id'],
            'os_numero': aloc['os_numero'],
            'sequencia': aloc['sequencia'],
            'maquina': aloc['maquina_nome'],
            'tempo_realizado_min': realizado,
            'tempo_realizado_corrido_min': realizado_corrido,
            'os_concluida': os_concluida,
            'proxima_liberada': dict(proxima)['sequencia'] if proxima else None,
        })

        return jsonify({
            'status': 'ok',
            'tempo_realizado_min': realizado,                    # minutos de expediente
            'tempo_realizado_corrido_min': realizado_corrido,    # minutos corridos (auditoria)
            'fora_do_expediente': fora_do_expediente(realizado_corrido, realizado),
            'os_concluida': os_concluida,
        }), 200

    except Exception as e:
        conn.rollback()
        logger.error(f'Erro ao concluir operação {alocacao_id}: {e}')
        return jsonify({'erro': str(e)}), 400
    finally:
        conn.close()


@app.route('/api/pecas', methods=['GET'])
def get_pecas():
    """Lista todas as peças, com a ficha técnica e o que falta cadastrar
    (tem_desenho, ficha e ficha_faltando) para a equipe ver o que está pendente."""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM pecas ORDER BY codigo')
    pecas = []
    for row in c.fetchall():
        p = {k: v for k, v in dict(row).items() if k not in FICHA_CAMPOS}   # a ficha vai em 'ficha'
        p.update(ficha_da_peca(row))
        p['tem_desenho'] = tem_desenho(p['codigo'])
        p['desenho_provisorio'] = desenho_provisorio(p['codigo'])   # PDF existe, mas é placeholder
        pecas.append(p)
    conn.close()
    return jsonify(pecas)

@app.route('/api/pecas/<codigo>/desenho', methods=['GET'])
def get_desenho_tecnico(codigo):
    """Desenho técnico em PDF de uma peça, se existir.

    Não havia rota nenhuma servindo isto: o único caminho de hoje é
    enviar_nota_telegram() lendo o arquivo do disco local do backend e
    mandando direto para o grupo. O bot do Telegram é outro processo — se
    ele lesse esse arquivo do próprio disco, ia depender de rodar na mesma
    máquina que o backend, o que quebra em produção. Daí esta rota: o bot
    busca o PDF pela API, como qualquer outro cliente.
    """
    if not CODIGO_PECA_REGEX.match(codigo):
        return jsonify({'erro': 'Código de peça inválido'}), 400
    nome_arquivo = f'{codigo}.pdf'
    if not os.path.isfile(os.path.join(DESENHOS_DIR, nome_arquivo)):
        return jsonify({'erro': 'Desenho técnico não encontrado para esta peça'}), 404
    return send_from_directory(DESENHOS_DIR, nome_arquivo, mimetype='application/pdf')


@app.route('/fotos_maquinas/<filename>')
def serve_foto(filename):
    return send_from_directory('fotos_maquinas', filename)

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
@requer_roles('operador', 'coordenador')
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

    agora = _agora()
    momento_quebra = agora.isoformat()
    c.execute("UPDATE maquinas SET status = 'QUEBRADA', quebrada_em = ? WHERE id = ?",
              (momento_quebra, maquina_id))
    # A operação que estava EXECUTANDO nesta máquina para de contar tempo de usinagem.
    interrompidas = _interromper_operacoes(c, maquina_id, agora)
    conn.commit()
    conn.close()

    registrar_auditoria('MAQUINA_QUEBRADA', 'MAQUINA', maquina_id, f'Máquina marcada como quebrada por {email}', usuario=email)
    for op in interrompidas:
        registrar_auditoria(
            'OPERACAO_INTERROMPIDA', 'ALOCACAO', op['alocacao_id'],
            f"OP {op['sequencia']} da {op['os_numero']} interrompida: {maquina['nome']} quebrou "
            f"({op['tempo_acumulado_min']} min de usinagem já feitos)", usuario=email)
        socketio.emit('operacao_interrompida', {**op, 'maquina': maquina['nome']})

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
@requer_roles('coordenador')
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

    agora = _agora()

    # tempo de reparo = agora - quebrada_em. Só calcula se a quebra foi
    # registrada; máquinas que quebraram antes desta versão têm quebrada_em
    # nulo, e aí o tempo fica nulo em vez de virar um número inventado.
    tempo_reparo = None
    if maquina['quebrada_em']:
        try:
            inicio_parada = datetime.fromisoformat(maquina['quebrada_em'])
            tempo_reparo = int((agora - inicio_parada).total_seconds() / 60)
        except (ValueError, TypeError):
            tempo_reparo = None

    c.execute('''UPDATE maquinas
                 SET status = 'DISPONIVEL', ultimo_conserto = ?, quebrada_em = NULL
                 WHERE id = ?''',
              (agora.isoformat(), maquina_id))

    c.execute('''INSERT INTO relatorios_manutencao
                 (maquina_id, usuario, descricao, quebrada_em, tempo_reparo_min, criado_em)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (maquina_id, email, relatorio,
               maquina['quebrada_em'], tempo_reparo, agora.isoformat()))
    relatorio_id = c.lastrowid
    # Operações interrompidas voltam a LIBERADO; NÃO retomam sozinhas.
    liberadas = _liberar_operacoes_interrompidas(c, maquina_id, agora, relatorio_id)
    conn.commit()
    conn.close()

    registrar_auditoria('MAQUINA_CONSERTADA', 'MAQUINA', maquina_id, f'Máquina consertada por {email}: {relatorio}', usuario=email)
    for op in liberadas:
        registrar_auditoria(
            'OPERACAO_LIBERADA', 'ALOCACAO', op['alocacao_id'],
            f"OP {op['sequencia']} da {op['os_numero']} liberada para retomada: {maquina['nome']} consertada",
            usuario=email)
        socketio.emit('operacao_liberada', {**op, 'maquina': maquina['nome']})

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
    c.execute('INSERT INTO chat_manutencao (usuario, role, mensagem, criado_em) VALUES (?, ?, ?, ?)',
             (email, role, mensagem, datetime.now().isoformat()))
    conn.commit()
    msg_id = c.lastrowid
    c.execute('SELECT * FROM chat_manutencao WHERE id = ?', (msg_id,))
    nova_msg = dict(c.fetchone())
    conn.close()

    registrar_auditoria('CHAT_MANUTENCAO', 'CHAT', msg_id, f'{email} ({role}): {mensagem}', usuario=email)

    socketio.emit('chat_msg', nova_msg)

    return jsonify(nova_msg), 201

@app.route('/api/metricas', methods=['GET'])
def get_metricas():
    """Retorna métricas do sistema, calculadas em tempo real a partir do banco.

    Query string:
        origem=REAL|DEMONSTRACAO|TODAS  (padrão TODAS)
    """
    origem, erro = _origem_da_requisicao()
    if erro:
        return erro
    filtro, params = _sql_origem(origem, 'n.origem')

    conn = get_db()
    c = conn.cursor()

    c.execute(f'SELECT COUNT(*) as total FROM notas n WHERE {filtro}', params)
    total_notas = c.fetchone()['total']

    c.execute(f'''SELECT COUNT(*) as total FROM ordens_servico os
                  JOIN notas n ON n.id = os.nota_id
                  WHERE os.status = 'CONCLUIDA' AND {filtro}''', params)
    os_concluidas = c.fetchone()['total']

    c.execute(f'''SELECT COUNT(*) as total FROM ordens_servico os
                  JOIN notas n ON n.id = os.nota_id WHERE {filtro}''', params)
    os_total = c.fetchone()['total']

    origem_dados = _contar_origens(c, 'notas', origem)

    conn.close()

    taxa_aderencia = round((os_concluidas / os_total) * 100, 1) if os_total else 0.0

    agora = datetime.now()
    economia = calcular_economia(MESES_PT[agora.month], agora.year, origem)

    return jsonify({
        'total_notas': total_notas,
        'os_concluidas': os_concluidas,
        'taxa_aderencia': taxa_aderencia,
        'economia_mensal': economia['economia_mensal'],
        'tempo_economizado_horas': economia['tempo_economizado'],
        'origem_dados': origem_dados,
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
    registrar_auditoria('LOGIN', 'USUARIO', usuario['id'], f'Login realizado: {email}', usuario=email)

    return jsonify({'token': token, 'role': usuario['role'], 'usuario': email})


# ============================================================================
# BOT DO TELEGRAM - ETAPA 1 (vínculo de conta)
# ============================================================================
#
# O bot NÃO tem rotas próprias de domínio: ele troca telegram_id por um JWT
# aqui e chama as MESMAS rotas que o site usa (/api/maquinas, /api/notas,
# /api/painel/operador etc.) com esse token, como qualquer outro cliente.

def _gerar_codigo_vinculo():
    """6 dígitos, com zero à esquerda quando sair menor que 100000.
    secrets.randbelow (não random.randint) porque isto é usado como senha
    de uso único, mesmo que curta."""
    return f'{secrets.randbelow(1_000_000):06d}'


def _bot_autorizado():
    """True só se BOT_SERVICE_TOKEN estiver configurado E bater com o
    header X-Bot-Token da requisição. compare_digest evita que a diferença
    de tempo de resposta vaze quantos caracteres já bateram (timing attack)."""
    if not BOT_SERVICE_TOKEN:
        return False
    return secrets.compare_digest(request.headers.get('X-Bot-Token', ''), BOT_SERVICE_TOKEN)


@app.route('/api/telegram/status', methods=['GET'])
@jwt_required()
def status_telegram():
    """Diz ao site se a conta do usuário logado já tem um Telegram vinculado
    (a tela Acesso mostra isso no lugar do botão de gerar código)."""
    conn = get_db()
    linha = conn.execute('SELECT telegram_id FROM usuarios WHERE email = ?',
                         (get_jwt_identity(),)).fetchone()
    conn.close()
    if not linha:
        return jsonify({'erro': 'Usuário não encontrado'}), 404
    return jsonify({'vinculado': linha['telegram_id'] is not None})


@app.route('/api/telegram/gerar-codigo', methods=['POST'])
@jwt_required()
def gerar_codigo_telegram():
    """O usuário logado no site pede um código para vincular o Telegram.

    Um código por usuário: gerar de novo apaga qualquer um ainda pendente
    (uso único — não dá pra ter dois códigos válidos ao mesmo tempo para a
    mesma conta).
    """
    email = get_jwt_identity()
    conn = get_db()
    c = conn.cursor()
    usuario = c.execute('SELECT id FROM usuarios WHERE email = ?', (email,)).fetchone()
    if not usuario:
        conn.close()
        return jsonify({'erro': 'Usuário não encontrado'}), 404

    codigo = _gerar_codigo_vinculo()
    agora = datetime.now()  # hora local, igual a expira_em (o DEFAULT do banco seria UTC)
    expira_em = agora + timedelta(minutes=VINCULO_CODIGO_EXPIRA_MIN)

    c.execute('DELETE FROM vinculos_pendentes WHERE usuario_id = ?', (usuario['id'],))
    c.execute('INSERT INTO vinculos_pendentes (usuario_id, codigo, criado_em, expira_em) VALUES (?, ?, ?, ?)',
             (usuario['id'], codigo, agora.isoformat(), expira_em.isoformat()))
    conn.commit()
    conn.close()

    return jsonify({
        'codigo': codigo,
        'expira_em': expira_em.isoformat(),
        'validade_minutos': VINCULO_CODIGO_EXPIRA_MIN,
    }), 201


@app.route('/api/telegram/vincular', methods=['POST'])
def vincular_telegram():
    """Chamado pelo bot (nunca pelo navegador): troca o código de 6 dígitos
    pelo vínculo telegram_id <-> usuário. Exige o token de serviço do bot.
    """
    if not _bot_autorizado():
        return jsonify({'erro': 'Token de serviço inválido'}), 401

    dados = request.json or {}
    codigo = (dados.get('codigo') or '').strip()
    telegram_id = dados.get('telegram_id')

    if not codigo or not telegram_id:
        return jsonify({'erro': 'codigo e telegram_id são obrigatórios'}), 400

    conn = get_db()
    c = conn.cursor()
    try:
        agora = datetime.now()

        bloqueio = c.execute(
            'SELECT bloqueado_ate FROM tentativas_vinculo_telegram WHERE telegram_id = ?',
            (telegram_id,)).fetchone()
        if bloqueio and bloqueio['bloqueado_ate'] and datetime.fromisoformat(bloqueio['bloqueado_ate']) > agora:
            return jsonify({'erro': 'Muitas tentativas erradas. Gere um novo código e tente de novo mais tarde.'}), 429

        pendente = c.execute(
            '''SELECT vp.id, vp.usuario_id, vp.expira_em, u.email, u.role
               FROM vinculos_pendentes vp JOIN usuarios u ON u.id = vp.usuario_id
               WHERE vp.codigo = ?''', (codigo,)).fetchone()
        valido = pendente and datetime.fromisoformat(pendente['expira_em']) > agora

        if not valido:
            # Tentativa errada não bate em nenhuma linha de vinculos_pendentes
            # (o código digitado pode nem existir), então o contador de
            # tentativas é por telegram_id, não pelo código.
            c.execute('''INSERT INTO tentativas_vinculo_telegram (telegram_id, tentativas, bloqueado_ate)
                        VALUES (?, 1, NULL)
                        ON CONFLICT(telegram_id) DO UPDATE SET
                            tentativas = tentativas_vinculo_telegram.tentativas + 1,
                            bloqueado_ate = CASE WHEN tentativas_vinculo_telegram.tentativas + 1 >= ?
                                                 THEN ? ELSE NULL END''',
                      (telegram_id, VINCULO_MAX_TENTATIVAS,
                       (agora + timedelta(minutes=VINCULO_BLOQUEIO_MIN)).isoformat()))
            conn.commit()
            return jsonify({'erro': 'Código inválido ou expirado'}), 400

        c.execute('UPDATE usuarios SET telegram_id = ? WHERE id = ?', (telegram_id, pendente['usuario_id']))
        c.execute('DELETE FROM vinculos_pendentes WHERE id = ?', (pendente['id'],))
        c.execute('DELETE FROM tentativas_vinculo_telegram WHERE telegram_id = ?', (telegram_id,))
        conn.commit()

        registrar_auditoria('VINCULO_TELEGRAM', 'USUARIO', pendente['usuario_id'],
                           f"Telegram vinculado a {pendente['email']}",
                           usuario=pendente['email'], canal='TELEGRAM')

        return jsonify({'nome': pendente['email'], 'role': pendente['role']}), 200

    except sqlite3.IntegrityError:
        conn.rollback()
        return jsonify({'erro': 'Este Telegram já está vinculado a outra conta'}), 409
    finally:
        conn.close()


@app.route('/api/telegram/token', methods=['POST'])
def token_telegram():
    """Chamado pelo bot antes de repassar qualquer comando: troca um
    telegram_id já vinculado por um JWT de curta duração. O papel vem de
    `usuarios` na hora — nunca fica guardado no vínculo, então uma troca de
    papel no banco vale no próximo comando, sem precisar vincular de novo.
    """
    if not _bot_autorizado():
        return jsonify({'erro': 'Token de serviço inválido'}), 401

    dados = request.json or {}
    telegram_id = dados.get('telegram_id')
    if not telegram_id:
        return jsonify({'erro': 'telegram_id é obrigatório'}), 400

    conn = get_db()
    c = conn.cursor()
    usuario = c.execute('SELECT id, email, role FROM usuarios WHERE telegram_id = ?',
                        (telegram_id,)).fetchone()
    conn.close()

    if not usuario:
        return jsonify({'erro': 'telegram_id não vinculado a nenhuma conta'}), 404

    token = create_access_token(
        identity=usuario['email'],
        additional_claims={'role': usuario['role'], 'canal': 'TELEGRAM'},
        expires_delta=timedelta(minutes=BOT_JWT_EXPIRES_MIN))

    registrar_auditoria('TOKEN_TELEGRAM', 'USUARIO', usuario['id'],
                       f"Token Telegram emitido para {usuario['email']}",
                       usuario=usuario['email'], canal='TELEGRAM')

    return jsonify({'token': token, 'role': usuario['role'], 'usuario': usuario['email']}), 200


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
@requer_roles('coordenador', 'gestor', 'diretor')
def get_estatisticas():
    """Estatísticas de desempenho por máquina, por solicitante e economia semanal.

    Query string:
        origem=REAL|DEMONSTRACAO|TODAS  (padrão TODAS)
    """
    origem, erro = _origem_da_requisicao()
    if erro:
        return erro
    filtro, params = _sql_origem(origem, 'n.origem')

    conn = get_db()
    c = conn.cursor()

    # Operação concluída FORA DO EXPEDIENTE (minutos corridos excedem os de
    # expediente em >= FORA_EXPEDIENTE_LIMIAR_MIN) fica de fora do tempo médio e
    # do desvio: quase sempre é operação deixada em aberto, não produção.
    excluida = (f'(am.tempo_realizado_corrido_min IS NOT NULL AND am.tempo_realizado_min IS NOT NULL '
                f'AND am.tempo_realizado_corrido_min - am.tempo_realizado_min >= {int(FORA_EXPEDIENTE_LIMIAR_MIN)})')
    planejado_sql = '''COALESCE(am.tempo_planejado_min,
                                  (julianday(am.fim_planejado)
                                   - julianday(am.inicio_planejado)) * 24 * 60)'''
    c.execute(f'''SELECT m.nome AS maquina,
                        COUNT(am.id) AS operacoes,
                        SUM(CASE WHEN am.fim_real IS NOT NULL THEN 1 ELSE 0 END)
                            AS operacoes_medidas,
                        SUM(CASE WHEN {excluida} THEN 1 ELSE 0 END)
                            AS operacoes_fora_do_calculo,
                        ROUND(AVG({planejado_sql}), 1)
                            AS tempo_planejado_medio_min,
                        ROUND(AVG(CASE WHEN NOT {excluida} THEN am.tempo_realizado_min END), 1)
                            AS tempo_realizado_medio_min,
                        ROUND(AVG(CASE WHEN NOT {excluida} AND am.tempo_realizado_min IS NOT NULL
                                       THEN am.tempo_realizado_min - {planejado_sql} END), 1)
                            AS desvio_medio_min
                 FROM alocacao_maquinas am
                 JOIN maquinas m ON m.id = am.maquina_id
                 JOIN ordens_servico os ON os.id = am.ordem_servico_id
                 JOIN notas n ON n.id = os.nota_id
                 WHERE {filtro}
                 GROUP BY m.id, m.nome
                 ORDER BY m.nome''', params)
    desempenho_maquinas = [dict(row) for row in c.fetchall()]

    c.execute(f'''SELECT os.numero AS os_numero, am.sequencia, m.nome AS maquina,
                        am.tempo_realizado_min AS expediente_min,
                        am.tempo_realizado_corrido_min AS corrido_min,
                        {planejado_sql} AS planejado_min
                 FROM alocacao_maquinas am
                 JOIN maquinas m ON m.id = am.maquina_id
                 JOIN ordens_servico os ON os.id = am.ordem_servico_id
                 JOIN notas n ON n.id = os.nota_id
                 WHERE {filtro} AND {excluida}
                 ORDER BY os.numero, am.sequencia''', params)
    fora_do_calculo = [dict(row) for row in c.fetchall()]

    c.execute(f'''SELECT COALESCE(n.solicitante, 'NAO_INFORMADO') as operador,
                        COUNT(*) as total_notas,
                        SUM(CASE WHEN n.status != 'PROCESSADA' THEN 1 ELSE 0 END) as pendentes
                 FROM notas n WHERE {filtro} GROUP BY n.solicitante''', params)
    por_operador = [dict(row) for row in c.fetchall()]

    c.execute(f'''SELECT strftime('%W', n.criada_em) as semana, COUNT(*) as notas
                 FROM notas n
                 WHERE n.status = 'PROCESSADA'
                   AND strftime('%Y', n.criada_em) = strftime('%Y', 'now')
                   AND {filtro}
                 GROUP BY semana ORDER BY semana''', params)
    economia_semanal = []
    for row in c.fetchall():
        notas_semana = row['notas']
        valor = round(notas_semana * (TEMPO_MANUAL_MIN - TEMPO_AUTOMATICO_MIN) / 60 * CUSTO_HORA_PRODUCAO, 2)
        economia_semanal.append({
            'semana': row['semana'],
            'notas_processadas': notas_semana,
            'economia_estimada': valor
        })

    origem_dados = _contar_origens(c, 'notas', origem)

    conn.close()

    return jsonify({
        'desempenho_por_maquina': desempenho_maquinas,
        'operacoes_fora_do_calculo': {
            'total': len(fora_do_calculo),
            'limiar_min': FORA_EXPEDIENTE_LIMIAR_MIN,
            'motivo': (f'execução fora do expediente: os minutos corridos passaram os de expediente em pelo menos '
                       f'{FORA_EXPEDIENTE_LIMIAR_MIN} min (hora extra, fim de semana ou operação deixada em aberto)'),
            'operacoes': fora_do_calculo,
        },
        'notas_por_operador': por_operador,
        'economia_semanal': economia_semanal,
        'origem_dados': origem_dados,
        'gerado_em': datetime.now().isoformat()
    })

@app.route('/api/indicadores/manutencao', methods=['GET'])
@requer_roles('coordenador', 'gestor', 'diretor')
def indicadores_manutencao():
    """MTTR por máquina, a partir das intervenções com duração medida.

    Query string:
        origem=REAL|DEMONSTRACAO|TODAS  (padrão TODAS)
        de / ate=YYYY-MM-DD  período das paradas de operação (pelo início da parada)

    O filtro fica no ON do LEFT JOIN: toda máquina continua listada, só as
    intervenções contadas mudam.

    Produção perdida (Etapa 3A): minutos de EXPEDIENTE em que operações ficaram
    interrompidas por máquina quebrada (paradas_operacao). Parada de madrugada,
    fim de semana ou feriado não conta. Parada ainda aberta conta até agora.
    """
    origem, erro = _origem_da_requisicao()
    if erro:
        return erro
    de, erro = _data_param('de')
    if erro:
        return jsonify({'erro': erro}), 400
    ate, erro = _data_param('ate', fim_do_dia=True)
    if erro:
        return jsonify({'erro': erro}), 400
    filtro, params = _sql_origem(origem, 'r.origem')

    conn = get_db()
    c = conn.cursor()

    c.execute(f'''SELECT m.id, m.nome, m.status, m.quebrada_em,
                        COUNT(r.id) AS intervencoes,
                        SUM(CASE WHEN r.tempo_reparo_min IS NOT NULL THEN 1 ELSE 0 END)
                            AS intervencoes_medidas,
                        ROUND(AVG(r.tempo_reparo_min), 1) AS mttr_min
                 FROM maquinas m
                 LEFT JOIN relatorios_manutencao r ON r.maquina_id = m.id AND {filtro}
                 GROUP BY m.id, m.nome, m.status, m.quebrada_em
                 ORDER BY m.nome''', params)

    agora = _agora()
    resultado = []
    for row in c.fetchall():
        item = dict(row)

        # Se está parada agora, há quanto tempo. Dado medido, não estimado.
        parada_ha_min = None
        if item['status'] == 'QUEBRADA' and item['quebrada_em']:
            try:
                parada_ha_min = int(
                    (agora - datetime.fromisoformat(item['quebrada_em'])).total_seconds() / 60
                )
            except (ValueError, TypeError):
                parada_ha_min = None

        item['parada_ha_min'] = parada_ha_min
        resultado.append(item)

    # --- Produção perdida: paradas de operação do período, em minutos de expediente
    onde_p, params_p = [], []
    sql_o, params_o = _sql_origem(origem, 'n.origem')
    if sql_o:
        onde_p.append(sql_o)
        params_p += list(params_o)
    if de:
        onde_p.append('p.inicio >= ?')
        params_p.append(de)
    if ate:
        onde_p.append('p.inicio < ?')
        params_p.append(ate)
    c.execute(f'''SELECT p.alocacao_id, p.maquina_id, p.inicio, p.fim
                  FROM paradas_operacao p
                  JOIN alocacao_maquinas am ON am.id = p.alocacao_id
                  JOIN ordens_servico os ON os.id = am.ordem_servico_id
                  JOIN notas n ON n.id = os.nota_id
                  {('WHERE ' + ' AND '.join(onde_p)) if onde_p else ''}''', params_p)
    perdido, interrompidas, todas_interrompidas = {}, {}, set()
    for pr in c.fetchall():
        ini, fim = _parse_ts(pr['inicio']), _parse_ts(pr['fim'])
        if not ini:
            continue
        perdido[pr['maquina_id']] = perdido.get(pr['maquina_id'], 0) + minutos_de_expediente(ini, fim or agora)
        interrompidas.setdefault(pr['maquina_id'], set()).add(pr['alocacao_id'])
        todas_interrompidas.add(pr['alocacao_id'])
    for item in resultado:
        item['producao_perdida_min'] = perdido.get(item['id'], 0)
        item['operacoes_interrompidas'] = len(interrompidas.get(item['id'], ()))

    total = len(resultado)
    paradas = sum(1 for m in resultado if m['status'] == 'QUEBRADA')

    origem_dados = _contar_origens(c, 'relatorios_manutencao', origem)

    conn.close()
    return jsonify({
        'maquinas': resultado,
        'total': total,
        'paradas': paradas,
        'disponibilidade_percentual': round((total - paradas) / total * 100, 1) if total else None,
        'producao_perdida_min': {
            'total': sum(perdido.values()),
            'por_maquina': [{'maquina_id': m['id'], 'nome': m['nome'], 'minutos': m['producao_perdida_min']}
                            for m in resultado],
        },
        'operacoes_interrompidas': len(todas_interrompidas),
        'periodo': {'de': de[:10] if de else None, 'ate': request.args.get('ate') or None},
        'origem_dados': origem_dados,
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
