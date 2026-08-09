import React from 'react';

export default function PasswordReset({
  view, setView,
  // forgot-password
  forgotEmail, setForgotEmail, forgotDone, error, loading, handleForgotPassword,
  // reset-password
  resetToken, setResetToken, newPassword, setNewPassword,
  confirmPassword, setConfirmPassword, resetDone, setResetDone,
  resetError, handleResetPassword,
}) {
  if (view === 'forgot-password') {
    return (
      <div style={{ minHeight: '100vh', background: 'var(--gradient-main)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
        <div style={{ background: 'var(--bg-card)', borderRadius: '16px', padding: '40px', maxWidth: '400px', width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
          <h1 style={{ fontSize: '26px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '8px', textAlign: 'center' }}>Reset your password</h1>
          <p style={{ color: 'var(--text-secondary)', marginBottom: '28px', textAlign: 'center', fontSize: '14px' }}>
            Enter your email and we'll send you a reset link.
          </p>

          {forgotDone ? (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '48px', marginBottom: '16px' }}>📬</div>
              <p style={{ color: 'var(--text-primary)', fontWeight: '600', marginBottom: '8px' }}>Check your server logs</p>
              <p style={{ color: 'var(--text-secondary)', fontSize: '13px', marginBottom: '24px' }}>
                (Email delivery goes to console in dev mode — copy the link from there.)
              </p>
              <button onClick={() => setView('login')} style={{ color: 'var(--accent-hover)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: '14px', fontWeight: '600' }}>
                Back to Sign In
              </button>
            </div>
          ) : (
            <>
              {error && <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', marginBottom: '16px', color: '#c53030', fontSize: '13px' }}>{error}</div>}
              <form onSubmit={handleForgotPassword}>
                <div style={{ marginBottom: '20px' }}>
                  <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-surface)', fontWeight: '500', fontSize: '14px' }}>Email</label>
                  <input type="email" value={forgotEmail} onChange={(e) => setForgotEmail(e.target.value)} placeholder="wolf@howl.app" required style={{ width: '100%', padding: '12px', border: '2px solid var(--border)', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#6B3FA0'} onBlur={(e) => e.target.style.borderColor = 'rgba(255,255,255,0.1)'} />
                </div>
                <button type="submit" disabled={loading} style={{ width: '100%', padding: '14px', background: loading ? 'var(--bg-hover)' : 'var(--gradient-brand)', color: loading ? 'var(--text-disabled)' : 'white', border: 'none', borderRadius: '8px', fontSize: '16px', fontWeight: '600', cursor: loading ? 'not-allowed' : 'pointer' }}>
                  {loading ? 'Sending…' : 'Send Reset Link'}
                </button>
              </form>
              <p style={{ marginTop: '20px', textAlign: 'center', fontSize: '14px' }}>
                <button onClick={() => setView('login')} style={{ color: 'var(--text-secondary)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: '14px' }}>
                  Back to Sign In
                </button>
              </p>
            </>
          )}
        </div>
      </div>
    );
  }

  // reset-password view
  return (
    <div style={{ minHeight: '100vh', background: 'var(--gradient-main)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
      <div style={{ background: 'var(--bg-card)', borderRadius: '16px', padding: '40px', maxWidth: '400px', width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
        <h1 style={{ fontSize: '26px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '8px', textAlign: 'center' }}>Set new password</h1>

        {/* No token: say so instead of offering a form that cannot work.
            `resetToken` was an unused prop until now, because this screen was
            only ever reachable by following a `?token=` link. /reset-password is
            a real URL now, so it can also be reached by typing it, by a link
            whose query got stripped by an email client, or by a refresh after
            the token was consumed — and the form would have POSTed an empty
            token and blamed the user's link for expiring. */}
        {!resetToken && !resetDone ? (
          <div style={{ textAlign: 'center', marginTop: '16px' }}>
            <div style={{ fontSize: '48px', marginBottom: '16px' }}>🔗</div>
            <p style={{ color: 'var(--text-primary)', fontWeight: '600', marginBottom: '8px' }}>This reset link is incomplete</p>
            <p style={{ color: 'var(--text-secondary)', fontSize: '13px', marginBottom: '24px', lineHeight: '1.5' }}>
              Open the link from your email directly, or request a new one.
            </p>
            <button
              onClick={() => setView('forgot-password')}
              style={{ padding: '12px 28px', background: 'var(--gradient-brand)', color: 'white', border: 'none', borderRadius: '8px', fontSize: '15px', fontWeight: '600', cursor: 'pointer' }}
            >
              Request a new link
            </button>
            <p style={{ marginTop: '20px', textAlign: 'center', fontSize: '14px' }}>
              <button onClick={() => setView('login')} style={{ color: 'var(--text-secondary)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: '14px' }}>
                Back to Sign In
              </button>
            </p>
          </div>
        ) : resetDone ? (
          <div style={{ textAlign: 'center', marginTop: '16px' }}>
            <div style={{ fontSize: '48px', marginBottom: '16px' }}>✅</div>
            <p style={{ color: 'var(--text-primary)', fontWeight: '600', marginBottom: '8px' }}>Password updated!</p>
            <p style={{ color: 'var(--text-secondary)', fontSize: '13px', marginBottom: '24px' }}>You can now log in with your new password.</p>
            <button
              onClick={() => { setView('login'); setResetDone(false); setResetToken(''); }}
              style={{ padding: '12px 28px', background: 'var(--gradient-brand)', color: 'white', border: 'none', borderRadius: '8px', fontSize: '15px', fontWeight: '600', cursor: 'pointer' }}
            >
              Go to Sign In
            </button>
          </div>
        ) : (
          <>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '24px', textAlign: 'center', fontSize: '14px' }}>Choose a new password (8+ characters).</p>
            {resetError && <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', marginBottom: '16px', color: '#c53030', fontSize: '13px' }}>{resetError}</div>}
            <form onSubmit={handleResetPassword}>
              <div style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-surface)', fontWeight: '500', fontSize: '14px' }}>New password</label>
                <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder="••••••••" required minLength={8} style={{ width: '100%', padding: '12px', border: '2px solid var(--border)', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#6B3FA0'} onBlur={(e) => e.target.style.borderColor = 'rgba(255,255,255,0.1)'} />
              </div>
              <div style={{ marginBottom: '24px' }}>
                <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-surface)', fontWeight: '500', fontSize: '14px' }}>Confirm password</label>
                <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder="••••••••" required minLength={8} style={{ width: '100%', padding: '12px', border: '2px solid var(--border)', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#6B3FA0'} onBlur={(e) => e.target.style.borderColor = 'rgba(255,255,255,0.1)'} />
              </div>
              <button type="submit" disabled={loading || !newPassword || newPassword !== confirmPassword} style={{ width: '100%', padding: '14px', background: (loading || !newPassword || newPassword !== confirmPassword) ? 'var(--bg-hover)' : 'var(--gradient-brand)', color: (loading || !newPassword || newPassword !== confirmPassword) ? 'var(--text-disabled)' : 'white', border: 'none', borderRadius: '8px', fontSize: '16px', fontWeight: '600', cursor: (loading || !newPassword || newPassword !== confirmPassword) ? 'not-allowed' : 'pointer' }}>
                {loading ? 'Resetting…' : 'Reset Password'}
              </button>
            </form>
            <p style={{ marginTop: '20px', textAlign: 'center', fontSize: '14px' }}>
              <button onClick={() => setView('login')} style={{ color: 'var(--text-secondary)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: '14px' }}>
                Back to Sign In
              </button>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
