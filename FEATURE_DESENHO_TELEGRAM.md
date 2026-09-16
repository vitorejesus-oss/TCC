# Feature 1: Desenho técnico no Telegram — status real

## O que foi implementado

O snippet que veio no pedido era escrito para um backend diferente do real
(usa `db.session`, classes `Nota`/`Peça`, `@token_required`, endpoint
`/api/notas/criar`) — nada disso existe em `app.py` (que usa `sqlite3` puro
e o endpoint real é `POST /api/notas`). Implementei a mesma ideia adaptada
ao código de verdade:

- `enviar_nota_telegram()` em [app.py](app.py), chamada dentro de
  `criar_nota()` logo depois que `AutomacaoUsinagem.processar_nota()`
  retorna sucesso.
- Procura `desenhos_tecnicos/{peca_codigo}.pdf` (usei o código da peça, tipo
  `40-091799`, não um id numérico — é o identificador que o resto do sistema
  já usa).
- Se existir → `sendDocument` com legenda; se não → `sendMessage` avisando
  que não tem desenho.
- Depois manda uma segunda mensagem com botão inline "🔗 Ver Detalhes"
  apontando pro frontend (`{FRONTEND_URL}/?nota={id}`).
- Tudo dentro de `try/except`, nunca derruba a criação da nota (testado —
  ver abaixo).

**Duas mudanças de segurança em relação ao snippet original:** o token e o
`chat_id` vieram hardcoded no código que foi colado no pedido — coloquei os
dois no `.env` (`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `FRONTEND_URL`) em vez
de deixar no `app.py`, mesmo padrão já usado pra JWT/email/senha demo.
`requests` foi pra `requirements.txt` principal (diferente do bot do
Telegram, este código roda dentro do próprio Flask/Railway, então a
dependência precisa estar lá — é uma lib pura Python, não deve repetir o
problema do `psycopg2-binary`).

## O que testei de verdade (contra o backend local rodando)

- [x] `pytest` → 24/24 continuam passando, nada quebrou.
- [x] Criei uma nota real via `POST /api/notas` para `40-091799` (peça com
      PDF) → nota criada, OS gerada, **HTTP 201 normalmente**.
- [x] Criei outra para `40-122633` (peça sem PDF) → mesma coisa, **201
      normalmente**, confirma que o requisito "não quebra nada" está
      cumprido nos dois caminhos (com e sem desenho).
- [x] Confirmei nos logs que o código tentou mandar pro Telegram nos dois
      casos, com o branch certo (documento vs. mensagem).

## ⚠️ O que não funcionou — e não é bug do código

**O `chat_id` `-4574320855` não existe pro bot, segundo o próprio Telegram:**

```
POST .../sendMessage → {"ok":false,"error_code":400,"description":"Bad Request: chat not found"}
GET  .../getChat?chat_id=-4574320855 → mesma coisa
```

Confirmei direto na API do Telegram (não é erro de parsing meu). A causa
mais provável: o bot `@Prixbotbot` ainda não foi adicionado como membro
desse grupo — um bot só consegue mandar mensagem pra um chat do qual
participa.

**Para resolver:**
1. Adicione `@Prixbotbot` ao grupo/canal certo no Telegram.
2. Mande qualquer mensagem no grupo (ex: `/status`) pra gerar uma
   atualização.
3. Rode `curl "https://api.telegram.org/bot<TOKEN>/getUpdates"` (ou peça
   pra eu rodar) — o `chat.id` correto aparece na resposta.
4. Atualize `TELEGRAM_CHAT_ID` no `.env` com o valor certo.

Ou, mais simples pra testar sozinho: mande `/start` pro bot em uma conversa
privada e use o `chat.id` de lá (positivo, não negativo) como
`TELEGRAM_CHAT_ID` temporário.

## Resumo honesto

Código pronto, testado, e comprovadamente não quebra a criação de notas em
nenhum dos dois caminhos (com/sem desenho). O envio real pro Telegram está
bloqueado só pela configuração do `chat_id` — assim que isso for corrigido,
deve funcionar de primeira, já que todo o resto do fluxo (token válido,
requisição formada corretamente, tratamento de erro) já está confirmado
funcionando.

---

Gerado em: 15/09/2026
Executor: Claude Code
