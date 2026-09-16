import React, { useState } from 'react';
import {
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
  ScrollView,
} from 'react-native';
import { useAuth } from '../context/AuthContext';
import { colors } from '../theme';

export default function AdminSetupScreen({ navigation }) {
  const { setupAdmin } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [setupCode, setSetupCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function handleSetup() {
    setError('');
    if (!username || !password || !setupCode) {
      setError('Preencha todos os campos');
      return;
    }
    setLoading(true);
    const result = await setupAdmin(username, password, setupCode);
    setLoading(false);
    if (!result.ok) setError(result.error);
  }

  return (
    <KeyboardAvoidingView style={styles.container} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={{ flexGrow: 1, justifyContent: 'center' }}>
        <Text style={styles.title}>Criar conta de administrador</Text>
        <Text style={styles.subtitle}>
          Isso só funciona uma vez, na primeira vez que o servidor é configurado. O código de
          configuração é o valor definido em ADMIN_SETUP_CODE no arquivo .env do backend.
        </Text>

        <TextInput
          style={styles.input}
          placeholder="Usuário"
          placeholderTextColor={colors.textMuted}
          autoCapitalize="none"
          value={username}
          onChangeText={setUsername}
        />
        <TextInput
          style={styles.input}
          placeholder="Senha"
          placeholderTextColor={colors.textMuted}
          secureTextEntry
          value={password}
          onChangeText={setPassword}
        />
        <TextInput
          style={styles.input}
          placeholder="Código de configuração"
          placeholderTextColor={colors.textMuted}
          autoCapitalize="none"
          secureTextEntry
          value={setupCode}
          onChangeText={setSetupCode}
        />

        {!!error && <Text style={styles.error}>{error}</Text>}

        <TouchableOpacity style={styles.button} onPress={handleSetup} disabled={loading}>
          {loading ? <ActivityIndicator color="#0F172A" /> : <Text style={styles.buttonText}>Criar admin</Text>}
        </TouchableOpacity>

        <TouchableOpacity style={styles.linkButton} onPress={() => navigation.goBack()}>
          <Text style={styles.linkText}>Voltar para o login</Text>
        </TouchableOpacity>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, padding: 24 },
  title: { color: colors.text, fontSize: 22, fontWeight: '700', marginBottom: 8 },
  subtitle: { color: colors.textMuted, fontSize: 13, marginBottom: 20, lineHeight: 18 },
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
  linkButton: { marginTop: 16, alignItems: 'center' },
  linkText: { color: colors.primary, fontSize: 13 },
});
