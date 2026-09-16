import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl } from 'react-native';
import api from '../services/api';
import { getSocket } from '../services/socket';
import { colors } from '../theme';

function Gauge({ label, percent, sublabel }) {
  const value = Math.max(0, Math.min(100, percent ?? 0));
  const barColor = value >= 90 ? colors.danger : value >= 70 ? colors.warning : colors.success;

  return (
    <View style={styles.gaugeCard}>
      <View style={styles.gaugeHeader}>
        <Text style={styles.gaugeLabel}>{label}</Text>
        <Text style={[styles.gaugeValue, { color: barColor }]}>{value}%</Text>
      </View>
      <View style={styles.gaugeTrack}>
        <View style={[styles.gaugeFill, { width: `${value}%`, backgroundColor: barColor }]} />
      </View>
      {!!sublabel && <Text style={styles.gaugeSublabel}>{sublabel}</Text>}
    </View>
  );
}

function formatUptime(seconds) {
  if (!seconds && seconds !== 0) return '—';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${d}d ${h}h ${m}m`;
}

export default function DashboardScreen() {
  const [status, setStatus] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');

  const loadAll = useCallback(async () => {
    try {
      const [statusRes, alertsRes] = await Promise.all([api.get('/status'), api.get('/alerts')]);
      setStatus(statusRes.data);
      setAlerts(alertsRes.data.alerts);
      setError('');
    } catch (err) {
      setError('Não foi possível carregar o status do servidor.');
    }
  }, []);

  useEffect(() => {
    loadAll();

    const socket = getSocket();
    if (!socket) return;

    const onStatus = (data) => setStatus(data);
    const onAlert = (alert) => setAlerts((prev) => [alert, ...prev].slice(0, 50));

    socket.on('status:update', onStatus);
    socket.on('alert', onAlert);
    return () => {
      socket.off('status:update', onStatus);
      socket.off('alert', onAlert);
    };
  }, [loadAll]);

  async function onRefresh() {
    setRefreshing(true);
    await loadAll();
    setRefreshing(false);
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={{ padding: 16 }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
    >
      <Text style={styles.title}>Status do servidor</Text>

      {!!error && <Text style={styles.error}>{error}</Text>}

      {status && (
        <>
          <Gauge label="CPU" percent={status.cpu.usagePercent} sublabel={`${status.cpu.model} · ${status.cpu.cores} núcleos`} />
          <Gauge
            label="Memória"
            percent={status.memory.usagePercent}
            sublabel={`${status.memory.usedMB} MB / ${status.memory.totalMB} MB`}
          />
          {status.disk.usagePercent != null && (
            <Gauge
              label="Disco"
              percent={status.disk.usagePercent}
              sublabel={`${status.disk.usedGB} GB / ${status.disk.totalGB} GB (${status.disk.mount})`}
            />
          )}
          <View style={styles.uptimeCard}>
            <Text style={styles.uptimeLabel}>Uptime</Text>
            <Text style={styles.uptimeValue}>{formatUptime(status.uptimeSeconds)}</Text>
          </View>
        </>
      )}

      <Text style={styles.sectionTitle}>Alertas recentes</Text>
      {alerts.length === 0 && <Text style={styles.emptyText}>Nenhum alerta até agora. 🎉</Text>}
      {alerts.map((alert) => (
        <View key={alert.id} style={styles.alertRow}>
          <Text style={styles.alertMessage}>{alert.message}</Text>
          <Text style={styles.alertTime}>{new Date(alert.createdAt).toLocaleString('pt-BR')}</Text>
        </View>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  title: { color: colors.text, fontSize: 22, fontWeight: '700', marginBottom: 16 },
  error: { color: colors.danger, marginBottom: 12 },
  gaugeCard: {
    backgroundColor: colors.surface,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: colors.border,
  },
  gaugeHeader: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 8 },
  gaugeLabel: { color: colors.text, fontSize: 15, fontWeight: '600' },
  gaugeValue: { fontSize: 15, fontWeight: '700' },
  gaugeTrack: { height: 8, backgroundColor: colors.surfaceAlt, borderRadius: 4, overflow: 'hidden' },
  gaugeFill: { height: 8, borderRadius: 4 },
  gaugeSublabel: { color: colors.textMuted, fontSize: 12, marginTop: 6 },
  uptimeCard: {
    backgroundColor: colors.surface,
    borderRadius: 12,
    padding: 14,
    marginBottom: 20,
    borderWidth: 1,
    borderColor: colors.border,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  uptimeLabel: { color: colors.textMuted, fontSize: 14 },
  uptimeValue: { color: colors.text, fontSize: 16, fontWeight: '600' },
  sectionTitle: { color: colors.text, fontSize: 17, fontWeight: '700', marginBottom: 10 },
  emptyText: { color: colors.textMuted, fontSize: 13 },
  alertRow: {
    backgroundColor: colors.surface,
    borderRadius: 10,
    padding: 12,
    marginBottom: 8,
    borderLeftWidth: 3,
    borderLeftColor: colors.warning,
  },
  alertMessage: { color: colors.text, fontSize: 14, marginBottom: 4 },
  alertTime: { color: colors.textMuted, fontSize: 11 },
});
