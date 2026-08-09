import React, { useState } from 'react';

import { apiFetch, readJson } from '../api/client';
import { useEmailVerification } from '../contexts/EmailVerificationContext';

const DEFAULT_MESSAGE = 'Please verify your email address to keep swiping, messaging and generating avatars.';
const NO_EMAIL_MESSAGE = "Couldn't resend — sign in again and retry.";
const NETWORK_MESSAGE = "Couldn't reach the server — please try again.";

/**
 * The single "verify your email" surface, rendered once above the route table
 * so it appears no matter which action was refused (a swipe, an undo, a
 * message, an avatar regeneration, or the chat socket being rejected at
 * connect).
 *
 * Two things it deliberately does not do:
 *
 *  - it does not word its own success message. `POST /api/auth/resend-verification`
 *    answers generically on purpose — it never reveals whether an address is
 *    registered or already verified — so showing the server's own text keeps
 *    the two from drifting and keeps the non-disclosure property intact.
 *  - it does not infer state from the response. Rate-limited and
 *    already-verified look the same by design, so there is nothing to read.
 */
export default function EmailVerificationBanner() {
  const { info, dismiss, email } = useEmailVerification();
  const [sending, setSending] = useState(false);
  const [feedback, setFeedback] = useState('');

  if (!info) return null;

  const handleResend = async () => {
    if (!email) {
      setFeedback(NO_EMAIL_MESSAGE);
      return;
    }
    setSending(true);
    setFeedback('');
    try {
      // The address goes in the body rather than being derived from the
      // session, so this still works when the caller's own cookie is stale.
      const res = await apiFetch('/api/auth/resend-verification', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
      const body = await readJson(res);
      setFeedback(
        (typeof body?.message === 'string' && body.message) ||
          (res.ok ? 'Verification email sent.' : NETWORK_MESSAGE),
      );
    } catch {
      setFeedback(NETWORK_MESSAGE);
    } finally {
      setSending(false);
    }
  };

  return (
    <div
      role="alert"
      aria-live="polite"
      style={{
        background: 'rgba(201,168,76,0.16)',
        borderBottom: '1px solid var(--gold)',
        padding: '12px 20px',
        display: 'flex',
        alignItems: 'flex-start',
        gap: '12px',
      }}
    >
      <span style={{ fontSize: '18px', flexShrink: 0 }} aria-hidden="true">📧</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ color: 'var(--text-primary)', fontSize: '14px', margin: 0, lineHeight: '1.45' }}>
          {info.message || DEFAULT_MESSAGE}
        </p>
        {feedback ? (
          <p style={{ color: 'var(--text-secondary)', fontSize: '13px', margin: '6px 0 0', fontStyle: 'italic' }}>
            {feedback}
          </p>
        ) : (
          <button
            type="button"
            onClick={handleResend}
            disabled={sending}
            style={{
              marginTop: '4px',
              padding: 0,
              background: 'none',
              border: 'none',
              color: 'var(--gold)',
              fontSize: '13px',
              fontWeight: '700',
              textDecoration: 'underline',
              cursor: sending ? 'progress' : 'pointer',
            }}
          >
            {sending ? 'Sending…' : 'Resend verification email'}
          </button>
        )}
      </div>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss this notice"
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--text-secondary)',
          fontSize: '16px',
          fontWeight: '600',
          cursor: 'pointer',
          flexShrink: 0,
          lineHeight: 1,
        }}
      >
        ✕
      </button>
    </div>
  );
}
