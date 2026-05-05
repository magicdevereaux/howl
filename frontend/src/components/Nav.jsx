import React from 'react';

export default function Nav({ view, setView, fetchDiscoverUsers, fetchMatches, handleLogout }) {
  const navButton = (label, targetView, fetchFn) => {
    const active = view === targetView;
    return (
      <button
        key={targetView}
        onClick={() => { setView(targetView); fetchFn && fetchFn(); }}
        style={{
          padding: '10px 20px',
          background: active ? 'white' : 'rgba(255,255,255,0.15)',
          color: active ? '#667eea' : 'white',
          border: active ? 'none' : '1px solid rgba(255,255,255,0.3)',
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

  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '32px', flexWrap: 'wrap', gap: '12px' }}>
      <h1 style={{ fontSize: '32px', fontWeight: '700', color: 'white' }}>Howl 🐺</h1>
      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
        {navButton('Discover', 'discover', fetchDiscoverUsers)}
        {navButton('Matches ❤️', 'matches', fetchMatches)}
        {navButton('My Profile', 'profile', null)}
        <button
          onClick={handleLogout}
          style={{ padding: '10px 20px', background: 'rgba(255,255,255,0.15)', color: 'white', border: '1px solid rgba(255,255,255,0.3)', borderRadius: '8px', cursor: 'pointer', fontSize: '14px', fontWeight: '500' }}
        >
          Logout
        </button>
      </div>
    </div>
  );
}
