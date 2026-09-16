import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import api, { extractErrorMessage } from '../services/api';
import {
  getServerUrl,
  setServerUrl as saveServerUrl,
  getToken,
  setToken as saveToken,
  getUser,
  setUser as saveUser,
  clearSession,
} from '../services/storage';
import { connectSocket, disconnectSocket } from '../services/socket';
import { registerForPushNotificationsAsync } from '../services/notifications';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [serverUrl, setServerUrlState] = useState(null);
  const [token, setTokenState] = useState(null);
  const [user, setUserState] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const [savedUrl, savedToken, savedUser] = await Promise.all([getServerUrl(), getToken(), getUser()]);
      setServerUrlState(savedUrl);
      setTokenState(savedToken);
      setUserState(savedUser);
      if (savedUrl && savedToken) {
        connectSocket(savedUrl, savedToken);
      }
      setLoading(false);
    })();
  }, []);

  const configureServer = useCallback(async (url) => {
    const clean = await saveServerUrl(url);
    setServerUrlState(clean);
    return clean;
  }, []);

  const afterAuth = useCallback(async (newToken, newUser) => {
    await saveToken(newToken);
    await saveUser(newUser);
    setTokenState(newToken);
    setUserState(newUser);

    const url = await getServerUrl();
    connectSocket(url, newToken);

    // Registra o dispositivo para push notifications (não bloqueia o login se falhar)
    try {
      const pushToken = await registerForPushNotificationsAsync();
      if (pushToken) {
        await api.post('/auth/push-token', { pushToken });
      }
    } catch (err) {
      console.warn('Não foi possível registrar push notifications:', err.message);
    }
  }, []);

  const login = useCallback(
    async (username, password) => {
      try {
        const { data } = await api.post('/auth/login', { username, password });
        await afterAuth(data.token, data.user);
        return { ok: true };
      } catch (err) {
        return { ok: false, error: extractErrorMessage(err) };
      }
    },
    [afterAuth]
  );

  const setupAdmin = useCallback(
    async (username, password, setupCode) => {
      try {
        const { data } = await api.post('/auth/setup', { username, password, setupCode });
        await afterAuth(data.token, data.user);
        return { ok: true };
      } catch (err) {
        return { ok: false, error: extractErrorMessage(err) };
      }
    },
    [afterAuth]
  );

  const logout = useCallback(async () => {
    disconnectSocket();
    await clearSession();
    setTokenState(null);
    setUserState(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{ serverUrl, token, user, loading, configureServer, login, setupAdmin, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth precisa ser usado dentro de um AuthProvider');
  return ctx;
}
