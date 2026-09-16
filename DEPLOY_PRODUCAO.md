# Deploy em Produção (Railway + Vercel) — Status

**Backend:** ainda não implantado (não em `https://algo.railway.app`)
**Frontend:** ainda não implantado (não em `https://algo.vercel.app`)
**Status:** preparação local concluída — falta o login e o deploy em si, que só
você pode fazer (ver "Por que parei aqui" abaixo).

---

## O que foi preparado nesta sessão

| Arquivo | O que mudou |
|---|---|
| `requirements.txt` | Adicionado `gunicorn`, `psycopg2-binary`, `SQLAlchemy` |
| `railway.json` | Criado. Comando de start usa `$PORT` (Railway define essa variável — porta fixa 5000 não funcionaria) e `-w 1 --threads 8` em vez de `-w 4` |
| `.env.production` (backend) | Criado com placeholders + uma `JWT_SECRET_KEY` aleatória forte já gerada |
| `.gitignore` (backend) | Adicionado `.env.production` e `.env.*.local` — não estavam cobertos e vazariam segredos no Git |
| `app.py` | Adicionado `DATABASE_URL` (com aviso no log se alguém setar um Postgres — ver nota crítica abaixo); `CORS_ORIGINS` agora é lido de verdade e aplicado tanto no Flask-CORS quanto no Socket.IO |
| `frontend/src/App.jsx` | Corrigido para usar `import.meta.env.VITE_API_URL` (ver nota crítica abaixo) |
| `frontend/.env.production` | Criado com prefixo `VITE_` (não `REACT_APP_`) |

Testei localmente depois de cada mudança (backend + frontend rodando juntos,
criei uma nota pela UI, evento chegou em tempo real) — nada quebrou.

---

## ⚠️ Duas correções importantes em relação ao roteiro original

**1. `process.env.REACT_APP_API_URL` não funcionaria neste projeto.**
Esse é o padrão do Create React App. Este frontend é Vite, que expõe variáveis
de ambiente como `import.meta.env.VITE_*` — e `process` nem existe no bundle
que roda no navegador. Se eu tivesse seguido o snippet ao pé da letra, o app
quebraria com `ReferenceError: process is not defined` assim que abrisse no
Vercel. Corrigi para `import.meta.env.VITE_API_URL` e nomeei o arquivo de
variáveis com prefixo `VITE_`.

**2. `DATABASE_URL` sozinha não migra nada para Postgres.**
O `app.py` usa `sqlite3` puro (conexões e SQL cru), não SQLAlchemy — apesar de
eu ter adicionado a dependência ao `requirements.txt` como pedido. Definir
`DATABASE_URL=postgresql://...` no Railway **não** faz o app passar a usar
Postgres; ele continua gravando em `usinagem.db` (SQLite) porque é isso que
`get_db()` chama. Isso importa muito em produção: **o filesystem do Railway é
efêmero** — a cada redeploy (ou às vezes reinício do container), o arquivo
`usinagem.db` é apagado e todo o histórico (peças, notas, OS, usuários,
auditoria) volta ao zero. Deixei um aviso automático no log do app para isso
não passar despercebido. Migrar de verdade para Postgres exigiria reescrever
`get_db()` e todas as queries para usar SQLAlchemy — não fiz isso agora
porque é um trabalho bem maior que "adicionar 3 linhas", e prefiro avisar do
que fingir que está pronto.

---

## Por que parei antes do deploy em si

Três coisas que só você pode fazer, e que eu não devo fazer por você:

1. **`railway login` / `vercel login`** exigem autenticar com a sua conta
   (fluxo de navegador ou token pessoal). Eu não tenho — e não devo ter —
   suas credenciais dessas contas.
2. **Depois de logado, `railway up` e `vercel --prod` colocam o sistema no ar
   de verdade**, em uma URL pública, potencialmente consumindo cota/crédito
   da sua conta. É uma ação real e visível para fora, não uma edição de
   arquivo — prefiro confirmar com você antes de disparar isso, mesmo com
   tudo preparado.
3. **Antes de ir ao ar de verdade**, vale trocar a senha padrão dos usuários
   demo (`123456`, ainda ativa) e preencher `EMAIL_USUARIO`/`EMAIL_SENHA` só
   se for usar alertas de verdade — caso contrário deixe em branco mesmo.

## Próximos passos (para você rodar)

```bash
npm install -g @railway/cli
railway login
cd TCC.VITOR
railway up
```

Depois de ver a URL gerada pelo Railway, cole ela em
`frontend/.env.production` (nos dois campos `VITE_...`) e rode:

```bash
npm install -g vercel
cd frontend
vercel login
vercel --prod
```

Me avise as duas URLs (ou só me diga "já fiz login") e eu continuo — confiro
CORS, testo os endpoints reais e atualizo este relatório com o resultado
verdadeiro.

---

Gerado em: 14/09/2026
Executor: Claude Code
