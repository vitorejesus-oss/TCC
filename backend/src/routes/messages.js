const express = require('express');
const { v4: uuidv4 } = require('uuid');
const db = require('../db');
const { authRequired } = require('../middleware/auth');

const router = express.Router();

// Histórico do chat (últimas 100 mensagens)
router.get('/', authRequired, (req, res) => {
  const messages = db.get('messages').sortBy('createdAt').takeRight(100).value();
  res.json({ messages });
});

// Envio via REST (fallback; o app normalmente usa o WebSocket para isso)
router.post('/', authRequired, (req, res) => {
  const { text } = req.body || {};
  if (!text || !text.trim()) {
    return res.status(400).json({ error: 'text é obrigatório' });
  }

  const message = {
    id: uuidv4(),
    userId: req.user.id,
    username: req.user.username,
    text: text.trim().slice(0, 2000),
    createdAt: new Date().toISOString(),
  };
  db.get('messages').push(message).write();

  const io = req.app.get('io');
  if (io) io.emit('chat:message', message);

  res.status(201).json({ message });
});

module.exports = router;
