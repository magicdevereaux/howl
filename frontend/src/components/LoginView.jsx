import React from 'react';

export default function LoginView({
  email, setEmail, password, setPassword,
  error, loading, handleLogin, setView,
  setForgotEmail, setForgotDone, setError,
}) {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--gradient-main)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
      <div style={{ background: 'var(--bg-card)', borderRadius: '16px', padding: '40px', maxWidth: '400px', width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
        <h1 style={{ fontSize: '34px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '8px', textAlign: 'center', fontFamily: 'var(--font-ceremonial)', letterSpacing: '0.04em' }}>Welcome to Howl 🐺</h1>
        <p style={{ color: 'var(--text-secondary)', marginBottom: '32px', textAlign: 'center', fontStyle: 'italic' }}>Sign in to find your spirit animal</p>
        {error && <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', marginBottom: '20px', color: '#c53030' }}>{error}</div>}
        <form onSubmit={handleLogin}>
          <div style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-surface)', fontWeight: '500', fontSize: '14px' }}>Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="wolf@howl.app" required style={{ width: '100%', padding: '12px', border: '2px solid var(--border)', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#6B3FA0'} onBlur={(e) => e.target.style.borderColor = 'rgba(255,255,255,0.1)'} />
          </div>
          <div style={{ marginBottom: '24px' }}>
            <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-surface)', fontWeight: '500', fontSize: '14px' }}>Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" required style={{ width: '100%', padding: '12px', border: '2px solid var(--border)', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#6B3FA0'} onBlur={(e) => e.target.style.borderColor = 'rgba(255,255,255,0.1)'} />
          </div>
          <button type="submit" disabled={loading} style={{ width: '100%', padding: '14px', background: loading ? 'var(--bg-hover)' : 'var(--gradient-brand)', color: loading ? 'var(--text-disabled)' : 'white', border: 'none', borderRadius: '8px', fontSize: '16px', fontWeight: '600', cursor: loading ? 'not-allowed' : 'pointer' }}>
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
        <p style={{ marginTop: '16px', textAlign: 'center', fontSize: '14px' }}>
          <button onClick={() => { setView('forgot-password'); setForgotEmail(''); setForgotDone(false); setError(''); }} style={{ color: 'var(--text-secondary)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: '14px' }}>
            Forgot password?
          </button>
        </p>
        <p style={{ marginTop: '8px', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '14px' }}>
          Don't have an account?{' '}
          <button onClick={() => setView('register')} style={{ color: 'var(--accent-hover)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: '14px', fontWeight: '600' }}>Create one</button>
        </p>
        <div style={{ marginTop: '20px', paddingTop: '16px', borderTop: '1px solid var(--border)', textAlign: 'center' }}>
          <button onClick={() => setView('privacy')} style={{ color: 'var(--text-disabled)', background: 'none', border: 'none', cursor: 'pointer', fontSize: '12px' }}>Privacy Policy</button>
          <span style={{ color: 'var(--border)', margin: '0 8px' }}>·</span>
          <button onClick={() => setView('terms')} style={{ color: 'var(--text-disabled)', background: 'none', border: 'none', cursor: 'pointer', fontSize: '12px' }}>Terms of Service</button>
        </div>
      </div>
    </div>
  );
}
