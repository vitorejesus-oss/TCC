const jwt = require('jsonwebtoken');
const { v4: uuidv4 } = require('uuid');
const db = require('./db');

function setupSocket(io) {
  // Autentica a conexão do WebSocket usando o mesmo token JWT do REST
  io.use((socket, next) => {
    const token = socket.handshake.auth?.token;
    if (!token) return next(new Error('Token não fornecido'));
    try {
      const payload = jwt.verify(token, process.env.JWT_SECRET);
      const user = db.get('users').find({ id: payload.sub }).value();
      if (!user) return next(new Error('Usuário não encontrado'));
      socket.user = { id: user.id, username: user.username, role: user.role };
      next();
    } catch (err) {
      next(new Error('Token inválido'));
    }
  });

  io.on('connection', (socket) => {
    console.log(`[socket] ${socket.user.username} conectou`);
    io.emit('presence:update', { username: socket.user.username, online: true });

    socket.on('chat:send', (payload, ack) => {
      const text = (payload?.text || '').trim().slice(0, 2000);
      if (!text) return;

      const message = {
        id: uuidv4(),
        userId: socket.user.id,
        username: socket.user.username,
        text,
        createdAt: new Date().toISOString(),
      };
      db.get('messages').push(message).write();
      io.emit('chat:message', message);
      if (typeof ack === 'function') ack({ ok: true, message });
    });

    socket.on('disconnect', () => {
      console.log(`[socket] ${socket.user.username} desconectou`);
      io.emit('presence:update', { username: socket.user.username, online: false });
    });
  });
}

module.exports = { setupSocket };
