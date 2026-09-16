import { io } from 'socket.io-client';

let socket = null;

export function connectSocket(serverUrl, token) {
  if (socket) {
    socket.disconnect();
    socket = null;
  }
  socket = io(serverUrl, {
    auth: { token },
    transports: ['websocket'],
    reconnection: true,
  });
  return socket;
}

export function getSocket() {
  return socket;
}

export function disconnectSocket() {
  if (socket) {
    socket.disconnect();
    socket = null;
  }
}
