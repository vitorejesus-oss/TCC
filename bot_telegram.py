"""Bot do Telegram - Sistema de Automação de Usinagem
Etapa 1: vínculo de conta, menu e consultas de leitura.
Etapa 2: fila de produção e execução de operações (iniciar/concluir), sempre
com confirmação antes da ação, pelas rotas /api/alocacoes/<id>/iniciar e
/concluir — a mesma execução que o site faz, com o JWT do usuário.

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
                          ContextTypes, MessageHandler, filters)

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


PAPEIS_EXECUTAM = ('operador', 'coordenador')  # os mesmos que o backend aceita em /alocacoes/*
LIMITE_FILA = 10  # o Telegram limita botões por mensagem; a fila vem ordenada por urgência


def operacoes_da_fila(ordem, operacoes):
    """Operações de uma OS que aparecem na fila de produção do bot.

    `ordem` é uma linha de GET /ordens-servico; `operacoes` vem de
    GET /ordens-servico/<id>/operacoes. Entram as EXECUTANDO e as prontas
    para iniciar (LIBERADO: o backend marca assim a 1ª operação de toda OS
    nova, cada seguinte quando a anterior termina e a interrompida quando a
    máquina é consertada) e as INTERROMPIDAS (máquina parada)."""
    itens = []
    for op in operacoes:
        if op['status'] not in ('EXECUTANDO', 'LIBERADO', 'INTERROMPIDA'):
            continue
        itens.append({
            'alocacao_id': op['id'], 'os_id': ordem['id'], 'os_numero': ordem['numero'],
            'prioridade': ordem.get('prioridade'), 'peca_codigo': ordem.get('peca_codigo'),
            'sequencia': op['sequencia'], 'total_operacoes': len(operacoes),
            'status': op['status'], 'maquina': op['maquina_nome'],
            'maquina_parada': op.get('maquina_status') == 'QUEBRADA',
            'planejado_min': op.get('tempo_planejado_min'),
            # LIBERADO com inicio_real = interrompida por quebra e já consertada: é RETOMADA
            'retomada': op['status'] == 'LIBERADO' and bool(op.get('inicio_real')),
            'acumulado_min': op.get('tempo_acumulado_min') or 0,
        })
    return itens


def texto_duracao(minutos):
    if minutos is None:
        return '?'
    h, m = divmod(max(int(minutos), 0), 60)
    return f'{h}h{m:02d}min' if h else f'{m}min'


def texto_fila_operacoes(itens, pode_executar=True):
    if not itens:
        return '📋 Fila de produção vazia: nenhuma operação liberada ou em execução agora.'
    linhas = ['📋 Fila de produção:']
    for it in itens[:LIMITE_FILA]:
        marca = '🚨' if it.get('prioridade') == 'URGENTE' else '•'
        if it['status'] == 'INTERROMPIDA':
            situacao = f"⏸️ INTERROMPIDA ({texto_duracao(it.get('acumulado_min'))} já feitos)"
        elif it['status'] == 'EXECUTANDO':
            situacao = '⚙️ EXECUTANDO'
        elif it.get('retomada'):
            situacao = f"🟡 LIBERADA para retomar ({texto_duracao(it.get('acumulado_min'))} já feitos)"
        else:
            situacao = '🟡 LIBERADA'
        # INTERROMPIDA já significa máquina parada; nos demais casos só avisa se estiver parada
        parada = ' 🔴 máquina parada' if it.get('maquina_parada') or it['status'] == 'INTERROMPIDA' else ''
        linhas.append(f"{marca} {it['os_numero']} — OP {it['sequencia']}/{it['total_operacoes']} — "
                      f"{it['maquina']} — {texto_duracao(it.get('planejado_min'))} estimados — {situacao}{parada}")
    if len(itens) > LIMITE_FILA:
        linhas.append(f'\n... e mais {len(itens) - LIMITE_FILA}.')
    if not pode_executar:
        linhas.append('\n👁️ Só operador e coordenador iniciam ou concluem operações.')
    return '\n'.join(linhas)


AVISO_PROVISORIO = '⚠️ Documento provisório: não é o desenho técnico oficial (ainda não cadastrado).'


def botao_desenho(codigo, provisorio=False):
    """📄 Desenho da peça, ou None se o código não cabe no callback_data (64 bytes).
    Para PDF provisório (placeholder) o rótulo avisa e o callback é dp:, que
    faz o envio vir com a legenda de aviso."""
    dados = f"{'dp' if provisorio else 'dw'}:{codigo}"
    if not codigo or len(dados.encode()) > 64:
        return None
    return InlineKeyboardButton('📄 Desenho (provisório)' if provisorio else '📄 Desenho', callback_data=dados)


def teclado_fila(itens, role, com_desenho=frozenset(), provisorios=frozenset()):
    """Um botão por operação (Iniciar ou Concluir), só para quem executa, e o
    📄 Desenho da peça ao lado quando ela tem PDF cadastrado (`com_desenho` =
    códigos de peça com PDF; `provisorios` = os que são só placeholder)."""
    if role not in PAPEIS_EXECUTAM:
        return None
    linhas = []
    for it in itens[:LIMITE_FILA]:
        botao = botao_desenho(it.get('peca_codigo'), it.get('peca_codigo') in provisorios)
        linha = []
        # Operação interrompida: sem Iniciar/Retomar enquanto a máquina não for consertada
        if it['status'] != 'INTERROMPIDA':
            acao, rotulo = ('c', '✅ Concluir') if it['status'] == 'EXECUTANDO' else \
                ('i', '▶️ Retomar' if it.get('retomada') else '▶️ Iniciar')
            linha.append(InlineKeyboardButton(f"{rotulo} {it['os_numero']} · OP {it['sequencia']}",
                                              callback_data=f"op:{acao}:{it['alocacao_id']}:{it['os_id']}"))
        if it.get('peca_codigo') in com_desenho and botao:
            linha.append(botao)
        if linha:
            linhas.append(linha)
    return InlineKeyboardMarkup(linhas) if linhas else None


def texto_ficha_curta(peca):
    """Material, dimensões e aplicação da peça, só o que existir. '' se nada."""
    ficha = (peca or {}).get('ficha') or {}
    linhas = [f"{rotulo}: {ficha[campo]}" for campo, rotulo in
              (("material", "Material"), ("dimensoes", "Dimensões"), ("aplicacao", "Aplicação"))
              if ficha.get(campo)]
    return '\n'.join(linhas)


def texto_atraso(minutos):
    """'há 3d 5h', 'há 2h05min' ou 'há 40min' (dias só a partir de 24h)."""
    if minutos is None:
        return 'há ?'
    d, resto = divmod(max(int(minutos), 0), 1440)
    if d:
        return f'há {d}d {resto // 60}h'
    return 'há ' + texto_duracao(resto)


def texto_busca_os(dados):
    """Resposta paginada de GET /ordens-servico?q=... -> texto para o chat."""
    itens = dados.get('itens', [])
    if not itens:
        return '🔎 Nenhuma OS encontrada.'
    situacao = {'PLANEJAMENTO': 'Planejamento', 'USINANDO': 'Em usinagem', 'CONCLUIDA': 'Concluída'}
    linhas = [f"🔎 {dados.get('total', len(itens))} OS encontrada(s):"]
    for o in itens:
        marca = '🚨 ' if o.get('prioridade') == 'URGENTE' else ''
        linhas.append(f"\n{marca}{o['numero']} — {o.get('peca_nome') or o.get('peca_codigo', '?')}")
        partes = [situacao.get(o['status'], o['status'])]
        if o.get('maquina_atual'):
            partes.append(f"na {o['maquina_atual']}")
        partes.append(f"planejado {texto_duracao(o.get('planejado_min'))}"
                      + (f" × realizado {texto_duracao(o['realizado_min'])}" if o.get('realizado_min') is not None else ''))
        linhas.append('   ' + ' · '.join(partes))
        if o.get('em_atraso'):
            linhas.append(f"   ⏰ em atraso {texto_atraso(o.get('atraso_min'))}")
    if dados.get('total', 0) > len(itens):
        linhas.append(f"\n... mostrando {len(itens)} de {dados['total']}. Refine a busca.")
    return '\n'.join(linhas)


def traduzir_erro_acao(erro):
    """Mensagem do backend -> texto legível para quem está no chat."""
    if 'Operação interrompida' in erro:
        return (f'⏸️ {erro}. A operação volta a ficar disponível para retomar assim que o '
                'coordenador registrar o conserto.')
    if 'está parada' in erro:
        return (f'🔴 {erro}. Não dá para iniciar uma operação nela até o conserto ser registrado. '
                'Fale com a manutenção e tente de novo depois.')
    if 'Permissão negada' in erro:
        return '⛔ Seu papel não permite iniciar ou concluir operações.'
    if 'ainda não foi retomada' in erro:
        return 'ℹ️ Essa operação foi interrompida e ainda não foi retomada. Retome-a em /fila antes de concluir.'
    if 'operação anterior' in erro:
        return f'⏳ {erro}. Veja a fila atualizada com /fila.'
    if 'já iniciada' in erro:
        return 'ℹ️ Essa operação já foi iniciada (talvez por outra pessoa). Veja a fila atualizada com /fila.'
    if 'já concluída' in erro:
        return 'ℹ️ Essa operação já foi concluída. Veja a fila atualizada com /fila.'
    if 'ainda não foi iniciada' in erro:
        return 'ℹ️ Essa operação ainda não foi iniciada, então não dá para concluir. Veja /fila.'
    if 'não encontrada' in erro:
        return 'ℹ️ Não encontrei essa operação. Veja a fila atualizada com /fila.'
    return f'❌ {erro}'


def texto_conclusao(resultado, operacoes, alocacao_id):
    """Resposta de POST /alocacoes/<id>/concluir + GET .../operacoes -> texto.

    Planejado e a operação liberada em seguida não vêm na resposta de
    concluir; saem da lista de operações da mesma OS."""
    atual = next((o for o in operacoes if o['id'] == alocacao_id), None)
    seq = atual['sequencia'] if atual else None
    realizado = resultado.get('tempo_realizado_min')
    planejado = atual.get('tempo_planejado_min') if atual else None

    linhas = [f"✅ OP {seq if seq is not None else '?'} concluída."]
    linhas.append(f'⏱️ Realizado: {texto_duracao(realizado)} | Planejado: {texto_duracao(planejado)}')
    if realizado is not None and planejado is not None:
        desvio = realizado - planejado
        if desvio > 0:
            linhas.append(f'   ({texto_duracao(desvio)} acima do planejado)')
        elif desvio < 0:
            linhas.append(f'   ({texto_duracao(-desvio)} abaixo do planejado)')
        else:
            linhas.append('   (exatamente o planejado)')

    if resultado.get('fora_do_expediente'):
        linhas.append(f"⚠️ Execução fora do expediente: {texto_duracao(resultado.get('tempo_realizado_corrido_min'))} "
                      f"corridos para {texto_duracao(realizado)} de expediente.")
    if resultado.get('os_concluida'):
        linhas.append('🏁 Era a última operação: a OS está concluída.')
    else:
        prox = next((o for o in operacoes if seq is not None and o['sequencia'] == seq + 1), None)
        if prox:
            linhas.append(f"➡️ Liberada em seguida: OP {prox['sequencia']} na {prox['maquina_nome']} "
                          f"({texto_duracao(prox.get('tempo_planejado_min'))} estimados).")
    return '\n'.join(linhas)


def texto_indicadores(indicadores, estatisticas):
    linhas = ['📊 Indicadores:',
             f"Disponibilidade: {indicadores.get('disponibilidade_percentual', '?')}%",
             f"Máquinas paradas: {indicadores.get('paradas', '?')} de {indicadores.get('total', '?')}"]
    for m in indicadores.get('maquinas', []):
        if m.get('mttr_min') is not None:
            linhas.append(f"  MTTR {m['nome']}: {m['mttr_min']} min ({m.get('intervencoes_medidas', 0)} medições)")
    perdida = indicadores.get('producao_perdida_min')
    if perdida and (perdida.get('total') or indicadores.get('operacoes_interrompidas')):
        linhas.append(f"🏭 Produção perdida por máquina parada: {texto_duracao(perdida.get('total'))} de expediente, "
                      f"{indicadores.get('operacoes_interrompidas', 0)} operação(ões) interrompida(s)")
        for m in perdida.get('por_maquina', []):
            if m.get('minutos'):
                linhas.append(f"  {m['nome']}: {texto_duracao(m['minutos'])}")
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
    '/os — ordens de serviço pendentes; /os <número> busca uma OS\n'
    '/fila — fila de produção: iniciar e concluir operações (operador e coordenador)\n'
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
    if context.args:   # /os <número da OS, da nota, peça ou solicitante>: mesma busca do site
        dados, erro = chamar_api(telegram_id, 'GET', '/ordens-servico',
                                 params={'q': ' '.join(context.args), 'pagina': 1, 'por_pagina': 5,
                                         'ordenar': 'criada_em', 'direcao': 'desc'})
        await update.message.reply_text(erro or texto_busca_os(dados))
        return
    dados, erro = chamar_api(telegram_id, 'GET', '/ordens-servico')
    await update.message.reply_text(erro or texto_ordens(dados))


def montar_fila(telegram_id):
    """(itens, erro): operações liberadas/executando de todas as OS abertas.
    Só rotas existentes: lista de OS + operações de cada uma (a lista de OS
    abertas é pequena; a ordem de urgência já vem do backend)."""
    ordens_, erro = chamar_api(telegram_id, 'GET', '/ordens-servico')
    if erro:
        return None, erro
    itens = []
    for ordem in ordens_:
        if ordem.get('status') == 'CONCLUIDA':
            continue
        ops, erro = chamar_api(telegram_id, 'GET', f"/ordens-servico/{ordem['id']}/operacoes")
        if erro:
            return None, erro
        itens.extend(operacoes_da_fila(ordem, ops))
    return itens, None


def _fila_pronta(telegram_id):
    """(texto, teclado) da fila para este usuário; o texto já é o erro se falhar."""
    _token, role, _email = obter_sessao(telegram_id)
    itens, erro = montar_fila(telegram_id)
    if erro:
        return erro, None
    pecas, _erro_pecas = chamar_api(telegram_id, 'GET', '/pecas')   # sem ela, só some o botão 📄
    com_desenho = frozenset(p['codigo'] for p in (pecas or []) if p.get('tem_desenho'))
    provisorios = frozenset(p['codigo'] for p in (pecas or []) if p.get('desenho_provisorio'))
    return (texto_fila_operacoes(itens, pode_executar=role in PAPEIS_EXECUTAM),
            teclado_fila(itens, role, com_desenho, provisorios))


async def fila(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop('obs_pendente', None)
    texto, teclado = _fila_pronta(update.effective_user.id)
    await update.message.reply_text(texto, reply_markup=teclado)


# --- Ações sobre operações (Etapa 2) -----------------------------------------
# Fluxo: botão -> [Confirmar]/[Cancelar] -> (só concluir) observação -> ação.
# callback_data: op:<acao>:<alocacao_id>:<os_id>, com acao = i/ic (iniciar,
# confirmar), c/cc (concluir, confirmar), cs (concluir sem observação), x.

OBS_VALIDADE_MIN = 10
OBS_MAX_CHARS = 500


def _teclado_confirmar(acao_confirmar, aid, os_id, extra=None):
    """[Confirmar][Cancelar], mais uma linha opcional de botões (ex.: 📄 Desenho)."""
    linhas = [[
        InlineKeyboardButton('✅ Confirmar', callback_data=f'op:{acao_confirmar}:{aid}:{os_id}'),
        InlineKeyboardButton('❌ Cancelar', callback_data='op:x:0:0'),
    ]]
    if extra:
        linhas.append(extra)
    return InlineKeyboardMarkup(linhas)


def _buscar_operacao(telegram_id, os_id, aid):
    """(operacao, todas, erro) com o estado ATUAL da operação no backend."""
    ops, erro = chamar_api(telegram_id, 'GET', f'/ordens-servico/{os_id}/operacoes')
    if erro:
        return None, None, erro
    op = next((o for o in ops if o['id'] == aid), None)
    if not op:
        return None, ops, 'Operação não encontrada'
    return op, ops, None


def _peca_da_os(telegram_id, os_id):
    """A peça (com ficha e tem_desenho, de GET /pecas) da OS, ou None."""
    os_, erro = chamar_api(telegram_id, 'GET', f'/ordens-servico/{os_id}')
    if erro:
        return None
    pecas, erro = chamar_api(telegram_id, 'GET', '/pecas')
    if erro:
        return None
    return next((p for p in pecas if p['codigo'] == os_.get('peca_codigo')), None)


async def _executar_iniciar(query, telegram_id, aid, os_id):
    dados, erro = chamar_api(telegram_id, 'POST', f'/alocacoes/{aid}/iniciar')
    if erro:
        await query.edit_message_text(traduzir_erro_acao(erro))
        return
    hora = (dados.get('retomada_em') or dados.get('inicio_real') or '')[11:16]
    verbo = 'retomada' if dados.get('retomada') else 'iniciada'
    await query.edit_message_text(f"▶️ Operação {verbo}{f' às {hora}' if hora else ''}. Bom trabalho!\n"
                                  'Quando terminar, use /fila e toque em Concluir.')


async def _executar_concluir(responder, telegram_id, aid, os_id, observacao):
    """`responder` = função async (texto) que edita ou envia a mensagem."""
    dados, erro = chamar_api(telegram_id, 'POST', f'/alocacoes/{aid}/concluir',
                             json={'observacao': observacao or ''})
    if erro:
        await responder(traduzir_erro_acao(erro))
        return
    ops, erro_ops = chamar_api(telegram_id, 'GET', f'/ordens-servico/{os_id}/operacoes')
    await responder(texto_conclusao(dados, ops or [], aid))


async def acao_operacao(update: Update, context: ContextTypes.DEFAULT_TYPE, query, dados_cb):
    telegram_id = update.effective_user.id
    try:
        _, acao, aid, os_id = dados_cb.split(':')
        aid, os_id = int(aid), int(os_id)
    except ValueError:
        await query.edit_message_text('Opção não reconhecida.')
        return

    if acao == 'x':
        context.user_data.pop('obs_pendente', None)
        await query.edit_message_text('Cancelado. Nada foi alterado. /fila mostra a fila de novo.')
        return

    role, resultado = _requer_vinculo(telegram_id)
    if not role:
        await query.edit_message_text(resultado)
        return
    if role not in PAPEIS_EXECUTAM:
        await query.edit_message_text(traduzir_erro_acao('Permissão negada para este papel'))
        return

    if acao in ('i', 'c'):  # pede confirmação, já com o estado atual da operação
        op, _ops, erro = _buscar_operacao(telegram_id, os_id, aid)
        if erro:
            await query.edit_message_text(traduzir_erro_acao(erro))
            return
        if acao == 'i' and op['status'] == 'EXECUTANDO':
            await query.edit_message_text(traduzir_erro_acao('Operação já iniciada'))
            return
        if acao == 'i' and op['status'] == 'INTERROMPIDA':
            await query.edit_message_text(traduzir_erro_acao(
                f"Operação interrompida: a máquina {op['maquina_nome']} está parada"))
            return
        if acao == 'c' and op['status'] != 'EXECUTANDO':
            motivo = {'CONCLUIDO': 'Operação já concluída',
                      'INTERROMPIDA': f"Operação interrompida: a máquina {op['maquina_nome']} está parada",
                      'LIBERADO': ('Operação ainda não foi retomada' if op.get('inicio_real')
                                   else 'Operação ainda não foi iniciada')}.get(op['status'], 'Operação ainda não foi iniciada')
            await query.edit_message_text(traduzir_erro_acao(motivo))
            return
        retomada = acao == 'i' and bool(op.get('inicio_real'))
        verbo = 'Retomar' if retomada else ('Iniciar' if acao == 'i' else 'Concluir')
        texto = (f"{verbo} a OP {op['sequencia']} na {op['maquina_nome']}?\n"
                 f"Estimado: {texto_duracao(op.get('tempo_planejado_min'))}")
        if retomada:
            texto += f"\nJá usinado antes da parada: {texto_duracao(op.get('tempo_acumulado_min'))}"
        extra = None
        if acao == 'i':
            peca = _peca_da_os(telegram_id, os_id)
            ficha = texto_ficha_curta(peca)
            if ficha:
                texto += f"\n\n📐 {peca['nome']}\n{ficha}"
            if peca and peca.get('tem_desenho'):
                provisorio = bool(peca.get('desenho_provisorio'))
                if botao_desenho(peca['codigo'], provisorio):
                    extra = [botao_desenho(peca['codigo'], provisorio)]
                if provisorio:
                    texto += f"\n\n{AVISO_PROVISORIO}"
        teclado = _teclado_confirmar('ic' if acao == 'i' else 'cc', aid, os_id, extra)
        await query.edit_message_text(texto, reply_markup=teclado)
        return

    if acao == 'ic':
        await _executar_iniciar(query, telegram_id, aid, os_id)
        return

    if acao == 'cc':  # confirmado: agora pergunta a observação antes de concluir
        context.user_data['obs_pendente'] = {'aid': aid, 'os_id': os_id, 'ate': datetime.now() + timedelta(minutes=OBS_VALIDADE_MIN)}
        await query.edit_message_text(
            '📝 Quer registrar alguma observação sobre esta operação?\n'
            'Escreva a mensagem agora, ou toque em [Sem observação].',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton('Sem observação', callback_data=f'op:cs:{aid}:{os_id}'),
                InlineKeyboardButton('❌ Cancelar', callback_data='op:x:0:0'),
            ]]))
        return

    if acao == 'cs':
        context.user_data.pop('obs_pendente', None)
        await _executar_concluir(query.edit_message_text, telegram_id, aid, os_id, '')
        return

    await query.edit_message_text('Opção não reconhecida.')


async def texto_livre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Texto solto: só faz algo quando há uma observação sendo esperada."""
    pendente = context.user_data.get('obs_pendente')
    if not pendente or pendente['ate'] < datetime.now():
        context.user_data.pop('obs_pendente', None)
        await update.message.reply_text('Não entendi. Use /menu para ver as opções.')
        return
    context.user_data.pop('obs_pendente', None)
    observacao = update.message.text.strip()[:OBS_MAX_CHARS]
    await _executar_concluir(update.message.reply_text, update.effective_user.id,
                             pendente['aid'], pendente['os_id'], observacao)


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
    pecas, _erro = chamar_api(update.effective_user.id, 'GET', '/pecas')
    provisorio = any(p['codigo'] == codigo and p.get('desenho_provisorio') for p in (pecas or []))
    await enviar_desenho(update.message, update.effective_user.id, codigo, provisorio)


