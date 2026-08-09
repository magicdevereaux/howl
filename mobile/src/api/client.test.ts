/**
 * Contract tests for the mobile API client (GAPS #29, guarding GAPS #13).
 *
 * These deliberately test the *contract* rather than the implementation, because
 * the load-bearing rule in mobile/CLAUDE.md is that errors on this client are
 * values, not exceptions: `api()` returns `{ok:true,data} | {ok:false,error,status}`
 * and every call site checks `.ok`. If a future change makes `api()` throw on a
 * network failure, every one of those call sites becomes an unhandled rejection —
 * which is exactly the bug #13 fixed.
 *
 * So the single most important assertion in this file is "it does not throw".
 */

import {
  api,
  EMAIL_VERIFICATION_REQUIRED_CODE,
  isConnectivityError,
  isEmailVerificationRequired,
  setEmailVerificationRequiredHandler,
  STATUS_BAD_PAYLOAD,
  STATUS_OFFLINE,
  STATUS_TIMEOUT,
} from './client';

const realFetch = global.fetch;

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
    headers: new Map() as unknown as Headers,
  } as unknown as Response;
}

afterEach(() => {
  global.fetch = realFetch;
});

describe('the ok/error union', () => {
  it('returns {ok:true, data} on success', async () => {
    global.fetch = jest.fn().mockResolvedValue(jsonResponse({ id: 7, name: 'Wolf' }));

    const res = await api<{ id: number; name: string }>('/api/profile/me');

    expect(res.ok).toBe(true);
    if (res.ok) {
      expect(res.data).toEqual({ id: 7, name: 'Wolf' });
    }
  });

  it('returns {ok:false} with the HTTP status on a 4xx', async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue(jsonResponse({ detail: 'Already swiped on this user.' }, 409));

    const res = await api('/api/swipes', { method: 'POST' });

    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.status).toBe(409);
      expect(res.error).toContain('Already swiped');
    }
  });
});

describe('never throws — the whole point of #13', () => {
  it('resolves instead of rejecting when the device is offline', async () => {
    // Airplane mode: fetch rejects with a TypeError. Previously this propagated
    // out of every un-awaited call site as an unhandled rejection.
    global.fetch = jest.fn().mockRejectedValue(new TypeError('Network request failed'));

    const res = await expect(api('/api/profile/me')).resolves.toBeDefined().then(
      () => api('/api/profile/me'),
    );

    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.status).toBe(STATUS_OFFLINE);
      expect(res.error).toBeTruthy();
      // The message reaches a user, so it must not be a raw TypeError string.
      expect(res.error).not.toContain('TypeError');
    }
  });

  it('resolves when the response body is not JSON at all', async () => {
    // A proxy error page or an HTML 502 — .json() rejects.
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError('Unexpected token < in JSON');
      },
      text: async () => '<html>502</html>',
      headers: new Map() as unknown as Headers,
    } as unknown as Response);

    const res = await api('/api/profile/me');

    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.status).toBe(STATUS_BAD_PAYLOAD);
  });

  it('resolves when fetch rejects with a non-Error value', async () => {
    // Defensive: some RN polyfills reject with a string.
    global.fetch = jest.fn().mockRejectedValue('boom');

    const res = await api('/api/profile/me');

    expect(res.ok).toBe(false);
  });
});

describe('timeouts', () => {
  it('gives up rather than hanging forever', async () => {
    // A request that never settles used to leave the UI spinning indefinitely.
    global.fetch = jest.fn().mockImplementation(
      (_url: string, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            const err = new Error('Aborted');
            err.name = 'AbortError';
            reject(err);
          });
        }),
    );

    const res = await api('/api/profile/me', { timeoutMs: 10 });

    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.status).toBe(STATUS_TIMEOUT);
  });

  it('passes an AbortSignal to fetch so the socket is actually released', async () => {
    const spy = jest.fn().mockResolvedValue(jsonResponse({}));
    global.fetch = spy;

    await api('/api/profile/me');

    const init = spy.mock.calls[0][1] as RequestInit;
    expect(init.signal).toBeDefined();
  });
});

describe('email verification required (403)', () => {
  // Only fires past the 72h post-registration grace window, so it can't be
  // triggered by hand in a test — exercised here with a mocked response
  // matching the documented contract:
  //   HTTP 403, {"detail": {"code": "email_verification_required", "message": ..., "grace_expired_at": ...}}
  afterEach(() => setEmailVerificationRequiredHandler(null));

  it('surfaces a distinct, checkable code instead of a generic error string', async () => {
    global.fetch = jest.fn().mockResolvedValue(
      jsonResponse(
        {
          detail: {
            code: 'email_verification_required',
            message: 'Please verify your email to keep using Howl.',
            grace_expired_at: '2026-08-01T00:00:00Z',
          },
        },
        403,
      ),
    );

    const res = await api('/api/swipes', { method: 'POST' });

    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.status).toBe(403);
      expect(res.code).toBe(EMAIL_VERIFICATION_REQUIRED_CODE);
      expect(res.error).toBe('Please verify your email to keep using Howl.');
      expect(isEmailVerificationRequired(res)).toBe(true);
    }
  });

  it('notifies the shared handler so the banner shows regardless of call site', async () => {
    global.fetch = jest.fn().mockResolvedValue(
      jsonResponse(
        {
          detail: {
            code: 'email_verification_required',
            message: 'Please verify your email to keep using Howl.',
            grace_expired_at: '2026-08-01T00:00:00Z',
          },
        },
        403,
      ),
    );

    const handler = jest.fn();
    setEmailVerificationRequiredHandler(handler);

    await api('/api/matches/1/messages', { method: 'POST' });

    expect(handler).toHaveBeenCalledWith({
      message: 'Please verify your email to keep using Howl.',
      graceExpiredAt: '2026-08-01T00:00:00Z',
    });
  });

  it('does not confuse an ordinary 403 (no structured code) for verification-required', async () => {
    global.fetch = jest.fn().mockResolvedValue(
      jsonResponse({ detail: 'You are blocked from viewing this profile.' }, 403),
    );

    const handler = jest.fn();
    setEmailVerificationRequiredHandler(handler);

    const res = await api('/api/profile/999');

    expect(handler).not.toHaveBeenCalled();
    if (!res.ok) {
      expect(res.code).toBeUndefined();
      expect(isEmailVerificationRequired(res)).toBe(false);
    }
  });
});

describe('isConnectivityError', () => {
  it('separates "you are offline" from "the server said no"', () => {
    // The UI shows a retry affordance for one and a real message for the other.
    expect(isConnectivityError(STATUS_OFFLINE)).toBe(true);
    expect(isConnectivityError(STATUS_TIMEOUT)).toBe(true);
    expect(isConnectivityError(401)).toBe(false);
    expect(isConnectivityError(500)).toBe(false);
  });
});
