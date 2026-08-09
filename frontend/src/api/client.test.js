import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  EMAIL_VERIFICATION_REQUIRED,
  WS_CLOSE_NOT_YOUR_MATCH,
  WS_CLOSE_UNAUTHENTICATED,
  WS_CLOSE_VERIFICATION_REQUIRED,
  WS_TERMINAL_CLOSE_CODES,
  apiFetch,
  errorMessage,
  isVerificationBlocked,
  isVerificationErrorFrame,
  readJson,
  reportVerificationRequired,
  setVerificationRequiredHandler,
} from './client';
import { jsonResponse } from '../test-utils';

/**
 * The single choke point for the email-verification 403 (GAPS #25). Backend
 * contract, from app/dependencies.py:
 *
 *   403 {"detail": {"code": "email_verification_required",
 *                   "message": …, "grace_expired_at": <ISO8601>}}
 *
 * It only fires for accounts more than 72h past registration, so it cannot be
 * produced by hand — hence stubbed responses.
 */

const verificationDetail = {
  code: EMAIL_VERIFICATION_REQUIRED,
  message: 'Please verify your email address to keep swiping…',
  grace_expired_at: '2026-08-01T00:00:00+00:00',
};

afterEach(() => {
  setVerificationRequiredHandler(null);
});

describe('apiFetch verification detection', () => {
  it('reports the 403 and marks the response, without consuming its body', async () => {
    // Consuming the body would break every call site, which all read it for
    // their own error handling. The check has to clone.
    const handler = vi.fn();
    setVerificationRequiredHandler(handler);
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(403, { detail: verificationDetail })));

    const res = await apiFetch('/api/swipes', { method: 'POST' });

    expect(handler).toHaveBeenCalledWith(verificationDetail);
    expect(isVerificationBlocked(res)).toBe(true);
    await expect(res.json()).resolves.toEqual({ detail: verificationDetail });
  });

  it('passes the address in the body through to fetch with credentials', async () => {
    const spy = vi.fn(async () => jsonResponse(200, { message: 'ok' }));
    vi.stubGlobal('fetch', spy);

    await apiFetch('/api/auth/resend-verification', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'wolf@howl.app' }),
    });

    expect(spy).toHaveBeenCalledWith(
      '/api/auth/resend-verification',
      expect.objectContaining({ credentials: 'include', method: 'POST' }),
    );
  });

  it('ignores a 403 that is a different refusal', async () => {
    // Only this one code means "go verify". A generic 403 must not put the
    // whole app into the verification state.
    const handler = vi.fn();
    setVerificationRequiredHandler(handler);
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(403, { detail: 'Not allowed' })));

    const res = await apiFetch('/api/blocks', { method: 'POST' });

    expect(handler).not.toHaveBeenCalled();
    expect(isVerificationBlocked(res)).toBe(false);
  });

  it('ignores a 403 with a non-JSON body', async () => {
    // A proxy or gateway can produce an HTML 403; parsing must not throw.
    const handler = vi.fn();
    setVerificationRequiredHandler(handler);
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('<html>Forbidden</html>', { status: 403 })),
    );

    const res = await apiFetch('/api/swipes', { method: 'POST' });

    expect(handler).not.toHaveBeenCalled();
    expect(isVerificationBlocked(res)).toBe(false);
  });

  it('leaves other statuses alone', async () => {
    const handler = vi.fn();
    setVerificationRequiredHandler(handler);
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(429, { detail: { code: 'daily_limit_reached' } })));

    const res = await apiFetch('/api/swipes', { method: 'POST' });

    expect(handler).not.toHaveBeenCalled();
    expect(isVerificationBlocked(res)).toBe(false);
  });

  it('survives having no handler registered', async () => {
    // The provider registers on mount; a request in flight before that must not
    // throw on a null handler.
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(403, { detail: verificationDetail })));
    await expect(apiFetch('/api/swipes', { method: 'POST' })).resolves.toBeDefined();
  });

  it('unregisters the previous handler when a new one is set', async () => {
    const first = vi.fn();
    const second = vi.fn();
    setVerificationRequiredHandler(first);
    setVerificationRequiredHandler(second);
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(403, { detail: verificationDetail })));

    await apiFetch('/api/swipes', { method: 'POST' });

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledOnce();
  });
});

