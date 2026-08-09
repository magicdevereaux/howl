import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, AppStateStatus } from 'react-native';

import {
  API_URL,
  EMAIL_VERIFICATION_REQUIRED_CODE,
  IS_API_CONFIGURED,
  endSession,
  notifyEmailVerificationRequired,
  refreshAccessToken,
} from '../api/client';
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
  | { type: 'typing';         user_name: string }
  | { type: 'error';          error: { code: string; message: string; grace_expired_at?: string } }
  // Not yet sent by the server as of GAPS-ROUND-2 #49 — a backend agent is
  // adding it. Field names are the most likely shape given the docs ("match
  // id, the reader's user id, and a high-water-mark message id"); reconcile
  // at merge time if the backend lands on something else. Harmless if it
  // never arrives: onmessage only forwards recognised-looking frames and this
  // handler is additive.
  | { type: 'messages_read';  match_id?: number; user_id?: number; up_to_message_id?: number; read_at?: string }
  // Not yet sent mid-session by the server as of GAPS-ROUND-2 #60 (today it
  // only ever arrives via the 4003 close at connect time). The hook also
  // synthesises this event itself on a mid-session 4003 close, so the screen
  // reacts the same way regardless of whether the server sends a companion
  // frame before closing.
  | { type: 'match_closed';   match_id?: number; reason?: string };

/** Connection state, so the UI can tell the user why messages aren't arriving. */
export type WsStatus =
  | 'connecting'
  /** Live: messages arrive in real time. */
  | 'open'
  /** Disconnected, retrying with backoff. Sending still works over REST. */
  | 'reconnecting'
  /** Gave up: the session or this match is no longer usable over WS. */
  | 'closed';

// ── Close codes (see app/api/chat.py:171-197) ──────────────────────────────────

const CLOSE_UNAUTHENTICATED           = 4001; // missing/expired/invalid token
const CLOSE_FORBIDDEN                 = 4003; // not a participant in this match
const CLOSE_EMAIL_VERIFICATION_REQUIRED = 4403; // grace window over — terminal, see app/api/chat.py

const RECONNECT_BASE_MS = 2_500;
const RECONNECT_MAX_MS  = 30_000;
/** Refreshes per mount before we stop trying — prevents a refresh/close loop. */
const MAX_AUTH_REFRESHES = 2;

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * Manages a WebSocket connection to /api/matches/{matchId}/ws.
 *
 * - Authenticates via `?token=` query param (mobile bearer auth). See the note
 *   in the repo docs: query-string placement is a backend contract, not a
 *   client choice.
 * - On a 4001 close (expired access token) it refreshes the token and
 *   reconnects, instead of spinning forever on a token the server rejects.
 * - Reconnects with exponential backoff, capped, and resets on a good open.
 * - Disconnects when the app goes to background; reconnects on foreground.
 * - Cleans up completely on component unmount.
 */
