"""Bot do Telegram - Sistema de Automação de Usinagem
Etapa 1: vínculo de conta, menu e consultas de leitura.

Nenhuma ação que muda dado passa por aqui ainda (isso é Etapa 2 em diante).

O bot NÃO tem rotas de domínio próprias e nunca acessa o banco direto: ele
troca telegram_id (+ o token de serviço deste processo) por um JWT de curta
duração em POST /api/telegram/token, e chama as MESMAS rotas que o site usa
com esse token — a permissão de cada ação continua sendo decidida no
backend, pelo papel de quem está vinculado, nunca por nada que o bot decida
sozinho.

Substitui o bot_telegram.py antigo (guardado em _fases/bot_telegram_antigo.py
só como referência — aquele não tinha autenticação nenhuma, só fazia GET
público no backend). requirements-bot.txt continua servindo sem mudança:
python-telegram-bot já traz InlineKeyboardButton/CallbackQueryHandler.
"""
import logging
import os
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes)

load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
# Só o bot usa esta variável; BACKEND_URL (produção) fica para o resto do projeto.
BOT_BACKEND_URL = os.getenv('BOT_BACKEND_URL', 'http://127.0.0.1:5000')
API_URL = f'{BOT_BACKEND_URL}/api'
BOT_SERVICE_TOKEN = os.getenv('BOT_SERVICE_TOKEN')
BOT_JWT_EXPIRES_MIN = int(os.getenv('BOT_JWT_EXPIRES_MIN', '15'))
TIMEOUT = 10

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('bot_telegram')

# {telegram_id: {'token', 'role', 'email', 'expira_em'}} — em memória, deste
# processo só. Evita pedir um JWT novo a cada mensagem; expira sozinho.
_tokens_cache = {}


# ============================================================================
# CAMADA HTTP (fala com o backend, nunca com o banco)
# ============================================================================

def _cabecalho_servico():
    return {'X-Bot-Token': BOT_SERVICE_TOKEN or ''}