describe('WebSocket verification form', () => {
  it('recognises the error frame the socket sends before closing', () => {
    expect(
      isVerificationErrorFrame({ type: 'error', error: verificationDetail }),
    ).toBe(true);
  });

  it('does not mistake other frames for it', () => {
    expect(isVerificationErrorFrame({ type: 'new_message', message: {} })).toBe(false);
    expect(isVerificationErrorFrame({ type: 'error', error: { code: 'nope' } })).toBe(false);
    expect(isVerificationErrorFrame(null)).toBe(false);
    expect(isVerificationErrorFrame(undefined)).toBe(false);
  });

  it('treats 4403 as terminal along with 4001 and 4003', () => {
    // All three are decisions about this identity and this match: a retry gets
    // the same answer. Reconnecting on 4403 every 2.5s would hammer the server
    // for as long as the tab stays open.
    expect(WS_TERMINAL_CLOSE_CODES.has(WS_CLOSE_VERIFICATION_REQUIRED)).toBe(true);
    expect(WS_TERMINAL_CLOSE_CODES.has(WS_CLOSE_UNAUTHENTICATED)).toBe(true);
    expect(WS_TERMINAL_CLOSE_CODES.has(WS_CLOSE_NOT_YOUR_MATCH)).toBe(true);
  });

  it('does not treat a transient close as terminal', () => {
    // 1000 normal, 1006 abnormal (what a dropped network looks like), 1012
    // server restart. These are exactly the cases reconnect exists for.
    for (const code of [1000, 1001, 1006, 1011, 1012]) {
      expect(WS_TERMINAL_CLOSE_CODES.has(code)).toBe(false);
    }
  });

  it('pins the close code to the backend constant', () => {
    // app/dependencies.py: WS_EMAIL_VERIFICATION_REQUIRED = 4403
    expect(WS_CLOSE_VERIFICATION_REQUIRED).toBe(4403);
  });

  it('routes a socket-originated block to the same handler as a 403', () => {
    const handler = vi.fn();
    setVerificationRequiredHandler(handler);
    reportVerificationRequired(verificationDetail);
    expect(handler).toHaveBeenCalledWith(verificationDetail);
  });

  it('falls back to a bare code when the frame carries no detail', () => {
    const handler = vi.fn();
    setVerificationRequiredHandler(handler);
    reportVerificationRequired(undefined);
    expect(handler).toHaveBeenCalledWith({ code: EMAIL_VERIFICATION_REQUIRED });
  });
});

describe('readJson', () => {
  it('returns null instead of throwing on a non-JSON body', async () => {
    expect(await readJson(new Response('nope', { status: 500 }))).toBeNull();
  });

  it('parses a JSON body', async () => {
    expect(await readJson(jsonResponse(200, { a: 1 }))).toEqual({ a: 1 });
  });
});

describe('errorMessage', () => {
  it('takes a string detail', () => {
    expect(errorMessage({ detail: 'Bad password' }, 'fallback')).toBe('Bad password');
  });

  it('takes the message out of a structured detail', () => {
    // daily_limit_reached / regeneration_limit_reached / email_verification_required
    // all use this shape.
    expect(errorMessage({ detail: { code: 'x', message: 'Slow down' } }, 'fallback')).toBe('Slow down');
  });

  it('falls back for a 422 field-error list rather than rendering an object', () => {
    // Rendering `detail` directly here is how React throws "Objects are not
    // valid as a React child".
    const body = { detail: [{ loc: ['body', 'email'], msg: 'invalid', type: 'value_error' }] };
    expect(errorMessage(body, 'fallback')).toBe('fallback');
  });

  it('falls back for an empty or missing body', () => {
    expect(errorMessage(null, 'fallback')).toBe('fallback');
    expect(errorMessage({}, 'fallback')).toBe('fallback');
  });
});
