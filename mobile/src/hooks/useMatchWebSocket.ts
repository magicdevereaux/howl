import { useCallback, useEffect, useRef } from 'react';
import { AppState, AppStateStatus } from 'react-native';

import { API_URL } from '../api/client';
import { getAccessToken } from '../auth/storage';

// ── Event types ───────────────────────────────────────────────────────────────

export interface WsMessage {
  id: number;
  sender_id: number;
  content: string | null;
  created_at: string;
  read_at: string | null;
  deleted_at: string | null;
  is_mine: boolean;
}

export type WsEvent =
  | { type: 'new_message';    message: WsMessage }
  | { type: 'message_deleted'; message: WsMessage }
  | { type: 'typing';         user_name: string };

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * Manages a WebSocket connection to /api/matches/{matchId}/ws.
 *
 * - Authenticates via ?token= query param (mobile bearer auth).
 * - Reconnects after 2.5 s on unexpected close.
 * - Disconnects when the app goes to background; reconnects on foreground.
 * - Cleans up completely on component unmount.
 */
export function useMatchWebSocket(
  matchId: number,
  onEvent: (event: WsEvent) => void,
): { sendTyping: () => void } {
  const wsRef           = useRef<WebSocket | null>(null);
  const reconnectRef    = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isActiveRef     = useRef(true);
  // Keep onEvent stable in the closure without restarting the socket on every render
  const onEventRef      = useRef(onEvent);
  onEventRef.current    = onEvent;

  const clearReconnect = () => {
    if (reconnectRef.current) { clearTimeout(reconnectRef.current); reconnectRef.current = null; }
  };

  const connect = useCallback(async () => {
    if (!isActiveRef.current) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const token = await getAccessToken();
    if (!token) return;

    // Convert http(s):// → ws(s)://
    const wsBase = API_URL.replace(/^http/, 'ws');
    const url = `${wsBase}/api/matches/${matchId}/ws?token=${encodeURIComponent(token)}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => { clearReconnect(); };

    ws.onmessage = (e) => {
      try {
        onEventRef.current(JSON.parse(e.data) as WsEvent);
      } catch { /* ignore malformed frames */ }
    };

    ws.onerror = () => { ws.close(); };

    ws.onclose = () => {
      wsRef.current = null;
      if (!isActiveRef.current) return;
      clearReconnect();
      reconnectRef.current = setTimeout(connect, 2500);
    };
  }, [matchId]);

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  useEffect(() => {
    isActiveRef.current = true;
    connect();

    const sub = AppState.addEventListener('change', (state: AppStateStatus) => {
      if (state === 'active') {
        // Reconnect if socket dropped while backgrounded
        if (!wsRef.current || wsRef.current.readyState === WebSocket.CLOSED) {
          connect();
        }
      } else if (state === 'background') {
        // Close proactively to save battery; we'll reconnect on foreground
        clearReconnect();
        wsRef.current?.close();
        wsRef.current = null;
      }
    });

    return () => {
      isActiveRef.current = false;
      clearReconnect();
      wsRef.current?.close();
      wsRef.current = null;
      sub.remove();
    };
  }, [connect]);

  // ── Actions ───────────────────────────────────────────────────────────────

  const sendTyping = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'typing' }));
    }
  }, []);

  return { sendTyping };
}
