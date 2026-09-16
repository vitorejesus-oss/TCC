import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Alert } from 'react-native';
import { useAuth } from '../context/AuthContext';
import { colors } from '../theme';

export default function SettingsScreen() {
  const { user, serverUrl, logout } = useAuth();

  function confirmLogout() {
    Alert.alert('Sair', 'Deseja sair da sua conta?', [
      { text: 'Cancelar', style: 'cancel' },
      { text: 'Sair', style: 'destructive', onPress: logout },
    ]);
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Configurações</Text>

      <View style={styles.card}>
        <Text style={styles.label}>Usuário</Text>
        <Text style={styles.value}>{user?.username}</Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.label}>Função</Text>
        <Text style={styles.value}>{user?.role === 'admin' ? 'Administrador' : 'Usuário'}</Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.label}>Servidor conectado</Text>
        <Text style={styles.value}>{serverUrl}</Text>
      </View>

      <TouchableOpacity style={styles.logoutButton} onPress={confirmLogout}>
        <Text style={styles.logoutText}>Sair da conta</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, padding: 16 },
  title: { color: colors.text, fontSize: 22, fontWeight: '700', marginBottom: 16 },
  card: {
    backgroundColor: colors.surface,
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: colors.border,
  },
  label: { color: colors.textMuted, fontSize: 12, marginBottom: 4 },
  value: { color: colors.text, fontSize: 15, fontWeight: '600' },
  logoutButton: {
    backgroundColor: colors.danger,
    borderRadius: 10,
    padding: 14,
    alignItems: 'center',
    marginTop: 20,
  },
  logoutText: { color: '#0F172A', fontWeight: '700' },
});