export function useMatchWebSocket(
  matchId: number,
  onEvent: (event: WsEvent) => void,
): { sendTyping: () => void; status: WsStatus } {
  const wsRef           = useRef<WebSocket | null>(null);
  const reconnectRef    = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isActiveRef     = useRef(true);
  const attemptsRef     = useRef(0);
  const authRefreshRef  = useRef(0);
  // Keep onEvent stable in the closure without restarting the socket on every render
  const onEventRef      = useRef(onEvent);
  onEventRef.current    = onEvent;

  const [status, setStatus] = useState<WsStatus>('connecting');

  const clearReconnect = () => {
    if (reconnectRef.current) { clearTimeout(reconnectRef.current); reconnectRef.current = null; }
  };

  const connectRef = useRef<() => void>(() => {});

  /** Queue another attempt with exponential backoff. */
  const scheduleReconnect = useCallback((immediate = false) => {
    if (!isActiveRef.current) return;
    clearReconnect();
    const delay = immediate
      ? 0
      : Math.min(RECONNECT_BASE_MS * 2 ** attemptsRef.current, RECONNECT_MAX_MS);
    attemptsRef.current += 1;
    setStatus('reconnecting');
    reconnectRef.current = setTimeout(() => connectRef.current(), delay);
  }, []);

  const connect = useCallback(async () => {
    if (!isActiveRef.current) return;
    if (!IS_API_CONFIGURED || !Number.isFinite(matchId)) { setStatus('closed'); return; }
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const token = await getAccessToken();
    if (!isActiveRef.current) return;
    if (!token) { setStatus('closed'); return; }

    setStatus((prev) => (prev === 'open' ? prev : 'connecting'));

    // Convert http(s):// → ws(s)://
    const wsBase = API_URL.replace(/^http/, 'ws');
    const url = `${wsBase}/api/matches/${matchId}/ws?token=${encodeURIComponent(token)}`;

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch (err) {
      if (__DEV__) console.warn('[ws] could not open socket:', err);
      scheduleReconnect();
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      clearReconnect();
      attemptsRef.current = 0;
      setStatus('open');
    };

    ws.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data) as WsEvent;
        // The server sends this frame right before closing with 4403. Route
        // it through the same shared handler api() uses for the REST 403, so
        // the banner/screen shows regardless of which transport caught it.
        if (parsed.type === 'error' && parsed.error?.code === EMAIL_VERIFICATION_REQUIRED_CODE) {
          notifyEmailVerificationRequired({
            message: parsed.error.message,
            graceExpiredAt: parsed.error.grace_expired_at ?? null,
          });
        }
        onEventRef.current(parsed);
      } catch { /* ignore malformed frames */ }
    };

    // onerror fires before onclose; closing here funnels everything through
    // the single reconnect decision in onclose.
    ws.onerror = () => {
      try { ws.close(); } catch { /* already closing */ }
    };

    ws.onclose = (event) => {
      wsRef.current = null;
      const code = (event as { code?: number } | undefined)?.code;
      if (!isActiveRef.current) return;
      clearReconnect();

      if (code === CLOSE_FORBIDDEN) {
        // Blocked, unmatched, or never a participant — retrying cannot help.
        // Synthesise a match_closed event through the same channel a server
        // frame would use, so the screen reacts identically whether this
        // fires at connect time (the only case today) or mid-session (GAPS-
        // ROUND-2 #60, once a backend agent wires unmatch/block to close
        // live sockets) — with or without a companion JSON frame from the
        // server.
        onEventRef.current({ type: 'match_closed', reason: 'forbidden' });
        setStatus('closed');
        return;
      }

      if (code === CLOSE_EMAIL_VERIFICATION_REQUIRED) {
        // Terminal until the user verifies: reconnecting would just get the
        // same rejection every ~2.5s and hammer the server for nothing. The
        // error frame handled in onmessage above already raised the banner.
        setStatus('closed');
        return;
      }

      if (code === CLOSE_UNAUTHENTICATED) {
        if (authRefreshRef.current >= MAX_AUTH_REFRESHES) {
          setStatus('closed');
          return;
        }
        authRefreshRef.current += 1;
        setStatus('reconnecting');
        refreshAccessToken().then(async (outcome) => {
          if (!isActiveRef.current) return;
          if (outcome.kind === 'ok') {
            attemptsRef.current = 0;
            scheduleReconnect(true);
          } else if (outcome.kind === 'invalid') {
            // Session is genuinely over; let the app route to sign-in.
            setStatus('closed');
            await endSession();
          } else {
            // Offline — the token may well still be good. Back off and retry.
            scheduleReconnect();
          }
        });
        return;
      }

      scheduleReconnect();
    };
  }, [matchId, scheduleReconnect]);

  connectRef.current = () => { void connect(); };

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  useEffect(() => {
    isActiveRef.current = true;
    attemptsRef.current = 0;
    authRefreshRef.current = 0;
    void connect();

    const sub = AppState.addEventListener('change', (state: AppStateStatus) => {
      if (state === 'active') {
        // Reconnect if socket dropped while backgrounded
        if (!wsRef.current || wsRef.current.readyState === WebSocket.CLOSED) {
          attemptsRef.current = 0;
          void connect();
        }
      } else if (state === 'background') {
        // Close proactively to save battery; we'll reconnect on foreground.
        // Reflect that in `status` (rather than leaving a stale 'open'
        // behind) so the eventual reopen is a real connecting/reconnecting →
        // open edge the screen can detect and refetch on — otherwise this
        // deliberate close/reopen cycle is exactly the gap GAPS-ROUND-2 #47
        // describes: it manufactures a drop with no visible transition to
        // hang a refetch off of.
        clearReconnect();
        try { wsRef.current?.close(); } catch { /* already closing */ }
        wsRef.current = null;
        setStatus('reconnecting');
      }
    });

    return () => {
      isActiveRef.current = false;
      clearReconnect();
      try { wsRef.current?.close(); } catch { /* already closing */ }
      wsRef.current = null;
      sub.remove();
    };
  }, [connect]);

  // ── Actions ───────────────────────────────────────────────────────────────

  const sendTyping = useCallback(() => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return;
    try {
      wsRef.current.send(JSON.stringify({ type: 'typing' }));
    } catch {
      // Socket died between the readyState check and the send; the close
      // handler will take care of reconnecting.
    }
  }, []);

  return { sendTyping, status };
}
