import React, { useEffect, useState, useRef, useCallback } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  FlatList,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import api from '../services/api';
import { getSocket } from '../services/socket';
import { useAuth } from '../context/AuthContext';
import { colors } from '../theme';

export default function ChatScreen() {
  const { user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState('');
  const listRef = useRef(null);

  const loadHistory = useCallback(async () => {
    try {
      const { data } = await api.get('/messages');
      setMessages(data.messages);
    } catch (err) {
      // silencioso: o chat ainda funciona em tempo real via socket
    }
  }, []);

  useEffect(() => {
    loadHistory();

    const socket = getSocket();
    if (!socket) return;

    const onMessage = (message) => {
      setMessages((prev) => [...prev, message]);
    };
    socket.on('chat:message', onMessage);
    return () => socket.off('chat:message', onMessage);
  }, [loadHistory]);

  function sendMessage() {
    const trimmed = text.trim();
    if (!trimmed) return;

    const socket = getSocket();
    if (socket && socket.connected) {
      socket.emit('chat:send', { text: trimmed });
    } else {
      api.post('/messages', { text: trimmed }).catch(() => {});
    }
    setText('');
  }

  function renderItem({ item }) {
    const isMine = item.username === user?.username;
    return (
      <View style={[styles.bubbleRow, isMine ? styles.bubbleRowMine : styles.bubbleRowOther]}>
        <View style={[styles.bubble, isMine ? styles.bubbleMine : styles.bubbleOther]}>
          {!isMine && <Text style={styles.bubbleAuthor}>{item.username}</Text>}
          <Text style={isMine ? styles.bubbleTextMine : styles.bubbleText}>{item.text}</Text>
          <Text style={isMine ? styles.bubbleTimeMine : styles.bubbleTime}>
            {new Date(item.createdAt).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
          </Text>
        </View>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={90}
    >
      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={(item) => item.id}
        renderItem={renderItem}
        contentContainerStyle={{ padding: 12 }}
        onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: true })}
      />

      <View style={styles.inputRow}>
        <TextInput
          style={styles.input}
          placeholder="Digite uma mensagem..."
          placeholderTextColor={colors.textMuted}
          value={text}
          onChangeText={setText}
          onSubmitEditing={sendMessage}
        />
        <TouchableOpacity style={styles.sendButton} onPress={sendMessage}>
          <Text style={styles.sendButtonText}>Enviar</Text>
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  bubbleRow: { flexDirection: 'row', marginBottom: 8 },
  bubbleRowMine: { justifyContent: 'flex-end' },
  bubbleRowOther: { justifyContent: 'flex-start' },
  bubble: { maxWidth: '80%', borderRadius: 12, padding: 10 },
  bubbleMine: { backgroundColor: colors.primary },
  bubbleOther: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  bubbleAuthor: { color: colors.primary, fontSize: 11, fontWeight: '700', marginBottom: 2 },
  bubbleText: { color: colors.text, fontSize: 15 },
  bubbleTextMine: { color: '#0F172A', fontSize: 15 },
  bubbleTime: { color: colors.textMuted, fontSize: 10, marginTop: 4, textAlign: 'right' },
  bubbleTimeMine: { color: '#0F172A99', fontSize: 10, marginTop: 4, textAlign: 'right' },
  inputRow: {
    flexDirection: 'row',
    padding: 10,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.background,
  },
  input: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 10,
    color: colors.text,
    marginRight: 8,
  },
  sendButton: { backgroundColor: colors.primary, borderRadius: 20, paddingHorizontal: 18, justifyContent: 'center' },
  sendButtonText: { color: '#0F172A', fontWeight: '700' },
});
