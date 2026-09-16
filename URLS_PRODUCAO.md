# Sistema em Produção — URLs reais

**Backend (Railway):** https://automacao-usinagem-backend-production.up.railway.app
**Frontend (Vercel):** https://frontend-xi-two-5l7d05gqtg.vercel.app

**Login demo:** `operador@fabrica.com` / `coordenador@fabrica.com` /
`gestor@fabrica.com` / `diretor@fabrica.com` — senha **`Vitor367`** (a antiga
`123456` foi trocada e não funciona mais, confirmado por teste real).

Testado agora (14/09/2026, ~23h): health check, login (senha nova aceita,
senha antiga rejeitada com 401), criação de nota → OS real, WebSocket
conectado e atualizando ao vivo — tudo isso direto contra as URLs acima, via
curl e pelo navegador aberto na URL do Vercel.

---

## Bugs reais encontrados e corrigidos durante ESTE deploy

Nenhum destes aparecia rodando local (`python app.py`) — só em produção:

1. **`psycopg2-binary` quebrava o build.** Não é usado em lugar nenhum do
   código (`app.py` fala SQLite puro), mas travava a compilação no Python
   3.13 do Railway. Removido junto com `SQLAlchemy` (também não usado).
2. **`railway.json` e a variável `NIXPACKS_START_CMD` foram ignorados** pela
   versão atual do CLI do Railway (que está migrando para um novo formato de
   config). O container ficava tentando rodar `main:app`, que não existe.
   Resolvido com um `Procfile` (`web: gunicorn ... app:app`), que tem
   prioridade mais alta e funcionou de primeira.
3. **O mais sério: a inicialização do banco (`init_db`, `seed_data`,
   `seed_usuarios`, o agendador de backup) estava dentro de
   `if __name__ == '__main__':`.** Isso roda com `python app.py`, mas
   **nunca roda** quando um servidor WSGI real (gunicorn) importa
   `app:app` diretamente — é assim que toda a stack de produção funciona.
   Resultado: o banco subia sem nenhuma tabela, e login/qualquer coisa que
   tocasse o banco quebrava com 500. Corrigido movendo essas chamadas para
   fora do bloco, executando sempre que o módulo é importado.
4. **A senha demo antiga (`123456`) sobreviveu a um redeploy** — o disco do
   Railway não se comportou como "totalmente descartável a cada deploy" (o
   que eu tinha documentado antes, com base no comportamento padrão
   esperado da plataforma); nos redeploys rápidos desta sessão, dados de uma
   tentativa anterior persistiram. Corrigido tornando `seed_usuarios()`
   idempotente-por-sincronização: agora ele sempre atualiza o hash das 4
   contas demo para a senha atual em vez de só criar-se-vazio, então a senha
   configurada (`Vitor367`) vale de verdade, não importa o que sobreviveu de
   antes.

## O que ficou configurado no Railway (variáveis)

- `JWT_SECRET_KEY` — chave forte gerada, não é mais o valor de exemplo
- `SENHA_PADRAO_DEMO=Vitor367`
- `CORS_ORIGINS` — travado na URL exata do Vercel acima (não é mais `*`)
- `NIXPACKS_START_CMD` — pode remover, já não é necessário (o Procfile
  manda), mas não atrapalha deixar

## O que ainda não verifiquei clicando na tela (mas verifiquei por outro caminho)

O clique físico no formulário de Login da página do Vercel esbarrou numa
falha de scroll da ferramenta de automação nesta sessão (não é um bug do
site). Em vez de forçar, confirmei a mesma coisa de duas formas diretas:
login funcionando via `curl` contra a URL real de produção (aceita
`Vitor367`, rejeita `123456` com 401) e o mesmo componente de login já
testado clicando na tela numa sessão anterior, sem mudanças de lógica desde
então. Vale um clique seu de qualquer forma antes da apresentação.

## Ponto de atenção que continua valendo

O banco ainda é SQLite num arquivo local ao container — mesmo com a
persistência inesperada observada nesta sessão, não há garantia de
durabilidade real (sem volume anexado, sem backup fora do container). Para
um uso sério a médio prazo, migrar para Postgres (via SQLAlchemy, reescrevendo
`get_db()` e as queries) ou anexar um Volume do Railway ao serviço.

---

Gerado em: 14/09/2026
Executor: Claude Code
