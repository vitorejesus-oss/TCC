"""
Bot do Telegram - Sistema de Automação de Usinagem
Consulta o backend real (Railway) e responde comandos no Telegram.
"""

import os
import logging

import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
BACKEND_URL = os.getenv('BACKEND_URL', 'https://automacao-usinagem-backend-production.up.railway.app')
API_URL = f'{BACKEND_URL}/api'
TIMEOUT = 10

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('bot_telegram')


def buscar(endpoint):
    """GET simples no backend. Retorna (dados, erro)."""
    try:
        resp = requests.get(f'{API_URL}/{endpoint}', timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json(), None
    except requests.exceptions.RequestException as e:
        logger.error(f'Erro ao consultar {endpoint}: {e}')
        return None, str(e)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    logger.info(f'[CHAT_ID] /start recebido de chat_id={chat.id} tipo={chat.type} nome={chat.title or chat.username or chat.first_name}')
    await update.message.reply_text(
        "🤖 Grand Prix Automation Bot\n\n"
        "Comandos:\n"
        "/notas - Ver notas recentes\n"
        "/urgente - Ordens de serviço urgentes\n"
        "/status - Status do sistema\n"
        "/help - Ajuda"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def notas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dados, erro = buscar('notas')
    if erro:
        await update.message.reply_text(f"❌ Não consegui falar com o backend: {erro}")
        return

    if not dados:
        await update.message.reply_text("Nenhuma nota registrada ainda.")
        return

    linhas = ["📝 Últimas notas:\n"]
    for nota in dados[:10]:
        prioridade = "🚨" if nota.get('prioridade') == 'URGENTE' else "•"
        linhas.append(
            f"{prioridade} {nota['numero']} — {nota['peca_codigo']} "
            f"(x{nota['quantidade']}) — {nota['status']}"
        )
    if len(dados) > 10:
        linhas.append(f"\n... e mais {len(dados) - 10} nota(s).")

    await update.message.reply_text("\n".join(linhas))


async def urgente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dados, erro = buscar('ordens-servico')
    if erro:
        await update.message.reply_text(f"❌ Não consegui falar com o backend: {erro}")
        return

    urgentes = [os_ for os_ in dados if os_.get('prioridade') == 'URGENTE' and os_.get('status') != 'CONCLUIDA']
    if not urgentes:
        await update.message.reply_text("✅ Nenhuma OS urgente pendente agora.")
        return

    linhas = ["🚨 Ordens de serviço urgentes:\n"]
    for os_ in urgentes[:10]:
        linhas.append(
            f"• {os_['numero']} — {os_.get('peca_nome', os_.get('peca_codigo'))} "
            f"— {os_['status']} — {os_.get('tempo_total', '?')} min"
        )

    await update.message.reply_text("\n".join(linhas))


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    saude, erro_saude = buscar('health')
    if erro_saude:
        await update.message.reply_text(f"🔴 Backend fora do ar: {erro_saude}")
        return

    metricas, erro_metricas = buscar('metricas')

    linhas = [f"🟢 Backend online ({BACKEND_URL})"]
    if metricas:
        linhas.append(f"\n📊 Total de notas: {metricas.get('total_notas', '?')}")
        linhas.append(f"✅ OS concluídas: {metricas.get('os_concluidas', '?')}")
        linhas.append(f"📈 Taxa de aderência: {metricas.get('taxa_aderencia', '?')}%")
        linhas.append(f"💰 Economia/mês: R$ {metricas.get('economia_mensal', '?')}")
    else:
        linhas.append(f"\n⚠️ Métricas indisponíveis: {erro_metricas}")

    await update.message.reply_text("\n".join(linhas))


async def log_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat:
        logger.info(f'[CHAT_ID] Update recebido de chat_id={chat.id} tipo={chat.type} nome={chat.title or chat.username or chat.first_name}')


def main():
    if not TELEGRAM_TOKEN:
        logger.error(
            'TELEGRAM_TOKEN não configurado no .env. '
            'Gere um token com @BotFather no Telegram e defina TELEGRAM_TOKEN antes de rodar este script.'
        )
        raise SystemExit(1)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(MessageHandler(filters.ALL, log_chat_id), group=-1)
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_cmd))
    app.add_handler(CommandHandler('notas', notas))
    app.add_handler(CommandHandler('urgente', urgente))
    app.add_handler(CommandHandler('status', status))

    logger.info(f'Bot iniciado. Backend alvo: {BACKEND_URL}')
    app.run_polling()


if __name__ == '__main__':
    main()
