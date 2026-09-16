import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, KeyboardAvoidingView, Platform } from 'react-native';
import { useAuth } from '../context/AuthContext';
import { colors } from '../theme';

export default function ServerSetupScreen({ navigation }) {
  const { configureServer } = useAuth();
  const [url, setUrl] = useState('http://');
  const [error, setError] = useState('');

  async function handleContinue() {
    setError('');
    if (!/^https?:\/\/.+/.test(url.trim())) {
      setError('Digite uma URL válida, ex: http://192.168.0.10:3000');
      return;
    }
    await configureServer(url);
    navigation.replace('Login');
  }

  return (
    <KeyboardAvoidingView style={styles.container} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Text style={styles.title}>Conectar ao servidor</Text>
      <Text style={styles.subtitle}>
        Digite o endereço do seu servidor privado (o mesmo onde o backend está rodando).
      </Text>

      <TextInput
        style={styles.input}
        placeholder="http://meu-servidor.com:3000"
        placeholderTextColor={colors.textMuted}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        value={url}
        onChangeText={setUrl}
      />

      {!!error && <Text style={styles.error}>{error}</Text>}

      <TouchableOpacity style={styles.button} onPress={handleContinue}>
        <Text style={styles.buttonText}>Continuar</Text>
      </TouchableOpacity>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, padding: 24, justifyContent: 'center' },
  title: { color: colors.text, fontSize: 24, fontWeight: '700', marginBottom: 8 },
  subtitle: { color: colors.textMuted, fontSize: 14, marginBottom: 24, lineHeight: 20 },
  input: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    padding: 14,
    color: colors.text,
    fontSize: 16,
    marginBottom: 12,
  },
  error: { color: colors.danger, marginBottom: 12 },
  button: { backgroundColor: colors.primary, borderRadius: 10, padding: 16, alignItems: 'center', marginTop: 8 },
  buttonText: { color: '#0F172A', fontWeight: '700', fontSize: 16 },
});
