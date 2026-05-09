import React from 'react';
import Nav from './Nav';
import { animalEmoji, avatarUrl } from '../utils';

export default function DiscoverView({
  discoverUsers, discoverLoading, discoverError,
  swipeLoading, swipeError, canUndo, undoMessage,
  matchPopup, setMatchPopup, avatarStatus,
  handleSwipe, handleUndo, handleBlock, handleOpenReport, fetchDiscoverUsers,
  setView, fetchMatches, navProps,
}) {
  const [blockConfirm, setBlockConfirm] = React.useState(false);
  const currentCard = discoverUsers[0] || null;

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', padding: '40px 20px' }}>
      <div style={{ maxWidth: '520px', margin: '0 auto' }}>
        <Nav {...navProps} />

        {discoverLoading ? (
          <div style={{ textAlign: 'center', color: 'white', padding: '60px', fontSize: '18px' }}>
            <div style={{ fontSize: '48px', marginBottom: '16px' }} className="spinner">🐾</div>
            Finding spirit animals…
          </div>
        ) : discoverError ? (
          <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', color: '#c53030' }}>{discoverError}</div>
        ) : !currentCard ? (
          <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.9)', padding: '60px', background: 'rgba(255,255,255,0.12)', borderRadius: '20px' }}>
            <div style={{ fontSize: '56px', marginBottom: '16px' }}>🎉</div>
            <p style={{ fontSize: '20px', fontWeight: '700' }}>You've seen everyone!</p>
            <p style={{ fontSize: '14px', marginTop: '8px', opacity: 0.8 }}>Check back later for new members.</p>
            <button
              onClick={fetchDiscoverUsers}
              style={{ marginTop: '20px', padding: '12px 28px', background: 'white', color: '#667eea', border: 'none', borderRadius: '10px', fontWeight: '600', cursor: 'pointer', fontSize: '15px' }}
            >
              Refresh
            </button>
          </div>
        ) : (
          <>
            <p style={{ color: 'rgba(255,255,255,0.7)', fontSize: '13px', marginBottom: '16px', textAlign: 'center' }}>
              {discoverUsers.length} {discoverUsers.length === 1 ? 'person' : 'people'} left
            </p>

            {/* Card */}
            <div style={{ background: 'white', borderRadius: '20px', overflow: 'hidden', boxShadow: '0 16px 48px rgba(0,0,0,0.25)' }}>
              <div style={{ background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', padding: '40px 28px 28px', textAlign: 'center' }}>
                {currentCard.avatar_url ? (
                  <img
                    src={avatarUrl(currentCard.avatar_url)}
                    alt={`${currentCard.name || 'User'}'s avatar`}
                    onError={(e) => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'block'; }}
                    style={{ width: '112px', height: '112px', borderRadius: '50%', objectFit: 'cover', marginBottom: '16px', border: '4px solid rgba(255,255,255,0.4)' }}
                  />
                ) : null}
                <div style={{ fontSize: '88px', lineHeight: 1, marginBottom: '16px', display: currentCard.avatar_url ? 'none' : 'block' }}>
                  {animalEmoji(currentCard.animal)}
                </div>
                <h2 style={{ color: 'white', fontSize: '26px', fontWeight: '700', margin: '0 0 4px' }}>
                  {currentCard.name || 'Anonymous'}
                </h2>
                <p style={{ color: 'rgba(255,255,255,0.9)', fontSize: '16px', margin: 0 }}>
                  {currentCard.animal ? currentCard.animal.charAt(0).toUpperCase() + currentCard.animal.slice(1) : ''}
                </p>
                {currentCard.location && (
                  <p style={{ color: 'rgba(255,255,255,0.75)', fontSize: '13px', marginTop: '8px' }}>
                    📍 {currentCard.location}
                  </p>
                )}
              </div>

              <div style={{ padding: '24px 28px 28px' }}>
                {currentCard.bio && (
                  <p style={{ color: '#4a5568', fontSize: '15px', lineHeight: '1.65', marginBottom: '16px' }}>
                    {currentCard.bio.length > 200 ? currentCard.bio.slice(0, 200).trimEnd() + '…' : currentCard.bio}
                  </p>
                )}
                {currentCard.personality_traits?.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '16px' }}>
                    {currentCard.personality_traits.map((trait, i) => (
                      <span key={i} style={{ background: '#eef2ff', color: '#667eea', padding: '4px 12px', borderRadius: '12px', fontSize: '13px', fontWeight: '500' }}>
                        {trait}
                      </span>
                    ))}
                  </div>
                )}
                {currentCard.avatar_description && (
                  <details style={{ marginBottom: '8px' }}>
                    <summary style={{ cursor: 'pointer', color: '#667eea', fontSize: '13px', fontWeight: '500', userSelect: 'none', listStyle: 'none' }}>
                      ✦ View spirit animal description
                    </summary>
                    <p style={{ marginTop: '10px', color: '#718096', fontSize: '13px', lineHeight: '1.6', padding: '10px 12px', background: '#f7fafc', borderRadius: '8px' }}>
                      {currentCard.avatar_description}
                    </p>
                  </details>
                )}
              </div>
            </div>

            {/* Swipe buttons */}
            <div style={{ display: 'flex', justifyContent: 'center', gap: '24px', marginTop: '28px' }}>
              <button
                disabled={swipeLoading}
                onClick={() => handleSwipe(currentCard.id, 'pass')}
                style={{ width: '72px', height: '72px', borderRadius: '50%', background: 'white', border: '2px solid #fed7d7', fontSize: '28px', cursor: swipeLoading ? 'not-allowed' : 'pointer', boxShadow: '0 4px 16px rgba(0,0,0,0.15)', transition: 'transform 0.15s, box-shadow 0.15s', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                onMouseEnter={(e) => !swipeLoading && (e.currentTarget.style.transform = 'scale(1.1)')}
                onMouseLeave={(e) => !swipeLoading && (e.currentTarget.style.transform = 'scale(1)')}
                title="Pass"
              >
                ❌
              </button>
              <button
                disabled={swipeLoading}
                onClick={() => handleSwipe(currentCard.id, 'like')}
                style={{ width: '72px', height: '72px', borderRadius: '50%', background: 'linear-gradient(135deg, #f687b3 0%, #ed64a6 100%)', border: 'none', fontSize: '28px', cursor: swipeLoading ? 'not-allowed' : 'pointer', boxShadow: '0 4px 16px rgba(237,100,166,0.4)', transition: 'transform 0.15s, box-shadow 0.15s', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                onMouseEnter={(e) => !swipeLoading && (e.currentTarget.style.transform = 'scale(1.1)')}
                onMouseLeave={(e) => !swipeLoading && (e.currentTarget.style.transform = 'scale(1)')}
                title="Like"
              >
                ❤️
              </button>
            </div>

            {/* Swipe error toast */}
            {swipeError && (
              <div style={{ textAlign: 'center', marginTop: '12px' }}>
                <span style={{ background: 'rgba(229,62,62,0.9)', color: 'white', fontSize: '13px', padding: '6px 16px', borderRadius: '20px' }}>
                  ⚠️ {swipeError}
                </span>
              </div>
            )}

            {/* Undo button — one-level, appears after first swipe */}
            <div style={{ textAlign: 'center', marginTop: '16px', minHeight: '32px' }}>
              {canUndo && (
                <button
                  disabled={swipeLoading}
                  onClick={handleUndo}
                  style={{ padding: '6px 18px', background: 'rgba(255,255,255,0.18)', color: 'white', border: '1px solid rgba(255,255,255,0.35)', borderRadius: '20px', fontSize: '13px', fontWeight: '500', cursor: swipeLoading ? 'not-allowed' : 'pointer', transition: 'background 0.15s', opacity: swipeLoading ? 0.5 : 1 }}
                  onMouseEnter={(e) => !swipeLoading && (e.currentTarget.style.background = 'rgba(255,255,255,0.28)')}
                  onMouseLeave={(e) => !swipeLoading && (e.currentTarget.style.background = 'rgba(255,255,255,0.18)')}
                >
                  ↩️ Undo
                </button>
              )}
              {undoMessage && (
                <p style={{ color: 'rgba(255,255,255,0.9)', fontSize: '13px', margin: 0 }}>{undoMessage}</p>
              )}
            </div>

            {/* Block button */}
            <div style={{ textAlign: 'center', marginTop: '12px' }}>
              {blockConfirm ? (
                <div style={{ display: 'inline-flex', gap: '8px', alignItems: 'center', background: 'rgba(0,0,0,0.3)', padding: '8px 16px', borderRadius: '20px' }}>
                  <span style={{ color: 'white', fontSize: '13px' }}>Block {currentCard.name || 'this user'}?</span>
                  <button onClick={() => setBlockConfirm(false)} style={{ background: 'rgba(255,255,255,0.2)', border: 'none', color: 'white', borderRadius: '6px', padding: '3px 10px', cursor: 'pointer', fontSize: '12px' }}>Cancel</button>
                  <button onClick={() => { setBlockConfirm(false); handleBlock(currentCard.id); }} style={{ background: '#c53030', border: 'none', color: 'white', borderRadius: '6px', padding: '3px 10px', cursor: 'pointer', fontSize: '12px', fontWeight: '600' }}>Block</button>
                </div>
              ) : (
                <button
                  onClick={() => setBlockConfirm(true)}
                  style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.4)', fontSize: '12px', cursor: 'pointer', textDecoration: 'underline' }}
                >
                  Block this person
                </button>
              )}
            </div>
            <div style={{ textAlign: 'center', marginTop: '6px' }}>
              <button
                onClick={() => handleOpenReport(currentCard.id, currentCard.name)}
                style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.3)', fontSize: '11px', cursor: 'pointer', textDecoration: 'underline' }}
              >
                Report this person
              </button>
            </div>
          </>
        )}
      </div>

      {/* Match popup */}
      {matchPopup && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }}>
          <div style={{ background: 'white', borderRadius: '24px', padding: '48px 40px', maxWidth: '360px', width: '100%', textAlign: 'center', boxShadow: '0 24px 64px rgba(0,0,0,0.4)' }}>
            <div style={{ fontSize: '48px', marginBottom: '8px' }}>🎉</div>
            <h2 style={{ fontSize: '28px', fontWeight: '800', color: '#2d3748', marginBottom: '8px' }}>It's a Match!</h2>
            <p style={{ color: '#718096', fontSize: '15px', marginBottom: '24px' }}>
              You and {matchPopup.other_user?.name || 'someone'} liked each other!
            </p>
            <div style={{ display: 'flex', justifyContent: 'center', gap: '16px', marginBottom: '28px', fontSize: '52px' }}>
              <span>{animalEmoji(avatarStatus?.animal)}</span>
              <span style={{ fontSize: '24px', alignSelf: 'center', color: '#ed64a6' }}>❤️</span>
              <span>{animalEmoji(matchPopup.other_user?.animal)}</span>
            </div>
            <button
              onClick={() => setMatchPopup(null)}
              style={{ width: '100%', padding: '14px', background: 'linear-gradient(135deg, #f687b3 0%, #ed64a6 100%)', color: 'white', border: 'none', borderRadius: '10px', fontSize: '16px', fontWeight: '700', cursor: 'pointer' }}
            >
              Keep Swiping
            </button>
            <button
              onClick={() => { setMatchPopup(null); setView('matches'); fetchMatches(); }}
              style={{ width: '100%', marginTop: '10px', padding: '12px', background: 'transparent', color: '#667eea', border: '2px solid #667eea', borderRadius: '10px', fontSize: '15px', fontWeight: '600', cursor: 'pointer' }}
            >
              View Matches
            </button>
          </div>
        </div>
      )}

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .spinner { display: inline-block; animation: spin 2s linear infinite; }
      `}</style>
    </div>
  );
}
