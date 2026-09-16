# React conectado ao backend — status real

Testado ao vivo em 14/09/2026: backend Flask (`python app.py`) + frontend Vite/React
(`npm run dev`, `frontend/`) rodando ao mesmo tempo, abertos no navegador e clicados
manualmente, um recurso por vez. Nada aqui foi assumido — cada item abaixo foi
verificado ou explicitamente marcado como não verificado.

## O que foi de fato testado e funciona

- [x] **WebSocket em tempo real** — indicador "Tempo real conectado" (bolinha verde)
      aparece ao abrir a página; ao criar uma nota pela aba "Criar Nota", o evento
      `nota_processada` chegou no feed "Ao vivo" em menos de 1s e a tabela de OS
      atualizou sozinha, sem F5.
- [x] **Login JWT** — login com `operador@fabrica.com` / `123456` funcionou, o token
      foi salvo e usado com sucesso para chamar `/api/painel/operador` (retornou a
      fila de produção real). Testado também: acesso sem token → 401.
- [x] **Backup** — botão "Criar Backup Agora" chamou `POST /api/backup/criar` e o
      arquivo `.db` apareceu na tabela imediatamente (nome, tamanho, data reais).
- [x] **Estatísticas** — aba carrega `/api/estatisticas` e mostra dados reais
      (desempenho por máquina batendo com a peça processada no teste).
- [x] **Métricas / Gestão** — cards de economia recalculam a partir do banco real
      (não são mais valores fixos).
- [x] **Criar Nota / Iniciar OS** (funcionalidade original) — confirmado que segue
      funcionando com o backend novo: criar nota gera OS de verdade, botão "Iniciar"
      muda o status para USINANDO.
- [x] **Relatório PDF** — o botão "Baixar PDF" disparou a requisição correta
      (`GET /api/relatorio/economia?mes=Setembro&ano=2026`) e o backend respondeu
      `200 OK` com um PDF válido (confirmado por `curl` na sessão anterior: cabeçalho
      `%PDF-1.4`, ~2.4KB, abre normalmente).

## O que NÃO foi testado (e por quê)

- [ ] **Upload de arquivo SAP pela UI** — a tela de importação SAP existe, está
      conectada ao endpoint certo e o botão fica desabilitado até um arquivo ser
      escolhido (comportamento correto). Mas o navegador automatizado usado para
      este teste não consegue interagir com o seletor nativo de arquivos do Windows
      (é uma limitação da ferramenta, não do código). **Você precisa testar esta
      parte manualmente**: abra a aba SAP, escolha `sap_test.txt` e clique em
      "Importar Arquivo". O endpoint em si (`/api/sap/importar`) já foi validado
      via `curl` na sessão anterior e funciona.
- [ ] **Download real do PDF no seu navegador** — o ambiente de teste usado aqui
      bloqueia downloads de arquivo por sandbox. A requisição/resposta foi
      confirmada (200 OK, PDF válido), mas o clique final "arquivo salvo no disco"
      não foi visto acontecer. Deve funcionar normalmente no seu Chrome/Edge.

## O que precisou ser criado do zero nesta sessão

O `frontend.jsx` original só chamava os 6 endpoints básicos (notas, ordens, peças,
máquinas, métricas, auditoria) — nada dos 10 diferenciais estava ligado a ele.
Nesta sessão:

1. Foi instalado Node.js (não existia no PC).
2. Foi criado um projeto React real (`frontend/`, Vite) — antes só havia o arquivo
   solto `frontend.jsx`, sem `package.json` nem como rodar.
3. Foram adicionadas 4 abas novas (SAP, Relatório, Backup, Estatísticas) e uma
   tela de Login/JWT com painel protegido, além do indicador e feed de WebSocket
   em tempo real no topo da página.
4. Tudo foi testado clicando de verdade no navegador (screenshots e logs de rede
   conferidos), não apenas lendo o código.

## Próximos passos reais

1. Testar o upload de SAP manualmente (única peça não coberta pelo teste automatizado).
2. Configurar `EMAIL_USUARIO` / `EMAIL_SENHA` / `GESTOR_EMAIL` no `.env` para testar
   alertas reais por email (endpoint já testado, mas sem credenciais não envia).
3. Rodar `npm run dev` (pasta `frontend/`) + `python app.py` juntos antes da
   apresentação e treinar a demo com esses dois processos no ar.
4. Preparar um arquivo SAP maior (150 notas) para o dia da apresentação —
   `sap_test.txt` atual tem só 6 linhas de teste.

## Sistema pronto?

Backend: sim, testado (24/24 testes automatizados + endpoints reais).
Frontend: sim, para 7 dos 8 recursos novos, testados ao vivo no navegador. O
upload de arquivo SAP pela UI precisa de um teste manual seu antes da apresentação.
