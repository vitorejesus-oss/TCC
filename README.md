# App de Automação e Comunicação para Servidor Privado

Sistema completo com duas partes:

- **backend/** — API + WebSocket (Node.js) que roda no seu servidor (VPS) e faz o trabalho real: monitora o sistema, executa comandos pré-aprovados, guarda o histórico do chat e dispara alertas.
- **mobile/** — App mobile (React Native com Expo) que se conecta ao backend para mostrar status em tempo real, chat entre usuários, execução de comandos remotos e notificações push.

## O que o app faz

1. **Monitoramento/status**: CPU, memória, disco e uptime do servidor, atualizados em tempo real via WebSocket.
2. **Comandos/controle remoto**: uma lista de comandos pré-definidos pelo administrador (nunca texto livre) que podem ser disparados pelo app.
3. **Chat**: mensagens em tempo real entre os usuários que têm o app instalado.
4. **Notificações/alertas**: quando CPU, memória ou disco passam de um limite configurável, todos os usuários recebem um alerta (na tela e por push notification).

## Importante sobre este pacote

O ambiente onde este projeto foi gerado não tem acesso ao registro do NPM, então **as dependências não foram instaladas nem testadas em runtime aqui** — só foi feita uma verificação de sintaxe de todos os arquivos (`node --check` no backend e um parser TypeScript/JSX no app mobile), e todos passaram sem erros. Antes de usar de verdade, rode `npm install` em cada pasta (veja abaixo) — isso precisa de um computador com internet normal.

---

## 1. Backend (rodar no seu servidor/VPS)

### Pré-requisitos
- Node.js 18 ou mais recente instalado no servidor.
- Linux (o monitoramento e os comandos de exemplo assumem Linux; adapte se for outro SO).

### Configuração

```bash
cd backend
npm install
cp .env.example .env
```

Edite o `.env`:

- `JWT_SECRET`: gere um valor aleatório grande (ex: `openssl rand -hex 32`).
- `ADMIN_SETUP_CODE`: um código que só você conhece — é exigido para criar a primeira conta de administrador pelo app. Depois que o primeiro admin é criado, esse endpoint de "primeiro acesso" fica bloqueado automaticamente.
- Ajuste os limites de alerta (`CPU_ALERT_THRESHOLD`, etc.) se quiser.

### Rodar

```bash
npm start
```

O servidor sobe em `http://SEU_SERVIDOR:3000` (ajustável pela variável `PORT`). Para produção, recomenda-se:

- Rodar atrás de um **nginx** como proxy reverso, com HTTPS (Let's Encrypt) — importante porque o app troca senha e token, então não use HTTP puro na internet.
- Usar **pm2** ou um serviço **systemd** para manter o processo rodando e reiniciar sozinho se cair:

```bash
npm install -g pm2
pm2 start src/server.js --name servidor-privado-backend
pm2 save
pm2 startup
```

### Configurar os comandos remotos (whitelist)

Edite `backend/src/commands.config.js`. Cada item é um comando fixo, com uma chave (`key`), um rótulo para exibir no app e o comando de shell (`cmd`) que será executado. **Nunca** transforme isso em um campo de texto livre vindo do app — isso seria uma porta aberta para qualquer pessoa executar comandos arbitrários no seu servidor.

Se algum comando precisar de `sudo` (como reiniciar um serviço), configure permissão **apenas para aquele comando específico**, sem senha, usando `visudo`:

```
# /etc/sudoers.d/servidor-privado-app
usuario_do_node ALL=(root) NOPASSWD: /usr/bin/systemctl restart minha-app
```

Nunca dê `NOPASSWD: ALL` — isso anularia toda a proteção da whitelist.

### Criar o primeiro usuário (administrador)

Isso é feito **pelo próprio app mobile**, na tela "Primeiro acesso" do login, usando o `ADMIN_SETUP_CODE` do `.env`. Depois disso, o administrador pode criar outros usuários pelo endpoint `POST /api/auth/users` (ainda não tem tela própria no app — pode ser feito com `curl` ou adicionando uma tela depois).

Exemplo com `curl`:

```bash
curl -X POST http://SEU_SERVIDOR:3000/api/auth/users \
  -H "Authorization: Bearer SEU_TOKEN_DE_ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"username":"joao","password":"senha-forte","role":"user"}'
```

---

## 2. App mobile (Expo)

### Pré-requisitos
- Node.js 18+ no seu computador.
- App **Expo Go** instalado no celular (Android ou iOS) para testar rapidamente sem compilar nada nativo.

### Rodar em modo de desenvolvimento

```bash
cd mobile
npm install
npx expo start
```

Isso abre um QR code no terminal/navegador. Escaneie com o app Expo Go (Android: dentro do próprio app; iOS: pela câmera) e o app abre no celular, conectado à mesma rede Wi-Fi do computador.

Se alguma versão de pacote reclamar de incompatibilidade com o SDK do Expo, rode:

```bash
npx expo install --fix
```

### Primeiro uso do app

1. Ao abrir pela primeira vez, o app pede o **endereço do servidor** (ex: `http://192.168.0.10:3000` na sua rede local, ou `https://meuservidor.com` se já estiver publicado com domínio/HTTPS).
2. Na tela de login, toque em **"Primeiro acesso? Criar conta de administrador"** e informe o `ADMIN_SETUP_CODE` que você definiu no `.env` do backend.
3. Depois disso, esse fluxo de "primeiro acesso" some automaticamente (o backend bloqueia sozinho) e os próximos usuários entram por login normal, com contas criadas por um admin.

### Gerar um app instalável (APK/IPA), sem Expo Go

Quando quiser distribuir o app de verdade (sem depender do Expo Go), use o **EAS Build** da própria Expo (tem plano gratuito com limites):

```bash
npm install -g eas-cli
eas login
eas build:configure
eas build --platform android
```

Isso gera um `.apk`/`.aab` para instalar direto no Android. Para iOS é necessário conta de desenvolvedor Apple.

---

## Arquitetura (resumo)

```
[App mobile - Expo]  <—HTTP/REST—>   [Backend Node.js]
        |            <—WebSocket—>          |
        |                                    |—> monitora CPU/RAM/disco (systeminformation)
        |                                    |—> executa comandos da whitelist (child_process)
        |                                    |—> guarda usuários/mensagens/logs (arquivo JSON local)
        |                                    |—> dispara alerta quando passa do limite
        └── recebe push notification (Expo Push API) quando o backend dispara um alerta
```

O banco de dados do backend é um arquivo JSON simples (`backend/data/db.json`, via `lowdb`) — suficiente para um servidor privado com poucos usuários. Se o uso crescer bastante, dá para trocar por PostgreSQL/SQLite sem mudar a estrutura das rotas.

## Segurança — pontos que merecem atenção antes de usar em produção

- Sempre coloque o backend atrás de **HTTPS** (nginx + Let's Encrypt) antes de expor na internet — hoje o token de login viaja como texto se for HTTP puro.
- A whitelist de comandos é a principal proteção contra abuso — revise `commands.config.js` com cuidado e marque como `adminOnly: true` tudo que for arriscado (reiniciar serviços, apagar arquivos, etc).
- Troque `JWT_SECRET` e `ADMIN_SETUP_CODE` por valores realmente aleatórios — os exemplos no `.env.example` são só placeholders.
- Faça backup do `backend/data/db.json` de tempos em tempos (é onde ficam os usuários e o histórico).

## Próximos passos sugeridos

- Tela no app para o admin criar/gerenciar usuários direto pela interface (hoje é via `curl`/API).
- Histórico de comandos executados visível no app (o backend já guarda em `/api/commands/logs`).
- Múltiplas salas de chat, se for necessário separar assuntos.
