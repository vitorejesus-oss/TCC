const express = require('express');
const si = require('systeminformation');
const { authRequired } = require('../middleware/auth');

const router = express.Router();

async function collectStatus() {
  const [cpu, mem, disks, time, currentLoad] = await Promise.all([
    si.cpu(),
    si.mem(),
    si.fsSize(),
    si.time(),
    si.currentLoad(),
  ]);

  const disk = disks[0] || {};

  return {
    timestamp: new Date().toISOString(),
    uptimeSeconds: time.uptime,
    cpu: {
      model: `${cpu.manufacturer} ${cpu.brand}`.trim(),
      cores: cpu.cores,
      usagePercent: Math.round(currentLoad.currentLoad * 10) / 10,
    },
    memory: {
      totalMB: Math.round(mem.total / 1024 / 1024),
      usedMB: Math.round((mem.total - mem.available) / 1024 / 1024),
      usagePercent: Math.round(((mem.total - mem.available) / mem.total) * 1000) / 10,
    },
    disk: {
      mount: disk.mount || 'N/A',
      totalGB: disk.size ? Math.round(disk.size / 1024 / 1024 / 1024) : null,
      usedGB: disk.used ? Math.round(disk.used / 1024 / 1024 / 1024) : null,
      usagePercent: disk.use ?? null,
    },
  };
}

router.get('/', authRequired, async (req, res) => {
  try {
    const status = await collectStatus();
    res.json(status);
  } catch (err) {
    res.status(500).json({ error: 'Falha ao coletar status do servidor', details: err.message });
  }
});

module.exports = { router, collectStatus };