def obter_sessao(telegram_id):
    """(token, role, email) do usuário vinculado a este telegram_id, ou
    (None, None, None) se não estiver vinculado, se o backend recusar, ou se
    a rede falhar. Reaproveita o token em cache enquanto não estiver perto
    de vencer."""
    cache = _tokens_cache.get(telegram_id)
    if cache and cache['expira_em'] > datetime.now() + timedelta(seconds=30):
        return cache['token'], cache['role'], cache['email']

    if not BOT_SERVICE_TOKEN:
        logger.error('BOT_SERVICE_TOKEN não configurado no .env — /api/telegram/token vai recusar tudo.')
        return None, None, None

    try:
        resp = requests.post(f'{API_URL}/telegram/token', headers=_cabecalho_servico(),
                            json={'telegram_id': telegram_id}, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        logger.error(f'Erro ao pedir token (telegram_id={telegram_id}): {e}')
        return None, None, None

    if resp.status_code != 200:
        return None, None, None

    dados = resp.json()
    _tokens_cache[telegram_id] = {
        'token': dados['token'],
        'role': dados['role'],
        'email': dados['usuario'],
        'expira_em': datetime.now() + timedelta(minutes=BOT_JWT_EXPIRES_MIN),
    }
    return dados['token'], dados['role'], dados['usuario']


def chamar_api(telegram_id, metodo, caminho, **kwargs):
    """GET/POST autenticado nas rotas do site, com o JWT deste telegram_id.
    Devolve (dados, None) ou (None, mensagem_de_erro_pro_usuario)."""
    token, _role, _email = obter_sessao(telegram_id)
    if not token:
        return None, 'Você ainda não vinculou sua conta. Use /vincular <código>.'

    headers = kwargs.pop('headers', {})
    headers['Authorization'] = f'Bearer {token}'
    try:
        resp = requests.request(metodo, f'{API_URL}{caminho}', headers=headers, timeout=TIMEOUT, **kwargs)
    except requests.exceptions.RequestException as e:
        return None, f'Não consegui falar com o backend: {e}'

    if resp.status_code == 401:
        _tokens_cache.pop(telegram_id, None)
        return None, 'Sua sessão expirou. Tente de novo.'
    if not resp.ok:
        try:
            return None, resp.json().get('erro', f'Erro {resp.status_code}')
        except ValueError:
            return None, f'Erro {resp.status_code}'
    return resp.json(), None


# ============================================================================
# FORMATAÇÃO (funções puras, sem Telegram nem rede — testáveis isoladas)
# ============================================================================

def texto_maquinas(maquinas):
    if not maquinas:
        return 'Nenhuma máquina cadastrada.'
    agora = datetime.now()
    linhas = ['🏭 Máquinas:']
    for m in maquinas:
        if m.get('status') != 'QUEBRADA':
            linhas.append(f"🟢 {m['nome']}")
            continue
        parada_ha = ''
        if m.get('quebrada_em'):
            try:
                minutos = int((agora - datetime.fromisoformat(m['quebrada_em'])).total_seconds() / 60)
                h, mnt = divmod(max(minutos, 0), 60)
                parada_ha = f' — parada há {h}h{mnt:02d}min' if h else f' — parada há {mnt}min'
            except (ValueError, TypeError):
                pass
        linhas.append(f"🔴 {m['nome']}{parada_ha}")
    return '\n'.join(linhas)


def texto_ordens(ordens, limite=10):
    pendentes = [o for o in ordens if o.get('status') != 'CONCLUIDA']
    if not pendentes:
        return '✅ Nenhuma ordem de serviço pendente agora.'
    linhas = ['📋 Ordens de serviço pendentes:']
    for os_ in pendentes[:limite]:
        marca = '🚨' if os_.get('prioridade') == 'URGENTE' else '•'
        linhas.append(f"{marca} {os_['numero']} — {os_.get('peca_nome', os_.get('peca_codigo', '?'))} "
                     f"— {os_['status']}")
    if len(pendentes) > limite:
        linhas.append(f'\n... e mais {len(pendentes) - limite}.')
    return '\n'.join(linhas)


def texto_fila_producao(dados):
    fila = dados.get('fila_producao', [])
    if not fila:
        return '📋 Fila de produção vazia agora.'
    linhas = ['📋 Fila de produção (todas as OS em planejamento ou usinando):']
    for os_ in fila[:10]:
        marca = '🚨' if os_.get('prioridade') == 'URGENTE' else '•'
        linhas.append(f"{marca} {os_['numero']} — {os_.get('peca_codigo', '?')} — {os_['status']}")
    return '\n'.join(linhas)


def texto_indicadores(indicadores, estatisticas):
    linhas = ['📊 Indicadores:',
             f"Disponibilidade: {indicadores.get('disponibilidade_percentual', '?')}%",
             f"Máquinas paradas: {indicadores.get('paradas', '?')} de {indicadores.get('total', '?')}"]
    for m in indicadores.get('maquinas', []):
        if m.get('mttr_min') is not None:
            linhas.append(f"  MTTR {m['nome']}: {m['mttr_min']} min ({m.get('intervencoes_medidas', 0)} medições)")
    od = estatisticas.get('origem_dados') if estatisticas else None
    if od and od.get('demonstracao'):
        linhas.append(f"\n⚠️ Inclui {od['demonstracao']} registro(s) de demonstração, "
                      f"além de {od['real']} real(is).")
    return '\n'.join(linhas)


TEXTO_AJUDA = (
    '🤖 Sistema de Automação de Usinagem\n\n'
    '/vincular <código> — liga sua conta do site a este chat\n'
    '  (gere o código no site: Acesso > Gerar código de vínculo)\n'
    '/menu — opções disponíveis para o seu papel\n'
    '/maquinas — situação das 8 máquinas\n'
    '/os — ordens de serviço pendentes\n'
    '/desenho <código> — desenho técnico da peça (PDF)\n'
    '/indicadores — disponibilidade e MTTR (coordenador, gestor, diretor)\n'
    '/ajuda — esta mensagem'
)


# ============================================================================
# HANDLERS
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    _token, role, email = obter_sessao(telegram_id)
    if role:
        await update.message.reply_text(f'Olá, {email} ({role})! Use /menu para ver as opções.')
    else:
        await update.message.reply_text(
            '🤖 Sistema de Automação de Usinagem\n\n'
            'Sua conta ainda não está vinculada a este chat.\n'
            'No site, entre e gere um código em: Acesso > Gerar código de vínculo.\n'
            'Depois mande aqui: /vincular 482915'
        )


async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(TEXTO_AJUDA)


async def vincular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text('Uso: /vincular 482915 (código de 6 dígitos gerado no site)')
        return

    codigo = context.args[0].strip()
    telegram_id = update.effective_user.id

    try:
        resp = requests.post(f'{API_URL}/telegram/vincular', headers=_cabecalho_servico(),
                            json={'codigo': codigo, 'telegram_id': telegram_id}, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        await update.message.reply_text(f'Não consegui falar com o backend: {e}')
        return

    if resp.status_code == 200:
        dados = resp.json()
        _tokens_cache.pop(telegram_id, None)  # força buscar um token novo, já com o vínculo
        await update.message.reply_text(
            f"✅ Vinculado! Você é {dados['nome']}, papel: {dados['role']}.\nUse /menu para ver as opções.")
        return

    if resp.status_code == 429:
        await update.message.reply_text(
            '⛔ Muitas tentativas erradas. Gere um novo código no site e tente de novo mais tarde.')
        return

    try:
        erro = resp.json().get('erro', 'código inválido')
    except ValueError:
        erro = 'código inválido'
    await update.message.reply_text(f'❌ {erro}. Confira o código e tente de novo.')


def _requer_vinculo(telegram_id):
    """(role, email) se vinculado, senão (None, mensagem_para_o_usuario)."""
    _token, role, email = obter_sessao(telegram_id)
    if not role:
        return None, ('Você ainda não vinculou sua conta.\n'
                      'No site: Acesso > Gerar código de vínculo. Depois:\n/vincular 482915')
    return role, email


def _botoes_menu(role):
    linhas = [[InlineKeyboardButton('🏭 Máquinas', callback_data='maquinas')],
             [InlineKeyboardButton('📋 Ordens de serviço', callback_data='os')],
             [InlineKeyboardButton('📋 Fila de produção', callback_data='fila')]]
    if role in ('coordenador', 'gestor', 'diretor'):
        linhas.append([InlineKeyboardButton('📊 Indicadores', callback_data='indicadores')])
    linhas.append([InlineKeyboardButton('❓ Ajuda', callback_data='ajuda')])
    return InlineKeyboardMarkup(linhas)


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    role, resultado = _requer_vinculo(telegram_id)
    if not role:
        await update.message.reply_text(resultado)
        return
    await update.message.reply_text(f'Menu ({role}) — {resultado}:', reply_markup=_botoes_menu(role))


async def maquinas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    dados, erro = chamar_api(telegram_id, 'GET', '/maquinas')
    await update.message.reply_text(erro or texto_maquinas(dados))


async def ordens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    dados, erro = chamar_api(telegram_id, 'GET', '/ordens-servico')
    await update.message.reply_text(erro or texto_ordens(dados))


async def fila(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    dados, erro = chamar_api(telegram_id, 'GET', '/painel/operador')
    await update.message.reply_text(erro or texto_fila_producao(dados))


async def indicadores(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    role, resultado = _requer_vinculo(telegram_id)
    if not role:
        await update.message.reply_text(resultado)
        return
    if role not in ('coordenador', 'gestor', 'diretor'):
        # /api/indicadores/manutencao não é uma rota que precise de JWT no
        # backend hoje (é pública, igual /api/maquinas) — o bot é quem
        # aplica a tabela de permissões da seção 2 do brief aqui, do mesmo
        # jeito que o site esconde o que o papel não usa.
        await update.message.reply_text('Indicadores é só para coordenador, gestor e diretor.')
        return
    indic, erro = chamar_api(telegram_id, 'GET', '/indicadores/manutencao')
    if erro:
        await update.message.reply_text(erro)
        return
    estat, _erro_estat = chamar_api(telegram_id, 'GET', '/estatisticas')
    await update.message.reply_text(texto_indicadores(indic, estat))


async def desenho(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text('Uso: /desenho 40-091799')
        return
    codigo = context.args[0].strip()
    telegram_id = update.effective_user.id
    token, _role, _email = obter_sessao(telegram_id)
    if not token:
        await update.message.reply_text('Você ainda não vinculou sua conta. Use /vincular <código>.')
        return

    try:
        resp = requests.get(f'{API_URL}/pecas/{codigo}/desenho',
                           headers={'Authorization': f'Bearer {token}'}, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        await update.message.reply_text(f'Não consegui falar com o backend: {e}')
        return

    if resp.status_code == 200:
        await update.message.reply_document(document=resp.content, filename=f'{codigo}.pdf')
    elif resp.status_code == 404:
        await update.message.reply_text(f'Não achei desenho técnico para a peça {codigo}.')
    else:
        await update.message.reply_text(f'Erro {resp.status_code} ao buscar o desenho.')


ACOES_MENU = {
    'maquinas': lambda telegram_id: chamar_api(telegram_id, 'GET', '/maquinas'),
    'os': lambda telegram_id: chamar_api(telegram_id, 'GET', '/ordens-servico'),
    'fila': lambda telegram_id: chamar_api(telegram_id, 'GET', '/painel/operador'),
}
FORMATADORES_MENU = {
    'maquinas': texto_maquinas,
    'os': texto_ordens,
    'fila': texto_fila_producao,
}


async def botao_pressionado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    acao = query.data
    telegram_id = update.effective_user.id

    if acao == 'ajuda':
        await query.edit_message_text(TEXTO_AJUDA)
        return

    if acao == 'indicadores':
        role, resultado = _requer_vinculo(telegram_id)
        if not role:
            await query.edit_message_text(resultado)
            return
        if role not in ('coordenador', 'gestor', 'diretor'):
            await query.edit_message_text('Indicadores é só para coordenador, gestor e diretor.')
            return
        indic, erro = chamar_api(telegram_id, 'GET', '/indicadores/manutencao')
        if erro:
            await query.edit_message_text(erro)
            return
        estat, _erro_estat = chamar_api(telegram_id, 'GET', '/estatisticas')
        await query.edit_message_text(texto_indicadores(indic, estat))
        return

    if acao in ACOES_MENU:
        dados, erro = ACOES_MENU[acao](telegram_id)
        await query.edit_message_text(erro or FORMATADORES_MENU[acao](dados))
        return

    await query.edit_message_text('Opção não reconhecida.')


def main():
    if not TELEGRAM_TOKEN:
        logger.error('TELEGRAM_TOKEN não configurado no .env.')
        raise SystemExit(1)
    if not BOT_SERVICE_TOKEN:
        logger.error(
            'BOT_SERVICE_TOKEN não configurado no .env — /vincular e as consultas vão falhar. '
            'Gere um com: python -c "import secrets; print(secrets.token_urlsafe(32))" '
            'e coloque o MESMO valor no .env do backend e no deste bot.'
        )
        raise SystemExit(1)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler(['ajuda', 'help'], ajuda))
    app.add_handler(CommandHandler('vincular', vincular))
    app.add_handler(CommandHandler('menu', menu))
    app.add_handler(CommandHandler('maquinas', maquinas))
    app.add_handler(CommandHandler('os', ordens))
    app.add_handler(CommandHandler('minhas', fila))
    app.add_handler(CommandHandler('indicadores', indicadores))
    app.add_handler(CommandHandler('desenho', desenho))
    app.add_handler(CallbackQueryHandler(botao_pressionado))

    logger.info(f'Bot iniciado (Etapa 1). Backend alvo: {BOT_BACKEND_URL}')
    app.run_polling()


if __name__ == '__main__':
    main()
