const { v4: uuidv4 } = require('uuid');
const db = require('./db');
const { collectStatus } = require('./routes/status');
const { sendExpoPush } = require('./push');

const CPU_THRESHOLD = Number(process.env.CPU_ALERT_THRESHOLD || 90);
const MEM_THRESHOLD = Number(process.env.MEM_ALERT_THRESHOLD || 90);
const DISK_THRESHOLD = Number(process.env.DISK_ALERT_THRESHOLD || 90);
const INTERVAL_MS = Number(process.env.MONITOR_INTERVAL_MS || 15000);

// Evita spam: só dispara o mesmo tipo de alerta de novo depois de ficar "ok" uma vez
const lastAlertState = { cpu: false, memory: false, disk: false };

function pushAlert(io, type, message) {
  const alert = { id: uuidv4(), type, message, createdAt: new Date().toISOString() };
  db.get('alerts').push(alert).write();
  if (io) io.emit('alert', alert);

  const tokens = db.get('users').map('pushToken').value().filter(Boolean);
  sendExpoPush(tokens, { title: '⚠️ Alerta do servidor', body: message, data: { alert } });
}

function startMonitor(io) {
  setInterval(async () => {
    try {
      const status = await collectStatus();

      checkThreshold(io, 'cpu', status.cpu.usagePercent, CPU_THRESHOLD, `CPU em ${status.cpu.usagePercent}%`);
      checkThreshold(io, 'memory', status.memory.usagePercent, MEM_THRESHOLD, `Memória em ${status.memory.usagePercent}%`);
      if (status.disk.usagePercent != null) {
        checkThreshold(io, 'disk', status.disk.usagePercent, DISK_THRESHOLD, `Disco em ${status.disk.usagePercent}%`);
      }

      if (io) io.emit('status:update', status);
    } catch (err) {
      console.error('[monitor] erro ao coletar status:', err.message);
    }
  }, INTERVAL_MS);
}

function checkThreshold(io, key, value, threshold, message) {
  if (value >= threshold && !lastAlertState[key]) {
    lastAlertState[key] = true;
    pushAlert(io, key, message);
  } else if (value < threshold) {
    lastAlertState[key] = false;
  }
}

module.exports = { startMonitor };
