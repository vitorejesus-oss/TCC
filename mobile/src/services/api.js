import axios from 'axios';
import { getServerUrl, getToken } from './storage';

const api = axios.create({ timeout: 15000 });

// Preenche baseURL e Authorization em cada requisição, lendo sempre o valor
// mais atual salvo pelo usuário na tela de Configurações.
api.interceptors.request.use(async (config) => {
  const serverUrl = await getServerUrl();
  if (!serverUrl) {
    throw new Error('Nenhum servidor configurado. Configure o endereço do servidor primeiro.');
  }
  config.baseURL = `${serverUrl}/api`;

  const token = await getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export function extractErrorMessage(err) {
  if (err?.response?.data?.error) return err.response.data.error;
  if (err?.message) return err.message;
  return 'Erro desconhecido';
}

export default api;
