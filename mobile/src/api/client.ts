import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  saveAccessToken,
} from '../auth/storage';

// ── Base URL ──────────────────────────────────────────────────────────────────

// Android emulator needs 10.0.2.2 to reach the host machine's localhost.
// iOS simulator and physical devices (on the same network) use the LAN IP.
// Override this with your machine's local IP when testing on a real device:
//   EXPO_PUBLIC_API_URL=http://192.168.x.x:8001 npx expo start
const DEV_FALLBACK_API_URL = 'http://localhost:8001';

/**
 * A release build must never silently fall back to `localhost` — on a real
 * phone that resolves to the phone itself and every request fails with an
 * opaque network error. If `EXPO_PUBLIC_API_URL` is missing outside dev we
 * return an empty base URL and `api()` reports a configuration error instead,
 * which is diagnosable. `eas.json` sets the variable for every build profile.
 */
function resolveApiUrl(): string {
  const configured = process.env.EXPO_PUBLIC_API_URL?.trim();
  if (configured) return configured.replace(/\/+$/, '');
  return __DEV__ ? DEV_FALLBACK_API_URL : '';
}

export const API_URL = resolveApiUrl();

/** False when a release build was produced without `EXPO_PUBLIC_API_URL`. */
export const IS_API_CONFIGURED = API_URL.length > 0;

// ── Result type ───────────────────────────────────────────────────────────────

export interface ApiFailure {
  ok: false;
  error: string;
  status: number;
}

export type ApiResponse<T> = { data: T; ok: true } | ApiFailure;

/**
 * Synthetic statuses for failures that never reached an HTTP response. Real
 * HTTP statuses are always >= 100, so anything <= 0 is a transport problem.
 */
export const STATUS_OFFLINE = 0;
export const STATUS_TIMEOUT = -1;
export const STATUS_UNCONFIGURED = -2;
export const STATUS_BAD_PAYLOAD = -3;

/** True when the request never made it to the server (offline, DNS, timeout). */
export function isConnectivityError(status: number): boolean {
  return status === STATUS_OFFLINE || status === STATUS_TIMEOUT;
}

const OFFLINE_MESSAGE =
  "Can't reach Howl. Check your internet connection and try again.";
const TIMEOUT_MESSAGE = 'The request took too long. Check your connection and try again.';
const UNCONFIGURED_MESSAGE =
  'This build has no server address configured (EXPO_PUBLIC_API_URL). Please update the app.';
const BAD_PAYLOAD_MESSAGE = 'The server sent something unexpected. Please try again.';

// ── Session expiry callback ───────────────────────────────────────────────────

let _onUnauthenticated: (() => void) | null = null;

/** Register a callback that fires when the session is fully expired (no valid refresh). */
export function setUnauthenticatedHandler(fn: () => void) {
  _onUnauthenticated = fn;
}

// ── fetch with timeout, never throws ──────────────────────────────────────────

export type ApiOptions = RequestInit & {
  /** Abort the request after this many ms. Defaults to 15 s. */
  timeoutMs?: number;
};

const DEFAULT_TIMEOUT_MS = 15_000;

type FetchOutcome =
  | { ok: true; res: Response }
  | { ok: false; failure: ApiFailure };

/**
 * `fetch` wrapped so it resolves instead of rejecting. Airplane mode, DNS
 * failure, TLS failure and our own timeout all come back as an `ApiFailure`
 * value — the contract the rest of this client depends on.
 */
async function fetchSafely(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<FetchOutcome> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...init, signal: controller.signal });
    return { ok: true, res };
  } catch (err) {
    const timedOut = controller.signal.aborted;
    if (__DEV__) console.warn(`[api] ${init.method ?? 'GET'} ${url} failed:`, err);
    return {
      ok: false,
      failure: timedOut
        ? { ok: false, error: TIMEOUT_MESSAGE, status: STATUS_TIMEOUT }
        : { ok: false, error: OFFLINE_MESSAGE, status: STATUS_OFFLINE },
    };
  } finally {
    clearTimeout(timer);
  }
}

/** Read a JSON body without ever throwing. */
async function readJson(res: Response): Promise<{ ok: true; value: unknown } | { ok: false }> {
  try {
    return { ok: true, value: await res.json() };
  } catch {
    return { ok: false };
  }
}

// ── Token refresh ─────────────────────────────────────────────────────────────

export type RefreshOutcome =
  /** A fresh access token was issued and persisted. */
  | { kind: 'ok'; token: string }
  /** The refresh token is missing/expired/revoked — the session is over. */
  | { kind: 'invalid' }
  /** We could not reach the server; the session may still be fine. */
  | { kind: 'unreachable'; failure: ApiFailure };

