import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, StyleSheet, FlatList, TouchableOpacity, Alert, ActivityIndicator, Modal, ScrollView } from 'react-native';
import api, { extractErrorMessage } from '../services/api';
import { colors } from '../theme';

export default function CommandsScreen() {
  const [commands, setCommands] = useState([]);
  const [loading, setLoading] = useState(true);
  const [runningKey, setRunningKey] = useState(null);
  const [result, setResult] = useState(null);

  const loadCommands = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/commands');
      setCommands(data.commands);
    } catch (err) {
      Alert.alert('Erro', extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCommands();
  }, [loadCommands]);

  function confirmAndRun(command) {
    Alert.alert(
      command.label,
      `Executar "${command.label}" agora no servidor?`,
      [
        { text: 'Cancelar', style: 'cancel' },
        { text: 'Executar', style: 'destructive', onPress: () => runCommand(command) },
      ]
    );
  }

  async function runCommand(command) {
    setRunningKey(command.key);
    try {
      const { data } = await api.post(`/commands/${command.key}/execute`);
      setResult({ label: command.label, ...data });
    } catch (err) {
      setResult({ label: command.label, success: false, output: extractErrorMessage(err) });
    } finally {
      setRunningKey(null);
    }
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Comandos remotos</Text>

      {loading && <ActivityIndicator color={colors.primary} style={{ marginTop: 20 }} />}

      <FlatList
        data={commands}
        keyExtractor={(item) => item.key}
        contentContainerStyle={{ padding: 16 }}
        ListEmptyComponent={
          !loading ? <Text style={styles.emptyText}>Nenhum comando disponível para o seu usuário.</Text> : null
        }
        renderItem={({ item }) => (
          <TouchableOpacity
            style={styles.card}
            onPress={() => confirmAndRun(item)}
            disabled={runningKey === item.key}
          >
            <View style={{ flex: 1 }}>
              <Text style={styles.cardTitle}>{item.label}</Text>
              {!!item.description && <Text style={styles.cardDescription}>{item.description}</Text>}
              {item.adminOnly && <Text style={styles.adminTag}>ADMIN</Text>}
            </View>
            {runningKey === item.key && <ActivityIndicator color={colors.primary} />}
          </TouchableOpacity>
        )}
      />

      <Modal visible={!!result} transparent animationType="fade" onRequestClose={() => setResult(null)}>
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>{result?.label}</Text>
            <Text style={[styles.modalStatus, { color: result?.success ? colors.success : colors.danger }]}>
              {result?.success ? 'Sucesso' : 'Falhou'}
            </Text>
            <ScrollView style={styles.outputBox}>
              <Text style={styles.outputText}>{result?.output || '(sem saída)'}</Text>
            </ScrollView>
            <TouchableOpacity style={styles.closeButton} onPress={() => setResult(null)}>
              <Text style={styles.closeButtonText}>Fechar</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  title: { color: colors.text, fontSize: 22, fontWeight: '700', paddingHorizontal: 16, paddingTop: 16 },
  emptyText: { color: colors.textMuted, textAlign: 'center', marginTop: 20 },
  card: {
    backgroundColor: colors.surface,
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: colors.border,
    flexDirection: 'row',
    alignItems: 'center',
  },
  cardTitle: { color: colors.text, fontSize: 15, fontWeight: '600' },
  cardDescription: { color: colors.textMuted, fontSize: 12, marginTop: 4 },
  adminTag: { color: colors.warning, fontSize: 10, fontWeight: '700', marginTop: 6 },
  modalBackdrop: { flex: 1, backgroundColor: '#00000099', justifyContent: 'center', padding: 24 },
  modalCard: { backgroundColor: colors.surface, borderRadius: 14, padding: 18, maxHeight: '70%' },
  modalTitle: { color: colors.text, fontSize: 17, fontWeight: '700' },
  modalStatus: { fontSize: 13, fontWeight: '700', marginTop: 4, marginBottom: 12 },
  outputBox: { backgroundColor: colors.background, borderRadius: 8, padding: 10, maxHeight: 220 },
  outputText: { color: colors.text, fontFamily: 'monospace', fontSize: 12 },
  closeButton: { backgroundColor: colors.primary, borderRadius: 10, padding: 12, alignItems: 'center', marginTop: 14 },
  closeButtonText: { color: '#0F172A', fontWeight: '700' },
});
