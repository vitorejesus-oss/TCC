const express = require('express');
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const { v4: uuidv4 } = require('uuid');
const db = require('../db');
const { authRequired, adminRequired } = require('../middleware/auth');

const router = express.Router();

function signToken(user) {
  return jwt.sign({ sub: user.id, role: user.role }, process.env.JWT_SECRET, {
    expiresIn: process.env.JWT_EXPIRES_IN || '7d',
  });
}

function publicUser(user) {
  return { id: user.id, username: user.username, role: user.role };
}

// Cria a primeira conta (admin), protegida por um código de configuração.
// Depois que já existe pelo menos um usuário, este endpoint deixa de funcionar.
router.post('/setup', (req, res) => {
  const { username, password, setupCode } = req.body || {};
  const hasUsers = db.get('users').size().value() > 0;

  if (hasUsers) {
    return res.status(403).json({ error: 'Setup já foi concluído. Peça a um admin para criar sua conta.' });
  }
  if (!username || !password) {
    return res.status(400).json({ error: 'username e password são obrigatórios' });
  }
  if (setupCode !== process.env.ADMIN_SETUP_CODE) {
    return res.status(403).json({ error: 'Código de configuração inválido' });
  }

  const user = {
    id: uuidv4(),
    username,
    passwordHash: bcrypt.hashSync(password, 10),
    role: 'admin',
    pushToken: null,
    createdAt: new Date().toISOString(),
  };
  db.get('users').push(user).write();

  const token = signToken(user);
  res.status(201).json({ token, user: publicUser(user) });
});

// Login
router.post('/login', (req, res) => {
  const { username, password } = req.body || {};
  if (!username || !password) {
    return res.status(400).json({ error: 'username e password são obrigatórios' });
  }

  const user = db.get('users').find({ username }).value();
  if (!user || !bcrypt.compareSync(password, user.passwordHash)) {
    return res.status(401).json({ error: 'Usuário ou senha inválidos' });
  }

  const token = signToken(user);
  res.json({ token, user: publicUser(user) });
});

// Admin cria novos usuários (depois do setup inicial)
router.post('/users', authRequired, adminRequired, (req, res) => {
  const { username, password, role } = req.body || {};
  if (!username || !password) {
    return res.status(400).json({ error: 'username e password são obrigatórios' });
  }
  if (db.get('users').find({ username }).value()) {
    return res.status(409).json({ error: 'Esse username já existe' });
  }

  const user = {
    id: uuidv4(),
    username,
    passwordHash: bcrypt.hashSync(password, 10),
    role: role === 'admin' ? 'admin' : 'user',
    pushToken: null,
    createdAt: new Date().toISOString(),
  };
  db.get('users').push(user).write();
  res.status(201).json({ user: publicUser(user) });
});

// Usuário logado consulta os próprios dados
router.get('/me', authRequired, (req, res) => {
  res.json({ user: req.user });
});

// Registrar/atualizar o token de push notification do dispositivo (Expo)
router.post('/push-token', authRequired, (req, res) => {
  const { pushToken } = req.body || {};
  db.get('users').find({ id: req.user.id }).assign({ pushToken: pushToken || null }).write();
  res.json({ ok: true });
});

module.exports = router;
