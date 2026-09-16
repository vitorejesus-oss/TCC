const express = require('express');
const { exec } = require('child_process');
const { v4: uuidv4 } = require('uuid');
const db = require('../db');
const { authRequired, adminRequired } = require('../middleware/auth');
const commandsConfig = require('../commands.config');

const router = express.Router();

// Lista os comandos que o usuário logado tem permissão de executar
router.get('/', authRequired, (req, res) => {
  const visible = commandsConfig
    .filter((c) => !c.adminOnly || req.user.role === 'admin')
    .map(({ key, label, description, adminOnly }) => ({ key, label, description, adminOnly }));
  res.json({ commands: visible });
});

function runCommand(commandDef) {
  return new Promise((resolve) => {
    exec(commandDef.cmd, { timeout: 15000, maxBuffer: 1024 * 1024 }, (error, stdout, stderr) => {
      resolve({
        success: !error,
        output: (stdout || stderr || error?.message || '').toString().slice(0, 8000),
      });
    });
  });
}

// Executa um comando pré-definido (nunca um comando de texto livre!)
router.post('/:key/execute', authRequired, async (req, res) => {
  const commandDef = commandsConfig.find((c) => c.key === req.params.key);
  if (!commandDef) {
    return res.status(404).json({ error: 'Comando não encontrado' });
  }
  if (commandDef.adminOnly && req.user.role !== 'admin') {
    return res.status(403).json({ error: 'Apenas administradores podem executar este comando' });
  }

  const result = await runCommand(commandDef);

  const log = {
    id: uuidv4(),
    userId: req.user.id,
    username: req.user.username,
    commandKey: commandDef.key,
    output: result.output,
    success: result.success,
    createdAt: new Date().toISOString(),
  };
  db.get('commandLogs').push(log).write();

  // Notifica outros clientes conectados (ex: admins acompanhando em tempo real)
  const io = req.app.get('io');
  if (io) {
    io.emit('command:executed', {
      key: commandDef.key,
      label: commandDef.label,
      by: req.user.username,
      success: result.success,
      createdAt: log.createdAt,
    });
  }

  res.json({ success: result.success, output: result.output });
});

// Histórico de comandos executados (só admin)
router.get('/logs', authRequired, adminRequired, (req, res) => {
  const logs = db.get('commandLogs').sortBy('createdAt').takeRight(100).reverse().value();
  res.json({ logs });
});

module.exports = router;
