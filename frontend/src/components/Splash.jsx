import React from 'react';

/** Shown while the cookie session is being checked, and on a chat deep link
 *  while the match list loads. Deliberately the same paw spinner used by every
 *  other loading state in the app. */
export default function Splash({ label = 'Loading…' }) {
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        minHeight: '100vh',
        background: 'var(--gradient-main)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '12px',
        color: 'var(--text-secondary)',
      }}
    >
      <div style={{ fontSize: '48px' }} className="spinner">🐾</div>
      {label}
      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .spinner { display: inline-block; animation: spin 2s linear infinite; }
      `}</style>
    </div>
  );
}
