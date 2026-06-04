import React, { useEffect, useState } from 'react';
import Nav from './Nav';
import { animalEmoji, avatarUrl } from '../utils';

export default function ProfileView({
  user, avatarStatus, isStale, isGenerating,
  name, age, location, bio,
  error, loading, copied,
  handleSaveProfile, handleRegenerate, handleCopyAnimal,
  deleteModalOpen, setDeleteModalOpen,
  deleteConfirmText, setDeleteConfirmText,
  deleteLoading, deleteError, setDeleteError,
  handleDeleteAccount,
  emailNotifications, handleToggleNotifications,
  blocks, blocksLoading, fetchBlocks, handleUnblock,
  navProps,
}) {
  useEffect(() => { fetchBlocks(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Edit mode state ────────────────────────────────────────────────────────
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState({});

  const enterEdit = () => {
    setDraft({ name: name || '', age: age || '', location: location || '', bio: bio || '' });
    setIsEditing(true);
  };

  const handleCancel = () => setIsEditing(false);

  const handleSave = async (e) => {
    e.preventDefault();
    const ok = await handleSaveProfile(draft);
    if (ok) setIsEditing(false);
  };

  // ── Avatar status helpers ──────────────────────────────────────────────────
  const getStatusEmoji = () => {
    if (!user?.bio) return <span>🐺</span>;
    if (!avatarStatus) return <span>🐺</span>;
    if (isStale) return <span>⚠️</span>;
    switch (avatarStatus.avatar_status) {
      case 'ready': return <span>✨</span>;
      case 'generating':
      case 'pending': return <span className="spinner">⏳</span>;
      case 'failed': return <span>❌</span>;
      default: return <span>🐺</span>;
    }
  };

  const getStatusText = () => {
    if (!user?.bio) return 'Fill in your bio to discover your spirit animal';
    if (!avatarStatus) return 'No avatar yet';
    if (isStale) return 'Generation timed out — click Try Again below';
    switch (avatarStatus.avatar_status) {
      case 'ready': return `Your spirit animal: ${avatarStatus.animal}`;
      case 'generating':
      case 'pending': return 'Claude is analyzing your bio...';
      case 'failed': return 'Avatar generation failed — try updating your bio';
      default: return 'Unknown status';
    }
  };

  // ── Regen countdown ────────────────────────────────────────────────────────
  const nextRegenDate = user?.regenerations_reset_at
    ? new Date(new Date(user.regenerations_reset_at).getTime() + 30 * 24 * 3600 * 1000)
    : null;
  const daysUntilRegen = nextRegenDate
    ? Math.max(1, Math.ceil((nextRegenDate - Date.now()) / (24 * 3600 * 1000)))
    : null;

  // ── Helpers ────────────────────────────────────────────────────────────────
  const inp = { width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' };
  const focusColor = (e) => (e.target.style.borderColor = '#667eea');
  const blurColor  = (e) => (e.target.style.borderColor = '#e2e8f0');
  const roVal = (v, placeholder = '—') => (
    <p style={{ color: v ? '#2d3748' : '#a0aec0', fontSize: '15px', margin: 0, fontStyle: v ? 'normal' : 'italic' }}>
      {v || placeholder}
    </p>
  );

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', padding: '40px 20px' }}>
      <div style={{ maxWidth: '600px', margin: '0 auto' }}>
        <Nav {...navProps} />

        {/* Unverified email banner */}
        {user && !user.is_email_verified && (
          <div style={{ background: 'rgba(246,173,85,0.2)', border: '1px solid rgba(246,173,85,0.5)', borderRadius: '12px', padding: '14px 20px', marginBottom: '20px', display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
            <span style={{ fontSize: '20px', flexShrink: 0 }}>📧</span>
            <div>
              <p style={{ color: 'white', fontWeight: '600', fontSize: '14px', margin: 0 }}>Please verify your email address</p>
              <p style={{ color: 'rgba(255,255,255,0.75)', fontSize: '13px', margin: '4px 0 0', lineHeight: '1.4' }}>
                A verification link was sent when you registered — check your server logs in dev mode.
              </p>
            </div>
          </div>
        )}

        {/* Avatar Status Card */}
        <div style={{ background: 'white', borderRadius: '16px', padding: '32px', marginBottom: '24px', boxShadow: '0 10px 40px rgba(0,0,0,0.2)', textAlign: 'center' }}>

          {/* Avatar image / emoji with optional badge */}
          <div style={{ position: 'relative', display: 'inline-block', marginBottom: '16px' }}>
            {avatarStatus?.avatar_status === 'ready' && avatarStatus?.avatar_url ? (
              <img
                src={avatarUrl(avatarStatus.avatar_url)}
                alt={avatarStatus.animal || 'avatar'}
                onError={(e) => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'block'; }}
                style={{ width: '120px', height: '120px', borderRadius: '50%', objectFit: 'cover', border: '4px solid #e2e8f0', boxShadow: '0 4px 16px rgba(0,0,0,0.15)', display: 'block' }}
              />
            ) : null}
            <div style={{ fontSize: '80px', lineHeight: 1, display: (avatarStatus?.avatar_status === 'ready' && avatarStatus?.avatar_url) ? 'none' : 'block' }}>
              {avatarStatus?.avatar_status === 'ready' ? animalEmoji(avatarStatus.animal) : getStatusEmoji()}
            </div>

            {/* Profile-out-of-sync badge */}
            {user?.profile_needs_regen && (
              <div style={{ position: 'absolute', bottom: '-8px', left: '50%', transform: 'translateX(-50%)', background: 'linear-gradient(135deg, #ed8936 0%, #dd6b20 100%)', color: 'white', borderRadius: '12px', padding: '3px 10px', fontSize: '11px', fontWeight: '600', whiteSpace: 'nowrap', boxShadow: '0 2px 8px rgba(0,0,0,0.2)' }}>
                too cheap to live their truth 🐾
              </div>
            )}
          </div>

          <h2 style={{ fontSize: '24px', fontWeight: '600', color: '#2d3748', marginBottom: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
            {getStatusText()}
            {avatarStatus?.avatar_status === 'ready' && avatarStatus?.animal && (
              <button onClick={handleCopyAnimal} style={{ padding: '4px 10px', background: copied ? '#48bb78' : '#edf2f7', color: copied ? 'white' : '#4a5568', border: 'none', borderRadius: '6px', fontSize: '12px', fontWeight: '500', cursor: 'pointer' }}>
                {copied ? 'Copied!' : '📋 Copy'}
              </button>
            )}
          </h2>

          {avatarStatus?.avatar_status === 'ready' && (
            <>
              {avatarStatus?.personality_traits?.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', justifyContent: 'center', marginBottom: '16px' }}>
                  {avatarStatus.personality_traits.map((trait, i) => (
                    <span key={i} style={{ background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', color: 'white', padding: '4px 12px', borderRadius: '16px', fontSize: '12px', fontWeight: '500' }}>
                      {trait}
                    </span>
                  ))}
                </div>
              )}
              {avatarStatus?.avatar_description && (
                <details style={{ textAlign: 'left', marginBottom: '12px' }}>
                  <summary style={{ cursor: 'pointer', color: '#667eea', fontSize: '13px', fontWeight: '500', userSelect: 'none' }}>View full description</summary>
                  <p style={{ marginTop: '8px', color: '#4a5568', fontSize: '14px', lineHeight: '1.6', padding: '12px', background: '#f7fafc', borderRadius: '8px' }}>
                    {avatarStatus.avatar_description}
                  </p>
                </details>
              )}
            </>
          )}

          {/* Generating progress bar */}
          {isGenerating && (
            <div style={{ marginTop: '16px', overflow: 'hidden' }}>
              <div style={{ width: '100%', height: '4px', background: '#e2e8f0', borderRadius: '2px', overflow: 'hidden' }}>
                <div style={{ width: '60%', height: '100%', background: 'linear-gradient(90deg, #667eea, #764ba2)', animation: 'slide 1.5s ease-in-out infinite' }} />
              </div>
            </div>
          )}

          {/* Stale recovery — lives here (avatar state, not profile form) */}
          {isStale && (
            <button
              onClick={handleRegenerate}
              disabled={loading}
              style={{ marginTop: '16px', padding: '10px 24px', background: 'linear-gradient(135deg, #f6ad55 0%, #ed8936 100%)', color: 'white', border: 'none', borderRadius: '8px', fontSize: '14px', fontWeight: '600', cursor: loading ? 'not-allowed' : 'pointer' }}
            >
              {loading ? 'Retrying…' : '⚠️ Try Again'}
            </button>
          )}

          {/* Regen-unavailable countdown */}
          {user?.profile_needs_regen && daysUntilRegen !== null && (
            <p style={{ marginTop: '14px', color: '#a0aec0', fontSize: '12px' }}>
              Next regeneration available in <strong>{daysUntilRegen} day{daysUntilRegen !== 1 ? 's' : ''}</strong>
            </p>
          )}
        </div>

        {/* Profile card */}
        <div style={{ background: 'white', borderRadius: '16px', padding: '32px', boxShadow: '0 10px 40px rgba(0,0,0,0.2)', marginBottom: '16px' }}>

          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px', gap: '12px' }}>
            <h3 style={{ fontSize: '20px', fontWeight: '600', color: '#2d3748', margin: 0 }}>
              {isEditing ? 'Edit Profile' : 'Your Profile'}
            </h3>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{ fontSize: '12px', color: '#718096', background: '#f7fafc', padding: '4px 12px', borderRadius: '12px' }}>{user?.email}</span>
              {!isEditing && (
                <button
                  onClick={enterEdit}
                  style={{ padding: '7px 16px', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', color: 'white', border: 'none', borderRadius: '8px', fontSize: '13px', fontWeight: '600', cursor: 'pointer' }}
                >
                  Edit Profile
                </button>
              )}
            </div>
          </div>

          {error && (
            <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', marginBottom: '20px', color: '#c53030', fontSize: '14px' }}>{error}</div>
          )}

          {/* ── Read-only view ─────────────────────────────────────────────── */}
          {!isEditing ? (
            <div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 80px 1fr', gap: '16px', marginBottom: '20px' }}>
                <div>
                  <p style={{ color: '#a0aec0', fontSize: '12px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 6px' }}>Name</p>
                  {roVal(name, 'Not set')}
                </div>
                <div>
                  <p style={{ color: '#a0aec0', fontSize: '12px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 6px' }}>Age</p>
                  {roVal(age, '—')}
                </div>
                <div>
                  <p style={{ color: '#a0aec0', fontSize: '12px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 6px' }}>Location</p>
                  {roVal(location, 'Not set')}
                </div>
              </div>
              <div>
                <p style={{ color: '#a0aec0', fontSize: '12px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 8px' }}>Bio</p>
                {bio
                  ? <p style={{ color: '#4a5568', fontSize: '15px', lineHeight: '1.65', margin: 0 }}>{bio}</p>
                  : <p style={{ color: '#a0aec0', fontSize: '14px', fontStyle: 'italic', margin: 0 }}>No bio yet — add one to generate your spirit animal!</p>
                }
              </div>
            </div>
          ) : (
            /* ── Edit form ───────────────────────────────────────────────── */
            <form onSubmit={handleSave}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 80px 1fr', gap: '16px', marginBottom: '20px' }}>
                <div>
                  <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Name</label>
                  <input type="text" value={draft.name} onChange={(e) => setDraft(d => ({ ...d, name: e.target.value }))} placeholder="Your first name" maxLength={100} style={inp} onFocus={focusColor} onBlur={blurColor} />
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Age</label>
                  <input type="number" value={draft.age} onChange={(e) => setDraft(d => ({ ...d, age: e.target.value }))} placeholder="25" min={18} max={120} style={inp} onFocus={focusColor} onBlur={blurColor} />
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Location</label>
                  <input type="text" value={draft.location} onChange={(e) => setDraft(d => ({ ...d, location: e.target.value }))} placeholder="City, State" maxLength={100} style={inp} onFocus={focusColor} onBlur={blurColor} />
                </div>
              </div>

              <div style={{ marginBottom: '24px' }}>
                <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>
                  Tell us about yourself
                </label>
                <textarea
                  value={draft.bio}
                  onChange={(e) => setDraft(d => ({ ...d, bio: e.target.value }))}
                  placeholder="I'm a lone wolf who loves midnight runs and howling at the moon..."
                  rows={4}
                  style={{ ...inp, fontFamily: 'inherit', resize: 'vertical' }}
                  onFocus={focusColor}
                  onBlur={blurColor}
                />
                <p style={{ fontSize: '12px', color: '#a0aec0', marginTop: '6px' }}>
                  Saving a changed bio will auto-regenerate your spirit animal if you have a regeneration available.
                </p>
              </div>

              <div style={{ display: 'flex', gap: '10px' }}>
                <button
                  type="button"
                  onClick={handleCancel}
                  disabled={loading}
                  style={{ flex: 1, padding: '13px', background: '#f7fafc', color: '#4a5568', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '15px', fontWeight: '600', cursor: 'pointer' }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  style={{ flex: 2, padding: '13px', background: loading ? '#a0aec0' : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', color: 'white', border: 'none', borderRadius: '8px', fontSize: '15px', fontWeight: '700', cursor: loading ? 'not-allowed' : 'pointer' }}
                >
                  {loading ? 'Saving…' : 'Save Changes'}
                </button>
              </div>
            </form>
          )}
        </div>

        {/* Notification preference */}
        <div style={{ marginTop: '16px', background: 'white', borderRadius: '16px', padding: '20px 32px', boxShadow: '0 10px 40px rgba(0,0,0,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px' }}>
          <div>
            <p style={{ color: '#2d3748', fontSize: '15px', fontWeight: '600', margin: 0 }}>Email notifications</p>
            <p style={{ color: '#718096', fontSize: '13px', margin: '4px 0 0' }}>
              Get an email when a match messages you (if you haven't been active in 5 min)
            </p>
          </div>
          <button
            onClick={() => handleToggleNotifications(!emailNotifications)}
            style={{ width: '48px', height: '26px', borderRadius: '13px', border: 'none', background: emailNotifications ? 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' : '#cbd5e0', cursor: 'pointer', position: 'relative', flexShrink: 0, transition: 'background 0.2s' }}
            aria-label={emailNotifications ? 'Disable email notifications' : 'Enable email notifications'}
          >
            <span style={{ position: 'absolute', top: '3px', left: emailNotifications ? '25px' : '3px', width: '20px', height: '20px', borderRadius: '50%', background: 'white', transition: 'left 0.2s', boxShadow: '0 1px 3px rgba(0,0,0,0.3)' }} />
          </button>
        </div>

        {/* Blocked users */}
        {(blocksLoading || blocks.length > 0) && (
          <div style={{ marginTop: '16px', background: 'white', borderRadius: '16px', padding: '24px 32px', boxShadow: '0 10px 40px rgba(0,0,0,0.2)' }}>
            <h3 style={{ fontSize: '15px', fontWeight: '700', color: '#2d3748', marginBottom: '16px' }}>Blocked Users</h3>
            {blocksLoading ? (
              <p style={{ color: '#a0aec0', fontSize: '14px' }}>Loading…</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {blocks.map((b) => (
                  <div key={b.id} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '10px 0', borderBottom: '1px solid #f7fafc' }}>
                    <div style={{ fontSize: '32px', flexShrink: 0 }}>
                      {b.avatar_url ? (
                        <img src={avatarUrl(b.avatar_url)} alt="" style={{ width: '40px', height: '40px', borderRadius: '50%', objectFit: 'cover' }} onError={(e) => { e.target.style.display='none'; e.target.nextSibling.style.display='block'; }} />
                      ) : null}
                      <span style={{ display: b.avatar_url ? 'none' : 'block', fontSize: '28px' }}>{animalEmoji(b.animal)}</span>
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{ color: '#2d3748', fontSize: '14px', fontWeight: '600', margin: 0 }}>{b.name || 'Anonymous'}</p>
                      {b.animal && <p style={{ color: '#a0aec0', fontSize: '12px', margin: '2px 0 0' }}>{b.animal.charAt(0).toUpperCase() + b.animal.slice(1)}</p>}
                    </div>
                    <button onClick={() => handleUnblock(b.id)} style={{ padding: '6px 14px', background: 'white', color: '#667eea', border: '2px solid #667eea', borderRadius: '8px', fontSize: '13px', fontWeight: '600', cursor: 'pointer', flexShrink: 0 }}>
                      Unblock
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Danger zone */}
        <div style={{ marginTop: '16px', background: 'white', borderRadius: '16px', padding: '24px 32px', boxShadow: '0 10px 40px rgba(0,0,0,0.2)', border: '1px solid #fed7d7' }}>
          <h3 style={{ fontSize: '15px', fontWeight: '700', color: '#c53030', marginBottom: '8px' }}>Danger Zone</h3>
          <p style={{ color: '#718096', fontSize: '13px', marginBottom: '16px' }}>Permanently delete your account and all data. This cannot be undone.</p>
          <button
            onClick={() => { setDeleteModalOpen(true); setDeleteConfirmText(''); setDeleteError(''); }}
            style={{ padding: '10px 20px', background: 'white', color: '#c53030', border: '2px solid #fc8181', borderRadius: '8px', fontSize: '14px', fontWeight: '600', cursor: 'pointer' }}
          >
            Delete Account
          </button>
        </div>

        <div style={{ marginTop: '24px', textAlign: 'center' }}>
          <a href="https://github.com/magicdevereaux/howl" target="_blank" rel="noopener noreferrer" style={{ color: 'rgba(255,255,255,0.8)', fontSize: '14px', textDecoration: 'none' }}>
            View on GitHub →
          </a>
        </div>
      </div>

      {/* Delete account confirmation modal */}
      {deleteModalOpen && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }}>
          <div style={{ background: 'white', borderRadius: '16px', padding: '36px 32px', maxWidth: '400px', width: '100%', boxShadow: '0 24px 64px rgba(0,0,0,0.35)' }}>
            <div style={{ fontSize: '40px', textAlign: 'center', marginBottom: '12px' }}>⚠️</div>
            <h2 style={{ fontSize: '20px', fontWeight: '800', color: '#2d3748', textAlign: 'center', marginBottom: '8px' }}>Delete your account?</h2>
            <p style={{ color: '#718096', fontSize: '14px', textAlign: 'center', marginBottom: '24px', lineHeight: '1.5' }}>
              This will permanently erase your profile, matches, and all messages. There is no undo.
            </p>
            <label style={{ display: 'block', color: '#4a5568', fontSize: '13px', fontWeight: '600', marginBottom: '6px' }}>
              Type <span style={{ fontFamily: 'monospace', background: '#f7fafc', padding: '1px 6px', borderRadius: '4px' }}>DELETE</span> to confirm
            </label>
            <input
              type="text"
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              placeholder="DELETE"
              style={{ width: '100%', padding: '10px 12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '15px', marginBottom: '16px', boxSizing: 'border-box', fontFamily: 'monospace' }}
              onFocus={(e) => e.target.style.borderColor = '#fc8181'}
              onBlur={(e) => e.target.style.borderColor = '#e2e8f0'}
            />
            {deleteError && <p style={{ color: '#c53030', fontSize: '13px', marginBottom: '12px', textAlign: 'center' }}>⚠️ {deleteError}</p>}
            <div style={{ display: 'flex', gap: '10px' }}>
              <button
                onClick={() => { setDeleteModalOpen(false); setDeleteConfirmText(''); setDeleteError(''); }}
                disabled={deleteLoading}
                style={{ flex: 1, padding: '12px', background: '#f7fafc', color: '#4a5568', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '15px', fontWeight: '600', cursor: 'pointer' }}
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteAccount}
                disabled={deleteConfirmText !== 'DELETE' || deleteLoading}
                style={{ flex: 1, padding: '12px', background: (deleteConfirmText === 'DELETE' && !deleteLoading) ? '#c53030' : '#fc8181', color: 'white', border: 'none', borderRadius: '8px', fontSize: '15px', fontWeight: '700', cursor: (deleteConfirmText === 'DELETE' && !deleteLoading) ? 'pointer' : 'not-allowed' }}
              >
                {deleteLoading ? 'Deleting…' : 'Delete forever'}
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        @keyframes slide { 0% { transform: translateX(-100%); } 100% { transform: translateX(250%); } }
        @keyframes spin  { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .spinner { display: inline-block; animation: spin 2s linear infinite; }
      `}</style>
    </div>
  );
}
