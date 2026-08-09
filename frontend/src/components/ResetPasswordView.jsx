import React, { useState } from 'react';
import { Link } from 'react-router-dom';

import { PATHS } from '../routes/paths';

const input = {
  width: '100%', padding: '12px', border: '2px solid var(--border)',
  borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box',
};
const focusColor = (e) => { e.target.style.borderColor = '#6B3FA0'; };
const blurColor = (e) => { e.target.style.borderColor = 'rgba(255,255,255,0.1)'; };

/**
 * The other half of the old PasswordReset. Two props: the token from the emailed
 * link, and an action.
 *
 * The tokenless branch is not defensive padding — /reset-password has a real
 * address now, so it can be reached by typing it, by an email client that
 * stripped the query, or by a refresh after the token was spent. Without this
 * the form would POST an empty token and blame the user's link for expiring.
 */
export default function ResetPasswordView({ token, onSubmit }) {
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  const mismatch = !newPassword || newPassword !== confirmPassword;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    setSubmitting(true);
    setError('');
    const failure = await onSubmit(token, newPassword);
    setSubmitting(false);
    if (failure) {
      setError(failure);
    } else {
      setDone(true);
      setNewPassword('');
      setConfirmPassword('');
    }
  };

  return (
    <div style={{ minHeight: '100vh', background: 'var(--gradient-main)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
      <div style={{ background: 'var(--bg-card)', borderRadius: '16px', padding: '40px', maxWidth: '400px', width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
        <h1 style={{ fontSize: '26px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '8px', textAlign: 'center' }}>Set new password</h1>

        {!token && !done ? (
          <div style={{ textAlign: 'center', marginTop: '16px' }}>
            <div style={{ fontSize: '48px', marginBottom: '16px' }}>🔗</div>
            <p style={{ color: 'var(--text-primary)', fontWeight: '600', marginBottom: '8px' }}>This reset link is incomplete</p>
            <p style={{ color: 'var(--text-secondary)', fontSize: '13px', marginBottom: '24px', lineHeight: '1.5' }}>
              Open the link from your email directly, or request a new one.
            </p>
            <Link
              to={PATHS.forgotPassword}
              style={{ display: 'inline-block', padding: '12px 28px', background: 'var(--gradient-brand)', color: 'white', borderRadius: '8px', fontSize: '15px', fontWeight: '600', textDecoration: 'none' }}
            >
              Request a new link
            </Link>
            <p style={{ marginTop: '20px', textAlign: 'center', fontSize: '14px' }}>
              <Link to={PATHS.login} style={{ color: 'var(--text-secondary)', textDecoration: 'underline', fontSize: '14px' }}>
                Back to Sign In
              </Link>
            </p>
          </div>
        ) : done ? (
          <div style={{ textAlign: 'center', marginTop: '16px' }}>
            <div style={{ fontSize: '48px', marginBottom: '16px' }}>✅</div>
            <p style={{ color: 'var(--text-primary)', fontWeight: '600', marginBottom: '8px' }}>Password updated!</p>
            <p style={{ color: 'var(--text-secondary)', fontSize: '13px', marginBottom: '24px' }}>You can now log in with your new password.</p>
            <Link
              to={PATHS.login}
              style={{ display: 'inline-block', padding: '12px 28px', background: 'var(--gradient-brand)', color: 'white', borderRadius: '8px', fontSize: '15px', fontWeight: '600', textDecoration: 'none' }}
            >
              Go to Sign In
            </Link>
          </div>
        ) : (
          <>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '24px', textAlign: 'center', fontSize: '14px' }}>Choose a new password (8+ characters).</p>
            {error && <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', marginBottom: '16px', color: '#c53030', fontSize: '13px' }}>{error}</div>}
            <form onSubmit={handleSubmit}>
              <div style={{ marginBottom: '16px' }}>
                <label htmlFor="new-password" style={{ display: 'block', marginBottom: '8px', color: 'var(--text-surface)', fontWeight: '500', fontSize: '14px' }}>New password</label>
                <input id="new-password" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder="••••••••" required minLength={8} style={input} onFocus={focusColor} onBlur={blurColor} />
              </div>
              <div style={{ marginBottom: '24px' }}>
                <label htmlFor="confirm-password" style={{ display: 'block', marginBottom: '8px', color: 'var(--text-surface)', fontWeight: '500', fontSize: '14px' }}>Confirm password</label>
                <input id="confirm-password" type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder="••••••••" required minLength={8} style={input} onFocus={focusColor} onBlur={blurColor} />
              </div>
              <button type="submit" disabled={submitting || mismatch} style={{ width: '100%', padding: '14px', background: (submitting || mismatch) ? 'var(--bg-hover)' : 'var(--gradient-brand)', color: (submitting || mismatch) ? 'var(--text-disabled)' : 'white', border: 'none', borderRadius: '8px', fontSize: '16px', fontWeight: '600', cursor: (submitting || mismatch) ? 'not-allowed' : 'pointer' }}>
                {submitting ? 'Resetting…' : 'Reset Password'}
              </button>
            </form>
            <p style={{ marginTop: '20px', textAlign: 'center', fontSize: '14px' }}>
              <Link to={PATHS.login} style={{ color: 'var(--text-secondary)', textDecoration: 'underline', fontSize: '14px' }}>
                Back to Sign In
              </Link>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
