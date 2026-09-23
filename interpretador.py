"""Identificação de máquina por texto livre, para o bot do Telegram.

Sem IA (seção 7 do brief): com 8 máquinas, um dicionário de palavras-chave
acerta sempre. Se o texto bater com mais de uma máquina, ou com nenhuma,
`interpretar_maquina` devolve None — quem chama mostra os botões. Nunca
adivinha.

Isto NÃO é o `interpretar(texto)` genérico da seção 13 do brief (aquele é um
despacho mais amplo, para usos futuros como resumir relato longo — fora do
escopo da Etapa 1). Esta função resolve só a identificação de máquina, que é
o único uso da Etapa 1. Se um dia entrar um modelo de linguagem, é esta
função — e só ela — que precisa trocar de implementação; quem chama continua
recebendo um nome de máquina ou None.
"""
import unicodedata

# Palavras-chave em minúsculas e sem acento (a normalização cuida do resto)
# apontando para o nome EXATO da máquina em maquinas.nome. Ajustar aqui se o
# parque mudar — é a única coisa que precisa mudar.
PALAVRAS_CHAVE = {
    'Torno Horizontal': ['torno horizontal', 'centur', 'romi centur'],
    'Torno Vertical': ['torno vertical', 'vtl', 'clever'],
    'Fresadora Universal': ['fresa', 'fresadora', 'romi u30'],
    'Mandrilhadora': ['mandrilhadora', 'mandril', 'varnsdorf'],
    'Furadeira Radial': ['furadeira', 'radial', 'gr-40', 'gr40'],
    'Serra de Fita': ['serra', 'serra de fita', 'sf', 'franho'],
    'Torno CNC Cilindros': ['torno cnc', 'cnc cilindros', 'herkules'],
    'Retificadora Cilíndrica': ['retifica', 'retificadora', 'rcg'],
}


def _normalizar(texto):
    """minúsculas, sem acento, espaços simples — pra 'Retífica', 'RETIFICA'
    e 'retifica' caírem na mesma comparação."""
    sem_acento = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('ascii')
    return ' '.join(sem_acento.lower().split())


def interpretar_maquina(texto, nomes_disponiveis=None):
    """Acha UMA máquina no texto livre, ou None se for ambíguo ou não bater
    com nada.

    `nomes_disponiveis` (opcional) restringe a busca às máquinas informadas
    — por exemplo, só as que existem hoje no banco. Sem isso, considera
    todo `PALAVRAS_CHAVE`.
    """
    texto_norm = _normalizar(texto or '')
    if not texto_norm:
        return None

    candidatos = PALAVRAS_CHAVE.keys() if nomes_disponiveis is None else nomes_disponiveis
    encontrados = {
        nome for nome in candidatos
        if any(_normalizar(p) in texto_norm for p in PALAVRAS_CHAVE.get(nome, []))
    }

    return next(iter(encontrados)) if len(encontrados) == 1 else None
