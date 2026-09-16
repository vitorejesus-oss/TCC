require('dotenv').config();
const http = require('http');
const express = require('express');
const cors = require('cors');
const { Server } = require('socket.io');

const authRoutes = require('./routes/auth');
const { router: statusRoutes } = require('./routes/status');
const commandsRoutes = require('./routes/commands');
const messagesRoutes = require('./routes/messages');
const alertsRoutes = require('./routes/alerts');
const { setupSocket } = require('./socket');
const { startMonitor } = require('./monitor');

if (!process.env.JWT_SECRET) {
  console.error('ERRO: defina JWT_SECRET no arquivo .env antes de iniciar o servidor.');
  process.exit(1);
}

const app = express();
app.use(cors());
app.use(express.json());

app.get('/health', (req, res) => res.json({ ok: true, service: 'servidor-privado-backend' }));

app.use('/api/auth', authRoutes);
app.use('/api/status', statusRoutes);
app.use('/api/commands', commandsRoutes);
app.use('/api/messages', messagesRoutes);
app.use('/api/alerts', alertsRoutes);

app.use((req, res) => res.status(404).json({ error: 'Rota não encontrada' }));
// eslint-disable-next-line no-unused-vars
app.use((err, req, res, next) => {
  console.error(err);
  res.status(500).json({ error: 'Erro interno do servidor' });
});

const server = http.createServer(app);
const io = new Server(server, { cors: { origin: '*' } });
app.set('io', io);

setupSocket(io);
startMonitor(io);

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
  console.log(`Servidor rodando na porta ${PORT}`);
});