async def enviar_desenho(mensagem, telegram_id, codigo, provisorio=False):
    """Busca o PDF da peça pela API e o envia no chat de `mensagem`, com a
    legenda de aviso quando for só um documento provisório."""
    token, _role, _email = obter_sessao(telegram_id)
    if not token:
        await mensagem.reply_text('Você ainda não vinculou sua conta. Use /vincular <código>.')
        return

    try:
        resp = requests.get(f'{API_URL}/pecas/{codigo}/desenho',
                           headers={'Authorization': f'Bearer {token}'}, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        await mensagem.reply_text(f'Não consegui falar com o backend: {e}')
        return

    if resp.status_code == 200:
        await mensagem.reply_document(document=resp.content, filename=f'{codigo}.pdf',
                                      caption=AVISO_PROVISORIO if provisorio else None)
    elif resp.status_code == 404:
        await mensagem.reply_text(f'Não achei desenho técnico para a peça {codigo}.')
    else:
        await mensagem.reply_text(f'Erro {resp.status_code} ao buscar o desenho.')


ACOES_MENU = {
    'maquinas': lambda telegram_id: chamar_api(telegram_id, 'GET', '/maquinas'),
    'os': lambda telegram_id: chamar_api(telegram_id, 'GET', '/ordens-servico'),
}
FORMATADORES_MENU = {
    'maquinas': texto_maquinas,
    'os': texto_ordens,
}


async def botao_pressionado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    acao = query.data
    telegram_id = update.effective_user.id

    if acao == 'ajuda':
        await query.edit_message_text(TEXTO_AJUDA)
        return

    if acao.startswith('op:'):
        await acao_operacao(update, context, query, acao)
        return

    if acao.startswith(('dw:', 'dp:')):   # 📄 Desenho: manda o PDF sem o operador digitar o código
        await enviar_desenho(query.message, telegram_id, acao[3:], provisorio=acao.startswith('dp:'))
        return

    if acao == 'fila':
        context.user_data.pop('obs_pendente', None)
        texto, teclado = _fila_pronta(telegram_id)
        await query.edit_message_text(texto, reply_markup=teclado)
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
    app.add_handler(CommandHandler(['fila', 'minhas'], fila))
    app.add_handler(CommandHandler('indicadores', indicadores))
    app.add_handler(CommandHandler('desenho', desenho))
    app.add_handler(CallbackQueryHandler(botao_pressionado))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, texto_livre))

    logger.info(f'Bot iniciado (Etapa 2). Backend alvo: {BOT_BACKEND_URL}')
    app.run_polling()


if __name__ == '__main__':
    main()
