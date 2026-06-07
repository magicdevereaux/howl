import { clearTokens, getAccessToken, getRefreshToken, saveTokens } from '../auth/storage';

// Android emulator needs 10.0.2.2 to reach the host machine's localhost.
// iOS simulator and physical devices (on the same network) use the LAN IP.
// Override this with your machine's local IP when testing on a real device.
export const API_URL = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8001';

type ApiResponse<T> = { data: T; ok: true } | { error: string; ok: false; status: number };

let _onUnauthenticated: (() => void) | null = null;

/** Register a callback that fires when the session is fully expired (no valid refresh). */
export function setUnauthenticatedHandler(fn: () => void) {
  _onUnauthenticated = fn;
}

async function _refreshAccessToken(): Promise<string | null> {
  const refreshToken = await getRefreshToken();
  if (!refreshToken) return null;

  try {
    const res = await fetch(`${API_URL}/api/mobile/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) return null;
    const json = await res.json();
    // Persist the new access token (refresh token stays the same)
    await saveTokens(json.access_token, refreshToken);
    return json.access_token as string;
  } catch {
    return null;
  }
}

/**
 * Authenticated fetch wrapper.
 * - Attaches Bearer token from SecureStore.
 * - On 401, attempts one token refresh then retries.
 * - On second 401 (refresh also failed), clears tokens and calls onUnauthenticated.
 */
export async function api<T = unknown>(
  path: string,
  options: RequestInit = {},
  retry = true,
): Promise<ApiResponse<T>> {
  const token = await getAccessToken();

  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });

  if (res.status === 401 && retry) {
    const newToken = await _refreshAccessToken();
    if (newToken) {
      return api<T>(path, options, false);
    }
    await clearTokens();
    _onUnauthenticated?.();
    return { ok: false, error: 'Session expired', status: 401 };
  }

  if (!res.ok) {
    let error = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      error = body?.detail ?? error;
    } catch { /* response wasn't JSON */ }
    return { ok: false, error, status: res.status };
  }

  const data = res.status === 204 ? (null as T) : await res.json() as T;
  return { ok: true, data };
}
