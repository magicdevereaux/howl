import React from 'react';

export default function Nav({ view, setView, fetchDiscoverUsers, fetchMatches, handleLogout, totalUnread = 0 }) {
  const navButton = (label, targetView, fetchFn) => {
    const active = view === targetView;
    return (
      <button
        key={targetView}
        onClick={() => { setView(targetView); fetchFn && fetchFn(); }}
        style={{
          padding: '10px 20px',
          background: active ? 'var(--bg-card)' : 'rgba(255,255,255,0.08)',
          color: active ? 'var(--accent-hover)' : 'var(--text-primary)',
          border: active ? 'none' : '1px solid var(--border)',
          borderRadius: '8px',
          cursor: 'pointer',
          fontSize: '14px',
          fontWeight: active ? '600' : '500',
        }}
      >
        {label}
      </button>
    );
  };

  const matchesActive = view === 'matches';

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', marginBottom: '32px', flexWrap: 'wrap', gap: '12px' }}>
      <h1 style={{ fontSize: '32px', fontWeight: '700', color: 'var(--text-primary)' }}>Howl 🐺</h1>
      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
        {navButton('Discover', 'discover', fetchDiscoverUsers)}

        {/* Matches button with unread badge */}
        <div style={{ position: 'relative', display: 'inline-flex' }}>
          <button
            onClick={() => { setView('matches'); fetchMatches(); }}
            style={{
              padding: '10px 20px',
              background: matchesActive ? 'var(--bg-card)' : 'rgba(255,255,255,0.08)',
              color: matchesActive ? 'var(--accent-hover)' : 'var(--text-primary)',
              border: matchesActive ? 'none' : '1px solid var(--border)',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: matchesActive ? '600' : '500',
            }}
          >
            Matches ❤️
          </button>
          {totalUnread > 0 && (
            <span style={{
              position: 'absolute',
              top: '-6px',
              right: '-6px',
              background: 'var(--gold)',
              color: '#0D0B1A',
              borderRadius: '10px',
              fontSize: '11px',
              fontWeight: '700',
              padding: '2px 6px',
              minWidth: '18px',
              textAlign: 'center',
              lineHeight: '14px',
              pointerEvents: 'none',
            }}>
              {totalUnread > 99 ? '99+' : totalUnread}
            </span>
          )}
        </div>

        {navButton('My Profile', 'profile', null)}
        <button
          onClick={handleLogout}
          style={{ padding: '10px 20px', background: 'rgba(255,255,255,0.08)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: '8px', cursor: 'pointer', fontSize: '14px', fontWeight: '500' }}
        >
          Logout
        </button>
      </div>
    </div>
  );
}
