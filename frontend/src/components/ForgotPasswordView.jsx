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
 * Half of what used to be PasswordReset, which took 18 props and switched on a
 * `view` string. Each half now has its own address, and owns the fields the
 * other never touched — an email address being typed into a form is not
 * application state, and it certainly is not App's.
 *
 * `onSubmit` returns an error string or null. The "sent" state is local because
 * nothing outside this screen can act on it.
 */
export default function ForgotPasswordView({ onSubmit }) {
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError('');
    const failure = await onSubmit(email);
    setSubmitting(false);
    if (failure) setError(failure);
    else setDone(true);
  };

  return (
    <div style={{ minHeight: '100vh', background: 'var(--gradient-main)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
      <div style={{ background: 'var(--bg-card)', borderRadius: '16px', padding: '40px', maxWidth: '400px', width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
        <h1 style={{ fontSize: '26px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '8px', textAlign: 'center' }}>Reset your password</h1>
        <p style={{ color: 'var(--text-secondary)', marginBottom: '28px', textAlign: 'center', fontSize: '14px' }}>
          Enter your email and we'll send you a reset link.
        </p>

        {done ? (
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '48px', marginBottom: '16px' }}>📬</div>
            <p style={{ color: 'var(--text-primary)', fontWeight: '600', marginBottom: '8px' }}>Check your inbox</p>
            <p style={{ color: 'var(--text-secondary)', fontSize: '13px', marginBottom: '24px' }}>
              If that address has an account, a reset link is on its way. The link expires in an hour.
            </p>
            <Link to={PATHS.login} style={{ color: 'var(--accent-hover)', textDecoration: 'underline', fontSize: '14px', fontWeight: '600' }}>
              Back to Sign In
            </Link>
          </div>
        ) : (
          <>
            {error && <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', marginBottom: '16px', color: '#c53030', fontSize: '13px' }}>{error}</div>}
            <form onSubmit={handleSubmit}>
              <div style={{ marginBottom: '20px' }}>
                <label htmlFor="forgot-email" style={{ display: 'block', marginBottom: '8px', color: 'var(--text-surface)', fontWeight: '500', fontSize: '14px' }}>Email</label>
                <input id="forgot-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="wolf@howl.app" required style={input} onFocus={focusColor} onBlur={blurColor} />
              </div>
              <button type="submit" disabled={submitting} style={{ width: '100%', padding: '14px', background: submitting ? 'var(--bg-hover)' : 'var(--gradient-brand)', color: submitting ? 'var(--text-disabled)' : 'white', border: 'none', borderRadius: '8px', fontSize: '16px', fontWeight: '600', cursor: submitting ? 'not-allowed' : 'pointer' }}>
                {submitting ? 'Sending…' : 'Send Reset Link'}
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
