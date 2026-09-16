import AsyncStorage from '@react-native-async-storage/async-storage';

const KEYS = {
  SERVER_URL: '@servidor_privado/server_url',
  TOKEN: '@servidor_privado/token',
  USER: '@servidor_privado/user',
};

export async function getServerUrl() {
  return AsyncStorage.getItem(KEYS.SERVER_URL);
}

export async function setServerUrl(url) {
  // Remove barra final para evitar "//api" nas requisições
  const clean = (url || '').trim().replace(/\/+$/, '');
  await AsyncStorage.setItem(KEYS.SERVER_URL, clean);
  return clean;
}

export async function getToken() {
  return AsyncStorage.getItem(KEYS.TOKEN);
}

export async function setToken(token) {
  if (token) {
    await AsyncStorage.setItem(KEYS.TOKEN, token);
  } else {
    await AsyncStorage.removeItem(KEYS.TOKEN);
  }
}

export async function getUser() {
  const raw = await AsyncStorage.getItem(KEYS.USER);
  return raw ? JSON.parse(raw) : null;
}

export async function setUser(user) {
  if (user) {
    await AsyncStorage.setItem(KEYS.USER, JSON.stringify(user));
  } else {
    await AsyncStorage.removeItem(KEYS.USER);
  }
}

export async function clearSession() {
  await AsyncStorage.multiRemove([KEYS.TOKEN, KEYS.USER]);
}
