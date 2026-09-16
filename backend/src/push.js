/**
 * Envio de push notifications via Expo Push API.
 * Não requer nenhuma conta paga — funciona com o token gerado pelo próprio
 * app Expo no celular do usuário (expo-notifications).
 */

const EXPO_PUSH_URL = 'https://exp.host/--/api/v2/push/send';

async function sendExpoPush(tokens, { title, body, data }) {
  const validTokens = (tokens || []).filter((t) => typeof t === 'string' && t.startsWith('ExponentPushToken'));
  if (validTokens.length === 0) return;

  const messages = validTokens.map((to) => ({ to, title, body, data, sound: 'default' }));

  try {
    await fetch(EXPO_PUSH_URL, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Accept-Encoding': 'gzip, deflate',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(messages),
    });
  } catch (err) {
    console.error('[push] Falha ao enviar push notification:', err.message);
  }
}

module.exports = { sendExpoPush };
