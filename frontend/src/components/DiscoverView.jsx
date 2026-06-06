import React, { useEffect, useState } from 'react';
import Nav from './Nav';
import { animalEmoji, avatarUrl } from '../utils';

const filterSel = {
  width: '100%', padding: '8px 10px', border: 'none',
  borderRadius: '8px', fontSize: '13px', background: 'rgba(255,255,255,0.08)',
  color: 'var(--text-primary)', cursor: 'pointer', outline: 'none',
};
const filterInput = {
  width: '100%', padding: '8px 10px', border: 'none',
  borderRadius: '8px', fontSize: '13px', background: 'rgba(255,255,255,0.08)',
  color: 'var(--text-primary)', outline: 'none', boxSizing: 'border-box',
};

export default function DiscoverView({
  discoverUsers, discoverLoading, discoverError,
  swipeLoading, swipeError, canUndo, undoMessage,
  matchPopup, setMatchPopup, avatarStatus,
  preferenceFilters, handleSaveFilters,
  swipeLimitReached, swipesRemaining, swipesResetAt,
  handleSwipe, handleUndo, handleBlock, handleOpenReport, fetchDiscoverUsers,
  setView, fetchMatches, navProps,
}) {
  const [blockConfirm, setBlockConfirm] = React.useState(false);
  const [localFilters, setLocalFilters] = useState({
    lookingFor: '', gender: '', sexuality: '', agePrefMin: '', agePrefMax: '',
  });

  useEffect(() => {
    if (preferenceFilters) setLocalFilters(preferenceFilters);
  }, [
    preferenceFilters?.lookingFor,
    preferenceFilters?.gender,
    preferenceFilters?.sexuality,
    preferenceFilters?.agePrefMin,
    preferenceFilters?.agePrefMax,
  ]);

  const filtersActive = !!(
    localFilters.lookingFor || localFilters.gender ||
    localFilters.sexuality || localFilters.agePrefMin || localFilters.agePrefMax
  );

  const handleApply = () => handleSaveFilters(localFilters);
  const handleClear = () => {
    const cleared = { lookingFor: '', gender: '', sexuality: '', agePrefMin: '', agePrefMax: '' };
    setLocalFilters(cleared);
    handleSaveFilters(cleared);
  };

  const set = (key) => (e) => setLocalFilters((f) => ({ ...f, [key]: e.target.value }));

  const currentCard = discoverUsers[0] || null;

  return (
    <div style={{ minHeight: '100vh', background: 'var(--gradient-main)', padding: '40px 20px' }}>
      <div style={{ maxWidth: '520px', margin: '0 auto' }}>
        <Nav {...navProps} />

        {/* Preference filters */}
        <div style={{ background: 'rgba(0,0,0,0.3)', borderRadius: '14px', padding: '14px 16px', marginBottom: '18px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginBottom: '8px' }}>
            <div>
              <p style={{ color: 'var(--text-disabled)', fontSize: '10px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 4px' }}>Looking for</p>
              <select value={localFilters.lookingFor} onChange={set('lookingFor')} style={filterSel}>
                <option value="" style={{ background: '#1A1035' }}>Anyone</option>
                <option value="men" style={{ background: '#1A1035' }}>Men</option>
                <option value="women" style={{ background: '#1A1035' }}>Women</option>
                <option value="non-binary" style={{ background: '#1A1035' }}>Non-binary</option>
                <option value="everyone" style={{ background: '#1A1035' }}>Everyone</option>
              </select>
            </div>
            <div>
              <p style={{ color: 'var(--text-disabled)', fontSize: '10px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 4px' }}>Gender</p>
              <select value={localFilters.gender} onChange={set('gender')} style={filterSel}>
                <option value="" style={{ background: '#1A1035' }}>Any</option>
                <option value="man" style={{ background: '#1A1035' }}>Man</option>
                <option value="woman" style={{ background: '#1A1035' }}>Woman</option>
                <option value="non-binary" style={{ background: '#1A1035' }}>Non-binary</option>
                <option value="other" style={{ background: '#1A1035' }}>Other</option>
              </select>
            </div>
            <div>
              <p style={{ color: 'var(--text-disabled)', fontSize: '10px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 4px' }}>Sexuality</p>
              <select value={localFilters.sexuality} onChange={set('sexuality')} style={filterSel}>
                <option value="" style={{ background: '#1A1035' }}>Any</option>
                <option value="straight" style={{ background: '#1A1035' }}>Straight</option>
                <option value="gay" style={{ background: '#1A1035' }}>Gay</option>
                <option value="lesbian" style={{ background: '#1A1035' }}>Lesbian</option>
                <option value="bisexual" style={{ background: '#1A1035' }}>Bisexual</option>
                <option value="pansexual" style={{ background: '#1A1035' }}>Pansexual</option>
                <option value="other" style={{ background: '#1A1035' }}>Other</option>
              </select>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginBottom: '12px' }}>
            <div>
              <p style={{ color: 'var(--text-disabled)', fontSize: '10px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 4px' }}>Min age</p>
              <input type="number" value={localFilters.agePrefMin} onChange={set('agePrefMin')} placeholder="18" min={18} max={120} style={filterInput} />
            </div>
            <div>
              <p style={{ color: 'var(--text-disabled)', fontSize: '10px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 4px' }}>Max age</p>
              <input type="number" value={localFilters.agePrefMax} onChange={set('agePrefMax')} placeholder="99" min={18} max={120} style={filterInput} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', gap: '6px' }}>
              <button
                onClick={handleApply}
                style={{ padding: '8px 0', background: 'var(--accent)', color: 'white', border: 'none', borderRadius: '8px', fontSize: '13px', fontWeight: '700', cursor: 'pointer', width: '100%' }}
              >
                Apply
              </button>
              <button
                onClick={handleClear}
                style={{ padding: '4px 0', background: 'none', color: 'var(--text-disabled)', border: 'none', fontSize: '11px', cursor: 'pointer', textDecoration: 'underline', visibility: filtersActive ? 'visible' : 'hidden' }}
              >
                Clear all
              </button>
            </div>
          </div>
          {filtersActive && (
            <p style={{ color: 'var(--text-disabled)', fontSize: '11px', margin: 0, textAlign: 'center' }}>
              Filters active — results are narrowed to your preferences
            </p>
          )}
        </div>

        {swipeLimitReached ? (
          <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '48px 24px', background: 'rgba(255,255,255,0.04)', borderRadius: '20px' }}>
            <div style={{ fontSize: '56px', marginBottom: '16px' }}>🐾</div>
            <p style={{ fontSize: '20px', fontWeight: '700', marginBottom: '8px', color: 'var(--text-primary)' }}>You're out of swipes!</p>
            <p style={{ fontSize: '14px', opacity: 0.8, marginBottom: '4px' }}>
              You've used all 20 free swipes for today.
            </p>
            {swipesResetAt && (
              <p style={{ fontSize: '13px', opacity: 0.65, marginBottom: '20px' }}>
                Resets in ~{Math.ceil((new Date(swipesResetAt).getTime() + 86400000 - Date.now()) / 3600000)}h
              </p>
            )}
            <p style={{ fontSize: '13px', opacity: 0.7, fontStyle: 'italic' }}>
              Upgrade to premium for unlimited swiping.
            </p>
          </div>
        ) : discoverLoading ? (
          <div style={{ textAlign: 'center', color: 'var(--text-primary)', padding: '60px', fontSize: '18px' }}>
            <div style={{ fontSize: '48px', marginBottom: '16px' }} className="spinner">🐾</div>
            Finding spirit animals…
          </div>
        ) : discoverError ? (
          <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', color: '#c53030' }}>{discoverError}</div>
        ) : !currentCard ? (
          <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '60px', background: 'rgba(255,255,255,0.04)', borderRadius: '20px' }}>
            <div style={{ fontSize: '56px', marginBottom: '16px' }}>🎉</div>
            <p style={{ fontSize: '20px', fontWeight: '700', color: 'var(--text-primary)' }}>You've seen everyone!</p>
            <p style={{ fontSize: '14px', marginTop: '8px' }}>Check back later for new members.</p>
            <button
              onClick={fetchDiscoverUsers}
              style={{ marginTop: '20px', padding: '12px 28px', background: 'var(--accent)', color: 'white', border: 'none', borderRadius: '10px', fontWeight: '600', cursor: 'pointer', fontSize: '15px' }}
            >
              Refresh
            </button>
          </div>
        ) : (
          <>
            {swipesRemaining !== null && swipesRemaining <= 5 && (
              <div style={{ textAlign: 'right', marginBottom: '16px' }}>
                <p style={{ color: swipesRemaining <= 2 ? '#fc8181' : 'var(--text-disabled)', fontSize: '12px', fontWeight: '600', margin: 0 }}>
                  {swipesRemaining} swipe{swipesRemaining !== 1 ? 's' : ''} left today
                </p>
              </div>
            )}

            {/* Card */}
            <div style={{ background: 'var(--bg-card)', borderRadius: '20px', overflow: 'hidden', boxShadow: '0 16px 48px rgba(0,0,0,0.4)' }}>
              <div style={{ background: 'var(--gradient-brand)', padding: '40px 28px 28px', textAlign: 'center' }}>
                {currentCard.avatar_url ? (
                  <img
                    src={avatarUrl(currentCard.avatar_url)}
                    alt={`${currentCard.name || 'User'}'s avatar`}
                    onError={(e) => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'block'; }}
                    style={{ width: '112px', height: '112px', borderRadius: '50%', objectFit: 'cover', marginBottom: '16px', border: '4px solid rgba(255,255,255,0.25)' }}
                  />
                ) : null}
                <div style={{ fontSize: '88px', lineHeight: 1, marginBottom: '16px', display: currentCard.avatar_url ? 'none' : 'block' }}>
                  {animalEmoji(currentCard.animal)}
                </div>
                <h2 style={{ color: 'white', fontSize: '28px', fontWeight: '500', margin: '0 0 4px', fontFamily: 'var(--font-display)' }}>
                  {currentCard.name || 'Anonymous'}
                </h2>
                <p style={{ fontSize: '17px', margin: 0, fontFamily: 'var(--font-display)', fontStyle: 'italic', color: 'var(--gold)', fontWeight: '400' }}>
                  {currentCard.animal ? currentCard.animal.charAt(0).toUpperCase() + currentCard.animal.slice(1) : ''}
                </p>
                {currentCard.location && (
                  <p style={{ color: 'rgba(255,255,255,0.65)', fontSize: '13px', marginTop: '8px' }}>
                    📍 {currentCard.location}
                  </p>
                )}
              </div>

              <div style={{ padding: '24px 28px 28px' }}>
                {currentCard.bio && (
                  <p style={{ color: 'var(--text-surface)', fontSize: '15px', lineHeight: '1.65', marginBottom: '16px' }}>
                    {currentCard.bio.length > 200 ? currentCard.bio.slice(0, 200).trimEnd() + '…' : currentCard.bio}
                  </p>
                )}
                {currentCard.personality_traits?.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '16px' }}>
                    {currentCard.personality_traits.map((trait, i) => (
                      <span key={i} style={{ background: 'var(--bg-hover)', color: 'var(--text-secondary)', padding: '4px 12px', borderRadius: '12px', fontSize: '14px', fontFamily: 'var(--font-display)', fontStyle: 'italic', fontWeight: '400' }}>
                        {trait}
                      </span>
                    ))}
                  </div>
                )}
                {currentCard.avatar_description && (
                  <details style={{ marginBottom: '8px' }}>
                    <summary style={{ cursor: 'pointer', color: 'var(--accent-hover)', fontSize: '13px', fontWeight: '500', userSelect: 'none', listStyle: 'none' }}>
                      ✦ View spirit animal description
                    </summary>
                    <p style={{ marginTop: '10px', color: 'var(--text-secondary)', fontSize: '13px', lineHeight: '1.6', padding: '10px 12px', background: 'var(--bg-input)', borderRadius: '8px' }}>
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
                style={{ width: '72px', height: '72px', borderRadius: '50%', background: 'var(--bg-card)', border: '2px solid #fed7d7', fontSize: '28px', cursor: swipeLoading ? 'not-allowed' : 'pointer', boxShadow: '0 4px 16px rgba(0,0,0,0.3)', transition: 'transform 0.15s, box-shadow 0.15s', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
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

            {/* Undo button */}
            <div style={{ textAlign: 'center', marginTop: '16px', minHeight: '32px' }}>
              {canUndo && (
                <button
                  disabled={swipeLoading}
                  onClick={handleUndo}
                  style={{ padding: '6px 18px', background: 'rgba(255,255,255,0.08)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: '20px', fontSize: '13px', fontWeight: '500', cursor: swipeLoading ? 'not-allowed' : 'pointer', transition: 'background 0.15s', opacity: swipeLoading ? 0.5 : 1 }}
                  onMouseEnter={(e) => !swipeLoading && (e.currentTarget.style.background = 'rgba(255,255,255,0.14)')}
                  onMouseLeave={(e) => !swipeLoading && (e.currentTarget.style.background = 'rgba(255,255,255,0.08)')}
                >
                  ↩️ Undo
                </button>
              )}
              {undoMessage && (
                <p style={{ color: 'var(--text-secondary)', fontSize: '13px', margin: 0 }}>{undoMessage}</p>
              )}
            </div>

            {/* Block button */}
            <div style={{ textAlign: 'center', marginTop: '12px' }}>
              {blockConfirm ? (
                <div style={{ display: 'inline-flex', gap: '8px', alignItems: 'center', background: 'rgba(0,0,0,0.4)', padding: '8px 16px', borderRadius: '20px' }}>
                  <span style={{ color: 'var(--text-primary)', fontSize: '13px' }}>Block {currentCard.name || 'this user'}?</span>
                  <button onClick={() => setBlockConfirm(false)} style={{ background: 'rgba(255,255,255,0.1)', border: 'none', color: 'var(--text-primary)', borderRadius: '6px', padding: '3px 10px', cursor: 'pointer', fontSize: '12px' }}>Cancel</button>
                  <button onClick={() => { setBlockConfirm(false); handleBlock(currentCard.id); }} style={{ background: '#c53030', border: 'none', color: 'white', borderRadius: '6px', padding: '3px 10px', cursor: 'pointer', fontSize: '12px', fontWeight: '600' }}>Block</button>
                </div>
              ) : (
                <button
                  onClick={() => setBlockConfirm(true)}
                  style={{ background: 'none', border: 'none', color: 'var(--text-disabled)', fontSize: '12px', cursor: 'pointer', textDecoration: 'underline' }}
                >
                  Block this person
                </button>
              )}
            </div>
            <div style={{ textAlign: 'center', marginTop: '6px' }}>
              <button
                onClick={() => handleOpenReport(currentCard.id, currentCard.name)}
                style={{ background: 'none', border: 'none', color: 'var(--text-disabled)', fontSize: '11px', cursor: 'pointer', textDecoration: 'underline', opacity: 0.6 }}
              >
                Report this person
              </button>
            </div>
          </>
        )}
      </div>

      {/* Match popup — gold moment */}
      {matchPopup && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }}>
          <div style={{ background: 'var(--bg-card)', borderRadius: '24px', padding: '48px 40px', maxWidth: '360px', width: '100%', textAlign: 'center', boxShadow: '0 24px 64px rgba(0,0,0,0.6)' }}>
            <div style={{ fontSize: '48px', marginBottom: '8px' }}>🎉</div>
            <h2 style={{ fontSize: '32px', fontWeight: '700', color: 'var(--gold)', marginBottom: '8px', fontFamily: 'var(--font-ceremonial)', letterSpacing: '0.05em' }}>It's a Match!</h2>
            <p style={{ color: 'var(--text-secondary)', fontSize: '15px', marginBottom: '24px' }}>
              You and {matchPopup.other_user?.name || 'someone'} liked each other!
            </p>
            <div style={{ display: 'flex', justifyContent: 'center', gap: '16px', marginBottom: '28px', fontSize: '52px' }}>
              <span>{animalEmoji(avatarStatus?.animal)}</span>
              <span style={{ fontSize: '24px', alignSelf: 'center', color: 'var(--gold)' }}>❤️</span>
              <span>{animalEmoji(matchPopup.other_user?.animal)}</span>
            </div>
            <button
              onClick={() => setMatchPopup(null)}
              style={{ width: '100%', padding: '14px', background: 'var(--gradient-gold)', color: '#0D0B1A', border: 'none', borderRadius: '10px', fontSize: '16px', fontWeight: '700', cursor: 'pointer' }}
            >
              Keep Swiping
            </button>
            <button
              onClick={() => { setMatchPopup(null); setView('matches'); fetchMatches(); }}
              style={{ width: '100%', marginTop: '10px', padding: '12px', background: 'transparent', color: 'var(--gold)', border: '2px solid var(--gold)', borderRadius: '10px', fontSize: '15px', fontWeight: '600', cursor: 'pointer' }}
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
