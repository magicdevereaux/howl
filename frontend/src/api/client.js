import { API_URL, fetchApi } from '../utils';

// ---------------------------------------------------------------------------
// The single place the client recognises "your email is not verified".
//
// The backend gates four write routes behind a 72-hour grace window:
//   POST   /api/swipes
//   DELETE /api/swipes/last
//   POST   /api/matches/{id}/messages
//   POST   /api/avatar/regenerate
// Each answers 403 with
//   {"detail": {"code": "email_verification_required",
//               "message": "...", "grace_expired_at": "<ISO8601>"}}
// Reads (discover, matches, message history, unread, profile, avatar status)
// and resend-verification / logout / account deletion are NOT gated.
//
// Every call goes through `apiFetch`, so the detection lives here rather than
// at eleven call sites. A response that was blocked is recorded in a WeakSet so
// callers can ask `isVerificationBlocked(res)` and skip their own generic
// "something failed" message — the global notice already explains it.
// ---------------------------------------------------------------------------

export const EMAIL_VERIFICATION_REQUIRED = 'email_verification_required';

// Application close codes used by /api/matches/{id}/ws.
export const WS_CLOSE_UNAUTHENTICATED = 4001;   // no/invalid credentials
export const WS_CLOSE_NOT_YOUR_MATCH = 4003;    // authenticated, wrong match
export const WS_CLOSE_VERIFICATION_REQUIRED = 4403;
// The server caps sockets per (user, match) and evicts the oldest when a newer
// one connects (GAPS-ROUND-2 #59). This tab lost its seat to another of our own
// — a second tab, or a socket the browser never tore down. Reconnecting would
// evict that newer socket and leave the two trading places forever.
export const WS_CLOSE_TOO_MANY_SOCKETS = 4004;

/**
 * Close codes that reconnecting cannot fix.
 *
 * The first three are decisions about *this* identity and *this* match, so a
 * retry produces the same answer. Retrying 4403 in particular would hammer the
 * server for as long as the tab stays open. 4004 is different in kind — the
 * refusal is about how many sockets we hold, not who we are — but retrying is
 * just as futile, and worse: it would evict the newer socket that replaced us
 * and start the two trading places indefinitely.
 */
export const WS_TERMINAL_CLOSE_CODES = new Set([
  WS_CLOSE_UNAUTHENTICATED,
  WS_CLOSE_NOT_YOUR_MATCH,
  WS_CLOSE_VERIFICATION_REQUIRED,
  WS_CLOSE_TOO_MANY_SOCKETS,
]);

let onVerificationRequired = null;

/**
 * Register the one listener that reacts to a verification block.
 * Returns an unsubscribe function. VerificationProvider owns this.
 */
export function setVerificationRequiredHandler(handler) {
  onVerificationRequired = handler;
  return () => {
    if (onVerificationRequired === handler) onVerificationRequired = null;
  };
}

/**
 * Report a block that did not arrive as an HTTP response — the chat WebSocket
 * sends `{type:'error', error:{code:'email_verification_required', ...}}` and
 * then closes with 4403.
 */
export function reportVerificationRequired(detail) {
  if (onVerificationRequired) {
    onVerificationRequired(detail || { code: EMAIL_VERIFICATION_REQUIRED });
  }
}

const blockedResponses = new WeakSet();

/** True when this response was the verification 403. */
export const isVerificationBlocked = (res) => !!res && blockedResponses.has(res);

/** True when this WS error frame is the verification block. */
export const isVerificationErrorFrame = (frame) =>
  frame?.type === 'error' && frame?.error?.code === EMAIL_VERIFICATION_REQUIRED;

async function detectVerificationBlock(res) {
  if (res?.status !== 403 || typeof res.clone !== 'function') return;
  let body = null;
  try {
    body = await res.clone().json();
  } catch {
    return; // a 403 with a non-JSON body is not this contract
  }
  const detail = body?.detail;
  if (detail?.code !== EMAIL_VERIFICATION_REQUIRED) return;
  blockedResponses.add(res);
  reportVerificationRequired(detail);
}

/**
 * `fetchApi` plus the API base URL and the verification check.
 *
 * Takes a server-relative path ('/api/...'); `API_URL` is empty in dev (the
 * Vite proxy makes everything same-origin) and the full backend origin in prod.
 */
export async function apiFetch(path, options = {}) {
  const res = await fetchApi(`${API_URL}${path}`, options);
  await detectVerificationBlock(res);
  return res;
}

/** JSON-body request. The Content-Type header was repeated at 14 call sites. */
export const apiSend = (path, method, body) =>
  apiFetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });

/** Parse a JSON body, or null. Error bodies are not always JSON. */
export const readJson = async (res) => {
  try {
    return await res.json();
  } catch {
    return null;
  }
};

/**
 * Pull a user-facing string out of a FastAPI error body.
 *
 * `detail` is a string for `HTTPException(detail="...")`, an object with a
 * `message` for the structured errors (daily_limit_reached,
 * regeneration_limit_reached, email_verification_required), and a list of
 * field errors for a 422.
 */
export const errorMessage = (body, fallback) => {
  const detail = body?.detail;
  if (typeof detail === 'string') return detail;
  if (typeof detail?.message === 'string') return detail.message;
  return fallback;
};
