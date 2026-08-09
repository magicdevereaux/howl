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
 * Three props, down from eleven.
 *
 * The email and password were `useState` on App, along with setters for the
 * forgot-password screen's email and its "sent" flag — App was holding the
 * contents of two other screens' form fields so that this one could reset them
 * on the way out. They are local now, and navigation is `<Link>`.
 *
 * `sessionError` stays a prop because it is not this form's error: it is
 * "Session expired. Please sign in again.", set when a background request 401s
 * somewhere else in the app. `onLogin` returns this attempt's own error.
 */
export default function LoginView({ onLogin, sessionError }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError('');
    const failure = await onLogin(email, password);
    setSubmitting(false);
    if (failure) setError(failure);
  };

  const shown = error || sessionError;

  return (
    <div style={{ minHeight: '100vh', background: 'var(--gradient-main)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
      <div style={{ background: 'var(--bg-card)', borderRadius: '16px', padding: '40px', maxWidth: '400px', width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
        <h1 style={{ fontSize: '34px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '8px', textAlign: 'center', fontFamily: 'var(--font-ceremonial)', letterSpacing: '0.04em' }}>Welcome to Howl 🐺</h1>
        <p style={{ color: 'var(--text-secondary)', marginBottom: '32px', textAlign: 'center', fontStyle: 'italic' }}>Sign in to find your spirit animal</p>
        {shown && <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', marginBottom: '20px', color: '#c53030' }}>{shown}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '20px' }}>
            <label htmlFor="login-email" style={{ display: 'block', marginBottom: '8px', color: 'var(--text-surface)', fontWeight: '500', fontSize: '14px' }}>Email</label>
            <input id="login-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="wolf@howl.app" required style={input} onFocus={focusColor} onBlur={blurColor} />
          </div>
          <div style={{ marginBottom: '24px' }}>
            <label htmlFor="login-password" style={{ display: 'block', marginBottom: '8px', color: 'var(--text-surface)', fontWeight: '500', fontSize: '14px' }}>Password</label>
            <input id="login-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" required style={input} onFocus={focusColor} onBlur={blurColor} />
          </div>
          <button type="submit" disabled={submitting} style={{ width: '100%', padding: '14px', background: submitting ? 'var(--bg-hover)' : 'var(--gradient-brand)', color: submitting ? 'var(--text-disabled)' : 'white', border: 'none', borderRadius: '8px', fontSize: '16px', fontWeight: '600', cursor: submitting ? 'not-allowed' : 'pointer' }}>
            {submitting ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
        <p style={{ marginTop: '16px', textAlign: 'center', fontSize: '14px' }}>
          <Link to={PATHS.forgotPassword} style={{ color: 'var(--text-secondary)', textDecoration: 'underline', fontSize: '14px' }}>
            Forgot password?
          </Link>
        </p>
        <p style={{ marginTop: '8px', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '14px' }}>
          Don't have an account?{' '}
          <Link to={PATHS.register} style={{ color: 'var(--accent-hover)', textDecoration: 'underline', fontSize: '14px', fontWeight: '600' }}>Create one</Link>
        </p>
        <div style={{ marginTop: '20px', paddingTop: '16px', borderTop: '1px solid var(--border)', textAlign: 'center' }}>
          <Link to={PATHS.privacy} style={{ color: 'var(--text-disabled)', fontSize: '12px' }}>Privacy Policy</Link>
          <span style={{ color: 'var(--border)', margin: '0 8px' }}>·</span>
          <Link to={PATHS.terms} style={{ color: 'var(--text-disabled)', fontSize: '12px' }}>Terms of Service</Link>
        </div>
      </div>
    </div>
  );
}
