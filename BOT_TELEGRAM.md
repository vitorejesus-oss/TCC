# Bot do Telegram — status real

## O que existe e foi testado

- [x] `bot_telegram.py` criado, com os comandos `/start`, `/help`, `/notas`,
      `/urgente`, `/status` (o snippet original parava no meio de `/notas` —
      completei os três comandos e adicionei tratamento de erro em todos).
- [x] Dependências instaladas (`python-telegram-bot==22.8`, `requests==2.34.2`).
- [x] Sintaxe do arquivo validada.
- [x] **A lógica de busca no backend foi testada de verdade, contra a API
      real em produção** (chamei `buscar()` diretamente, sem passar pelo
      Telegram): `/status` retornou saúde + métricas reais, `/notas` listou
      as 4 notas reais existentes, `/urgente` filtrou corretamente 1 OS
      urgente pendente. Os dados batem com o que está realmente no banco em
      produção agora.
- [x] Rodar o script sem `TELEGRAM_TOKEN` falha de forma controlada (mensagem
      clara, sem traceback) em vez de quebrar feio.

## O que NÃO foi testado (e por quê)

- [ ] **A integração real com o Telegram** (`/start` respondendo no chat,
      `app.run_polling()` funcionando de verdade). Isso exige um
      `TELEGRAM_TOKEN` real, que só você pode gerar — eu não tenho como
      criar um bot em sua conta do Telegram. `.env` já tem o campo
      `TELEGRAM_TOKEN=` pronto para receber o valor.

## Como pegar o token e testar

1. No Telegram, abra uma conversa com **@BotFather**.
2. Envie `/newbot`, escolha um nome e um username (precisa terminar em `bot`,
   ex: `automacao_usinagem_bot`).
3. O BotFather devolve um token tipo `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`.
4. Cole em `TCC.VITOR/.env` (e `TCC/.env`) na linha `TELEGRAM_TOKEN=`.
5. Rode:
   ```bash
   pip install -r requirements-bot.txt
   python bot_telegram.py
   ```
6. Procure seu bot pelo username no Telegram e mande `/start`.

## Decisão que tomei sem perguntar (e por quê)

O pedido original mandava instalar as dependências direto — mas coloquei
`python-telegram-bot` e `requests` num `requirements-bot.txt` separado, **não**
no `requirements.txt` do backend. O último deploy no Railway já quebrou uma
vez por causa de uma dependência (`psycopg2-binary`) que não era usada por
nada no código; não fazia sentido arriscar o backend que está funcionando em
produção por uma biblioteca que só o bot usa e que nunca vai rodar no
Railway (o bot é um processo separado, rodado localmente ou em outro lugar).

## Sobre "testar o bot" (Passo 4 do pedido original)

Fiz todo o teste que dava para fazer sem o seu token: a parte que fala com o
backend está provada funcionando com dados reais. A parte que fala com o
Telegram em si não tem como eu verificar sem uma credencial que é seguramente
sua, não minha — mesmo critério que já apliquei para os logins do
Railway/Vercel antes.

---

Gerado em: 15/09/2026
Executor: Claude Code
