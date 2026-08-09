import React from 'react';
import Nav from './Nav';
import { animalEmoji, avatarUrl } from '../utils';

export default function MatchesView({
  matches, matchesLoading, matchesError,
  fetchMatches, openChat, user,
  setView, handleOpenReport, navProps,
}) {
  return (
    <div style={{ minHeight: '100vh', background: 'var(--gradient-main)', padding: '40px 20px' }}>
      <div style={{ maxWidth: '800px', margin: '0 auto' }}>
        <Nav {...navProps} />

        <h2 style={{ color: 'var(--text-primary)', fontSize: '22px', fontWeight: '600', marginBottom: '8px' }}>Your Matches</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '14px', marginBottom: '28px' }}>Spirit animals that connected with yours</p>

        {matchesError && (
          <div style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border)', borderRadius: '12px', padding: '20px 24px', marginBottom: '20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px' }}>
            <p style={{ color: 'var(--text-primary)', fontSize: '14px', margin: 0 }}>⚠️ {matchesError}</p>
            <button
              onClick={fetchMatches}
              style={{ padding: '6px 16px', background: 'var(--accent)', color: 'white', border: 'none', borderRadius: '8px', fontSize: '13px', fontWeight: '600', cursor: 'pointer', flexShrink: 0 }}
            >
              Retry
            </button>
          </div>
        )}

        {matchesLoading ? (
          <div style={{ textAlign: 'center', color: 'var(--text-primary)', padding: '60px', fontSize: '18px' }}>
            <div style={{ fontSize: '48px', marginBottom: '16px' }} className="spinner">🐾</div>
            Loading matches…
          </div>
        ) : matches.length === 0 ? (
          <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '60px', background: 'rgba(255,255,255,0.04)', borderRadius: '16px' }}>
            <div style={{ fontSize: '48px', marginBottom: '16px' }}>❤️</div>
            <p style={{ fontSize: '18px', fontWeight: '600', color: 'var(--text-primary)' }}>No matches yet</p>
            <p style={{ fontSize: '14px', marginTop: '8px' }}>Go discover some spirit animals!</p>
            <button
              onClick={() => setView('discover')}
              style={{ marginTop: '20px', padding: '12px 28px', background: 'var(--accent)', color: 'white', border: 'none', borderRadius: '10px', fontWeight: '600', cursor: 'pointer', fontSize: '15px' }}
            >
              Discover People
            </button>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '16px' }}>
            {matches.map((m) => (
              <div
                key={m.id}
                onClick={() => openChat(m)}
                style={{ background: 'var(--bg-card)', borderRadius: '16px', overflow: 'hidden', boxShadow: '0 4px 20px rgba(0,0,0,0.3)', transition: 'transform 0.2s', cursor: 'pointer' }}
                onMouseEnter={(e) => e.currentTarget.style.transform = 'translateY(-4px)'}
                onMouseLeave={(e) => e.currentTarget.style.transform = 'translateY(0)'}
              >
                {/* Gold header: avatar + name + unread badge — gold is the match moment */}
                <div style={{ background: 'var(--gradient-gold)', padding: '24px', textAlign: 'center', position: 'relative' }}>
                  {m.unread_count > 0 && (
                    <div style={{ position: 'absolute', top: '12px', right: '12px', background: 'var(--bg-brand)', color: 'var(--gold)', borderRadius: '10px', fontSize: '11px', fontWeight: '700', padding: '2px 7px', minWidth: '18px', textAlign: 'center' }}>
                      {m.unread_count}
                    </div>
                  )}
                  <div style={{ fontSize: '56px', lineHeight: 1, marginBottom: '10px' }}>
                    {m.other_user.avatar_url ? (
                      <img src={avatarUrl(m.other_user.avatar_url)} alt="" style={{ width: '72px', height: '72px', borderRadius: '50%', objectFit: 'cover', border: '3px solid rgba(255,255,255,0.4)' }} onError={(e) => { e.target.style.display='none'; e.target.nextSibling.style.display='block'; }} />
                    ) : null}
                    <span style={{ display: m.other_user.avatar_url ? 'none' : 'block' }}>{animalEmoji(m.other_user.animal)}</span>
                  </div>
                  <h3 style={{ color: '#0D0B1A', fontSize: '19px', fontWeight: '500', margin: 0, fontFamily: 'var(--font-display)' }}>
                    {m.other_user.name || 'Anonymous'}
                  </h3>
                  <p style={{ fontSize: '14px', margin: '4px 0 0', fontFamily: 'var(--font-display)', fontStyle: 'italic', color: 'rgba(13,11,26,0.75)', fontWeight: '400' }}>
                    {m.other_user.animal ? m.other_user.animal.charAt(0).toUpperCase() + m.other_user.animal.slice(1) : ''}
                  </p>
                </div>
                {/* Footer: last message preview or match date + report */}
                <div style={{ padding: '12px 16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    {m.last_message ? (
                      <p style={{ color: 'var(--text-surface)', fontSize: '12px', margin: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        <span style={{ color: 'var(--text-disabled)' }}>
                          {m.last_message.sender_id === user?.id ? 'You: ' : ''}
                        </span>
                        {m.last_message.content}
                      </p>
                    ) : (
                      <p style={{ color: 'var(--text-disabled)', fontSize: '11px', margin: 0, textAlign: 'center' }}>
                        Matched {new Date(m.matched_at).toLocaleDateString()}
                      </p>
                    )}
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleOpenReport(m.other_user.id, m.other_user.name); }}
                    title="Report this user"
                    style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '14px', opacity: 0.35, flexShrink: 0, padding: '2px 4px' }}
                  >
                    🚩
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .spinner { display: inline-block; animation: spin 2s linear infinite; }
      `}</style>
    </div>
  );
}
