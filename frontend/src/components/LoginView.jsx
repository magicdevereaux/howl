import React from 'react';

export default function LoginView({
  email, setEmail, password, setPassword,
  error, loading, handleLogin, setView,
  setForgotEmail, setForgotDone, setError,
}) {
  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
      <div style={{ background: 'white', borderRadius: '16px', padding: '40px', maxWidth: '400px', width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }}>
        <h1 style={{ fontSize: '32px', fontWeight: '700', color: '#2d3748', marginBottom: '8px', textAlign: 'center' }}>Welcome to Howl 🐺</h1>
        <p style={{ color: '#718096', marginBottom: '32px', textAlign: 'center' }}>Sign in to find your spirit animal</p>
        {error && <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', marginBottom: '20px', color: '#c53030' }}>{error}</div>}
        <form onSubmit={handleLogin}>
          <div style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="wolf@howl.app" required style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#667eea'} onBlur={(e) => e.target.style.borderColor = '#e2e8f0'} />
          </div>
          <div style={{ marginBottom: '24px' }}>
            <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" required style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#667eea'} onBlur={(e) => e.target.style.borderColor = '#e2e8f0'} />
          </div>
          <button type="submit" disabled={loading} style={{ width: '100%', padding: '14px', background: loading ? '#a0aec0' : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', color: 'white', border: 'none', borderRadius: '8px', fontSize: '16px', fontWeight: '600', cursor: loading ? 'not-allowed' : 'pointer' }}>
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
        <p style={{ marginTop: '16px', textAlign: 'center', fontSize: '14px' }}>
          <button onClick={() => { setView('forgot-password'); setForgotEmail(''); setForgotDone(false); setError(''); }} style={{ color: '#718096', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: '14px' }}>
            Forgot password?
          </button>
        </p>
        <p style={{ marginTop: '8px', textAlign: 'center', color: '#718096', fontSize: '14px' }}>
          Don't have an account?{' '}
          <button onClick={() => setView('register')} style={{ color: '#667eea', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: '14px', fontWeight: '600' }}>Create one</button>
        </p>
        <div style={{ marginTop: '20px', paddingTop: '16px', borderTop: '1px solid #e2e8f0', textAlign: 'center' }}>
          <button onClick={() => setView('privacy')} style={{ color: '#a0aec0', background: 'none', border: 'none', cursor: 'pointer', fontSize: '12px' }}>Privacy Policy</button>
          <span style={{ color: '#e2e8f0', margin: '0 8px' }}>·</span>
          <button onClick={() => setView('terms')} style={{ color: '#a0aec0', background: 'none', border: 'none', cursor: 'pointer', fontSize: '12px' }}>Terms of Service</button>
        </div>
      </div>
    </div>
  );
}
