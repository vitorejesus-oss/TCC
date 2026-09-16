const path = require('path');
const low = require('lowdb');
const FileSync = require('lowdb/adapters/FileSync');

const dbFile = path.join(__dirname, '..', 'data', 'db.json');
const adapter = new FileSync(dbFile);
const db = low(adapter);

// Estrutura inicial do banco de dados
db.defaults({
  users: [],       // { id, username, passwordHash, role: 'admin' | 'user', pushToken, createdAt }
  messages: [],     // { id, userId, username, text, createdAt }
  commandLogs: [],  // { id, userId, username, commandKey, output, success, createdAt }
  alerts: []        // { id, type, message, createdAt }
}).write();

module.exports = db;