let _refreshInFlight: Promise<RefreshOutcome> | null = null;

async function _doRefresh(): Promise<RefreshOutcome> {
  if (!IS_API_CONFIGURED) {
    return {
      kind: 'unreachable',
      failure: { ok: false, error: UNCONFIGURED_MESSAGE, status: STATUS_UNCONFIGURED },
    };
  }

  const refreshToken = await getRefreshToken();
  if (!refreshToken) return { kind: 'invalid' };

  const outcome = await fetchSafely(
    `${API_URL}/api/mobile/auth/refresh`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    },
    DEFAULT_TIMEOUT_MS,
  );

  // Transport failure: do NOT destroy the session over a dead subway tunnel.
  if (!outcome.ok) return { kind: 'unreachable', failure: outcome.failure };

  if (!outcome.res.ok) {
    // 5xx means the server is unhappy, not that our token is bad.
    if (outcome.res.status >= 500) {
      return {
        kind: 'unreachable',
        failure: {
          ok: false,
          error: 'Howl is having trouble right now. Please try again shortly.',
          status: outcome.res.status,
        },
      };
    }
    return { kind: 'invalid' };
  }

  const body = await readJson(outcome.res);
  const token =
    body.ok && typeof (body.value as { access_token?: unknown })?.access_token === 'string'
      ? (body.value as { access_token: string }).access_token
      : null;
  if (!token) return { kind: 'invalid' };

  // Persist the new access token (the refresh token stays the same).
  await saveAccessToken(token);
  return { kind: 'ok', token };
}

/**
 * Exchange the stored refresh token for a fresh access token.
 *
 * De-duplicated: concurrent callers (several screens 401-ing at once, or the
 * chat WebSocket reconnecting while a REST call is in flight) share one request.
 */
export function refreshAccessToken(): Promise<RefreshOutcome> {
  if (!_refreshInFlight) {
    _refreshInFlight = _doRefresh().finally(() => {
      _refreshInFlight = null;
    });
  }
  return _refreshInFlight;
}

/** Clear tokens and notify the app that the user has to sign in again. */
export async function endSession(): Promise<void> {
  await clearTokens();
  _onUnauthenticated?.();
}

// ── Main entry point ──────────────────────────────────────────────────────────

/**
 * Authenticated fetch wrapper. **Never throws** — every outcome, including
 * offline and timeout, is returned as a value:
 *   `{ ok: true, data }` | `{ ok: false, error, status }`
 *
 * - Attaches the Bearer token from SecureStore.
 * - On 401, attempts one token refresh then retries.
 * - On a refused refresh, clears tokens and calls the unauthenticated handler.
 *   A refresh that failed for network reasons leaves the session intact.
 */
export async function api<T = unknown>(
  path: string,
  options: ApiOptions = {},
  retry = true,
): Promise<ApiResponse<T>> {
  if (!IS_API_CONFIGURED) {
    return { ok: false, error: UNCONFIGURED_MESSAGE, status: STATUS_UNCONFIGURED };
  }

  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...init } = options;
  const token = await getAccessToken();

  const outcome = await fetchSafely(
    `${API_URL}${path}`,
    {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init.headers,
      },
    },
    timeoutMs,
  );

  if (!outcome.ok) return outcome.failure;
  const res = outcome.res;

  if (res.status === 401 && retry) {
    const refreshed = await refreshAccessToken();
    if (refreshed.kind === 'ok') {
      return api<T>(path, options, false);
    }
    if (refreshed.kind === 'unreachable') {
      // Keep the session; the user is offline, not signed out.
      return refreshed.failure;
    }
    await endSession();
    return { ok: false, error: 'Session expired', status: 401 };
  }

  if (!res.ok) {
    let error = `HTTP ${res.status}`;
    const body = await readJson(res);
    if (body.ok) {
      const detail = (body.value as { detail?: unknown })?.detail;
      if (typeof detail === 'string') error = detail;
    }
    if (res.status >= 500 && error === `HTTP ${res.status}`) {
      error = 'Howl is having trouble right now. Please try again shortly.';
    }
    return { ok: false, error, status: res.status };
  }

  if (res.status === 204) return { ok: true, data: null as T };

  const body = await readJson(res);
  if (!body.ok) {
    return { ok: false, error: BAD_PAYLOAD_MESSAGE, status: STATUS_BAD_PAYLOAD };
  }
  return { ok: true, data: body.value as T };
}
