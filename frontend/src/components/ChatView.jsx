import React, { useEffect, useRef, useState } from 'react';
import { API_URL, animalEmoji, avatarUrl, fetchApi } from '../utils';

const REPORT_REASONS = [
  { value: 'spam_scam',             label: 'Spam or scam' },
  { value: 'inappropriate_content', label: 'Inappropriate content' },
  { value: 'harassment',            label: 'Harassment or abuse' },
  { value: 'fake_profile',          label: 'Fake or impersonating profile' },
  { value: 'underage_user',         label: 'Underage user' },
  { value: 'other',                 label: 'Other' },
];

export default function ChatView({
  currentMatch, messages, setMessages,
  messagesLoading, messagesError, messageInput, setMessageInput,
  sending, sendError, sendMessage, loadMessages,
  hasMoreMessages, loadingMore, loadMoreMessages,
  handleDeleteMessage,
  typingUser, sendTypingEvent,
  handleUnmatch, handleBlock, handleBlockAndReport, handleOpenReport,
  setView, fetchMatches,
}) {
  const other = currentMatch.other_user;
  const messagesEndRef = useRef(null);
  const scrollContainerRef = useRef(null);
  const prevScrollHeightRef = useRef(null);
  const inputRef = useRef(null);
  const wasSending = useRef(false);
  const [pendingAction, setPendingAction] = useState(null);
  const typingDebounceRef = useRef(null);

  useEffect(() => () => { if (typingDebounceRef.current) clearTimeout(typingDebounceRef.current); }, []);

  const [menuOpen, setMenuOpen] = useState(false);
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [profileData, setProfileData] = useState(null);
  const [profileLoading, setProfileLoading] = useState(false);

  const openProfileModal = async () => {
    setShowProfileModal(true);
    if (profileData) return;
    setProfileLoading(true);
    try {
      const res = await fetchApi(`${API_URL}/api/profile/${other.id}`);
      if (res.ok) setProfileData(await res.json());
    } catch { /* show what we already have from other */ }
    finally { setProfileLoading(false); }
  };
  const [blockReportReason, setBlockReportReason] = useState('');
  const [blockReportNotes, setBlockReportNotes] = useState('');
  const [clickedMsgId, setClickedMsgId] = useState(null);

  useEffect(() => {
    if (!menuOpen) return;
    const close = () => setMenuOpen(false);
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, [menuOpen]);

  useEffect(() => {
    if (!clickedMsgId) return;
    const close = () => setClickedMsgId(null);
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, [clickedMsgId]);

  useEffect(() => {
    if (prevScrollHeightRef.current !== null && scrollContainerRef.current) {
      const delta = scrollContainerRef.current.scrollHeight - prevScrollHeightRef.current;
      scrollContainerRef.current.scrollTop = delta;
      prevScrollHeightRef.current = null;
      return;
    }
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleLoadMore = () => {
    prevScrollHeightRef.current = scrollContainerRef.current?.scrollHeight ?? null;
    loadMoreMessages();
  };

  useEffect(() => {
    if (wasSending.current && !sending) {
      inputRef.current?.focus();
    }
    wasSending.current = sending;
  }, [sending]);

  const formatTime = (iso) =>
    new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  const formatDate = (iso) => {
    const d = new Date(iso);
    const today = new Date();
    const yesterday = new Date(today - 86400000);
    if (d.toDateString() === today.toDateString()) return 'Today';
    if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  };

  const grouped = messages.reduce((acc, msg) => {
    const label = formatDate(msg.created_at);
    (acc[label] = acc[label] || []).push(msg);
    return acc;
  }, {});

  return (
    <div style={{ height: '100vh', overflow: 'hidden', background: 'var(--gradient-main)', display: 'flex', flexDirection: 'column' }}>

      {/* Chat header */}
      <div style={{ background: 'rgba(0,0,0,0.4)', padding: '16px 20px', display: 'flex', alignItems: 'center', gap: '14px', flexShrink: 0 }}>
        <button
          onClick={() => { setView('matches'); fetchMatches(); }}
          style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '8px', padding: '8px 14px', cursor: 'pointer', fontSize: '14px', fontWeight: '500' }}
        >
          ← Matches
        </button>
        {/* ⋯ action menu */}
        <div style={{ marginLeft: 'auto', position: 'relative' }}>
          <button
            onClick={(e) => { e.stopPropagation(); setMenuOpen((o) => !o); }}
            style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '8px', padding: '6px 12px', cursor: 'pointer', fontSize: '18px', lineHeight: 1 }}
            title="More options"
          >
            ⋯
          </button>
          {menuOpen && (
            <div style={{ position: 'absolute', top: 'calc(100% + 8px)', right: 0, background: 'var(--bg-card)', borderRadius: '12px', boxShadow: '0 8px 32px rgba(0,0,0,0.4)', overflow: 'hidden', minWidth: '180px', zIndex: 200 }}>
              <button
                onClick={() => { setMenuOpen(false); setPendingAction('unmatch'); }}
                style={{ display: 'block', width: '100%', padding: '13px 18px', background: 'none', border: 'none', textAlign: 'left', fontSize: '14px', color: 'var(--text-surface)', cursor: 'pointer', fontWeight: '500' }}
                onMouseEnter={(e) => e.currentTarget.style.background = 'var(--bg-hover)'}
                onMouseLeave={(e) => e.currentTarget.style.background = 'none'}
              >
                💔 Unmatch
              </button>
              <div style={{ height: '1px', background: 'var(--border)' }} />
              <button
                onClick={() => { setMenuOpen(false); setBlockReportReason(''); setBlockReportNotes(''); setPendingAction('block-report'); }}
                style={{ display: 'block', width: '100%', padding: '13px 18px', background: 'none', border: 'none', textAlign: 'left', fontSize: '14px', color: '#c53030', cursor: 'pointer', fontWeight: '500' }}
                onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(197,48,48,0.1)'}
                onMouseLeave={(e) => e.currentTarget.style.background = 'none'}
              >
                🚫 Block &amp; Report
              </button>
            </div>
          )}
        </div>
        {/* Clickable avatar + name */}
        <button
          onClick={openProfileModal}
          style={{ display: 'flex', alignItems: 'center', gap: '12px', background: 'none', border: 'none', cursor: 'pointer', padding: '4px 8px', borderRadius: '10px', transition: 'background 0.15s' }}
          onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.06)'}
          onMouseLeave={(e) => e.currentTarget.style.background = 'none'}
          title="View profile"
        >
          {other.avatar_url ? (
            <img
              src={avatarUrl(other.avatar_url)}
              alt={other.animal || 'avatar'}
              onError={(e) => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'block'; }}
              style={{ width: '44px', height: '44px', borderRadius: '50%', objectFit: 'cover', border: '2px solid var(--border)', flexShrink: 0 }}
            />
          ) : null}
          <div style={{ fontSize: '36px', lineHeight: 1, display: other.avatar_url ? 'none' : 'block' }}>{animalEmoji(other.animal)}</div>
          <div style={{ textAlign: 'left' }}>
            <p style={{ color: 'var(--text-primary)', fontWeight: '700', fontSize: '17px', margin: 0 }}>{other.name || 'Anonymous'}</p>
            <p style={{ color: 'var(--text-secondary)', fontSize: '12px', margin: 0 }}>
              {other.animal ? other.animal.charAt(0).toUpperCase() + other.animal.slice(1) : ''}
            </p>
          </div>
        </button>
      </div>

      {/* Message list */}
      <div ref={scrollContainerRef} style={{ flex: 1, overflowY: 'auto', padding: '20px 16px', display: 'flex', flexDirection: 'column' }}>

        {hasMoreMessages && !messagesError && (
          <div style={{ textAlign: 'center', marginBottom: '12px' }}>
            <button
              onClick={handleLoadMore}
              disabled={loadingMore}
              style={{ padding: '6px 18px', background: 'rgba(255,255,255,0.08)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: '20px', fontSize: '12px', fontWeight: '500', cursor: loadingMore ? 'not-allowed' : 'pointer', opacity: loadingMore ? 0.6 : 1 }}
            >
              {loadingMore ? 'Loading…' : '↑ Load older messages'}
            </button>
          </div>
        )}

        {messagesError ? (
          <div style={{ textAlign: 'center', color: 'var(--text-secondary)', marginTop: '60px', padding: '0 20px' }}>
            <div style={{ fontSize: '36px', marginBottom: '12px' }}>⚠️</div>
            <p style={{ fontSize: '15px', marginBottom: '16px' }}>{messagesError}</p>
            <button
              onClick={() => loadMessages(currentMatch.id)}
              style={{ padding: '10px 24px', background: 'var(--accent)', color: 'white', border: 'none', borderRadius: '10px', fontWeight: '600', cursor: 'pointer', fontSize: '14px' }}
            >
              Try again
            </button>
          </div>
        ) : messagesLoading && messages.length === 0 ? (
          <div style={{ textAlign: 'center', color: 'var(--text-secondary)', marginTop: '40px' }}>
            <div style={{ fontSize: '32px', marginBottom: '8px' }} className="spinner">🐾</div>
            Loading…
          </div>
        ) : messages.length === 0 ? (
          <div style={{ textAlign: 'center', color: 'var(--text-secondary)', marginTop: '60px' }}>
            <div style={{ fontSize: '48px', marginBottom: '12px' }}>👋</div>
            <p style={{ fontSize: '17px', fontWeight: '600', color: 'var(--text-primary)' }}>Start the conversation!</p>
            <p style={{ fontSize: '14px', marginTop: '6px' }}>
              Say hi to {other.name || 'them'}!
            </p>
          </div>
        ) : (
          Object.entries(grouped).map(([dateLabel, msgs]) => (
            <div key={dateLabel}>
              <div style={{ textAlign: 'center', margin: '16px 0 10px' }}>
                <span style={{ background: 'rgba(0,0,0,0.45)', color: 'var(--text-secondary)', fontSize: '11px', padding: '3px 12px', borderRadius: '10px' }}>
                  {dateLabel}
                </span>
              </div>
              {msgs.map((msg) => (
                <div key={msg.id} style={{ display: 'flex', justifyContent: msg.is_mine ? 'flex-end' : 'flex-start', alignItems: 'flex-end', gap: '6px', marginBottom: '8px' }}>
                  {!msg.is_mine && !msg.deleted_at && (
                    <button
                      onClick={() => handleOpenReport(other.id, other.name, msg.id)}
                      title="Report message"
                      style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '11px', opacity: 0.25, padding: '2px', flexShrink: 0, lineHeight: 1 }}
                    >
                      🚩
                    </button>
                  )}

                  <div style={{
                    maxWidth: '70%',
                    padding: msg.deleted_at ? '8px 14px' : '10px 14px',
                    borderRadius: msg.is_mine ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
                    background: msg.deleted_at
                      ? 'var(--border-subtle)'
                      : (msg.is_mine ? 'var(--accent)' : 'rgba(255,255,255,0.1)'),
                    color: 'var(--text-primary)',
                    boxShadow: msg.deleted_at ? 'none' : '0 1px 4px rgba(0,0,0,0.2)',
                    border: msg.deleted_at ? '1px dashed var(--border)' : 'none',
                  }}>
                    {msg.deleted_at ? (
                      <p style={{ margin: 0, fontSize: '13px', fontStyle: 'italic', opacity: 0.45 }}>
                        🗑 Message deleted
                      </p>
                    ) : (
                      <>
                        <p style={{ margin: 0, fontSize: '15px', lineHeight: '1.45', wordBreak: 'break-word' }}>{msg.content}</p>
                        <p style={{ margin: '4px 0 0', fontSize: '10px', opacity: 0.6, textAlign: 'right' }}>
                          {formatTime(msg.created_at)}
                          {msg.is_mine && (
                            <span style={{ marginLeft: '5px', color: msg.read_at ? 'var(--accent-hover)' : 'var(--text-disabled)' }}>
                              {msg.read_at ? '✓✓' : '✓'}
                            </span>
                          )}
                        </p>
                      </>
                    )}
                  </div>

                  {msg.is_mine && !msg.deleted_at && (
                    <div style={{ position: 'relative', flexShrink: 0 }}>
                      <button
                        onClick={(e) => { e.stopPropagation(); setClickedMsgId(clickedMsgId === msg.id ? null : msg.id); }}
                        title="Message options"
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-disabled)', fontSize: '16px', lineHeight: 1, padding: '2px 4px' }}
                      >
                        ⋮
                      </button>
                      {clickedMsgId === msg.id && (
                        <div style={{ position: 'absolute', bottom: '100%', right: 0, background: 'var(--bg-card)', borderRadius: '10px', boxShadow: '0 4px 20px rgba(0,0,0,0.4)', overflow: 'hidden', minWidth: '160px', zIndex: 100, marginBottom: '4px' }}>
                          <button
                            onClick={() => { setClickedMsgId(null); handleDeleteMessage(msg.id); }}
                            style={{ display: 'block', width: '100%', padding: '11px 16px', background: 'none', border: 'none', textAlign: 'left', fontSize: '14px', color: '#c53030', cursor: 'pointer', fontWeight: '500' }}
                            onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(197,48,48,0.1)'}
                            onMouseLeave={(e) => e.currentTarget.style.background = 'none'}
                          >
                            🗑 Delete message
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Typing indicator */}
      {typingUser && (
        <div style={{ padding: '4px 20px 6px', flexShrink: 0 }}>
          <span style={{ color: 'var(--text-secondary)', fontSize: '13px', fontStyle: 'italic' }}>
            {typingUser} is typing…
          </span>
        </div>
      )}

      {/* Send error */}
      {sendError && (
        <div style={{ background: 'rgba(197,48,48,0.15)', borderTop: '1px solid rgba(197,48,48,0.3)', padding: '8px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
          <p style={{ color: '#fc8181', fontSize: '13px', margin: 0 }}>⚠️ {sendError}</p>
          <button onClick={sendMessage} style={{ padding: '4px 12px', background: '#c53030', color: 'white', border: 'none', borderRadius: '6px', fontSize: '12px', fontWeight: '600', cursor: 'pointer' }}>
            Retry
          </button>
        </div>
      )}

      {/* Message input */}
      <div style={{ background: 'var(--bg-card)', padding: '12px 16px', display: 'flex', gap: '10px', alignItems: 'center', flexShrink: 0, borderTop: sendError ? 'none' : '1px solid var(--border)' }}>
        <input
          type="text"
          value={messageInput}
          ref={inputRef}
          onChange={(e) => {
            setMessageInput(e.target.value.slice(0, 2000));
            if (typingDebounceRef.current) clearTimeout(typingDebounceRef.current);
            typingDebounceRef.current = setTimeout(() => sendTypingEvent?.(), 500);
          }}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
          placeholder={`Message ${other.name || 'them'}…`}
          disabled={sending}
          style={{ flex: 1, padding: '11px 16px', border: '2px solid var(--border)', borderRadius: '24px', fontSize: '15px', outline: 'none', boxSizing: 'border-box', background: 'var(--bg-input)', color: 'var(--text-primary)' }}
          onFocus={(e) => e.target.style.borderColor = '#6B3FA0'}
          onBlur={(e) => e.target.style.borderColor = 'rgba(255,255,255,0.1)'}
        />
        <button
          onClick={sendMessage}
          disabled={!messageInput.trim() || sending}
          style={{
            width: '44px', height: '44px', borderRadius: '50%', border: 'none', flexShrink: 0,
            background: (!messageInput.trim() || sending) ? 'var(--bg-hover)' : 'var(--gradient-brand)',
            cursor: (!messageInput.trim() || sending) ? 'not-allowed' : 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px',
            transition: 'background 0.15s',
          }}
        >
          ➤
        </button>
      </div>

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .spinner { display: inline-block; animation: spin 2s linear infinite; }
      `}</style>

      {/* Unmatch confirmation modal */}
      {pendingAction === 'unmatch' && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }}>
          <div style={{ background: 'var(--bg-card)', borderRadius: '16px', padding: '32px', maxWidth: '360px', width: '100%', textAlign: 'center', boxShadow: '0 24px 64px rgba(0,0,0,0.5)' }}>
            <div style={{ fontSize: '36px', marginBottom: '12px' }}>💔</div>
            <h2 style={{ fontSize: '18px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '8px' }}>
              Unmatch {other.name || 'this user'}?
            </h2>
            <p style={{ color: 'var(--text-secondary)', fontSize: '14px', marginBottom: '24px', lineHeight: '1.5' }}>
              Your match and conversation will be removed. They may reappear in discover.
            </p>
            <div style={{ display: 'flex', gap: '10px' }}>
              <button onClick={() => setPendingAction(null)} style={{ flex: 1, padding: '11px', background: 'var(--bg-hover)', color: 'var(--text-surface)', border: '1px solid var(--border)', borderRadius: '8px', fontSize: '14px', fontWeight: '600', cursor: 'pointer' }}>
                Cancel
              </button>
              <button
                onClick={() => { setPendingAction(null); handleUnmatch(currentMatch.id); }}
                style={{ flex: 1, padding: '11px', background: 'var(--bg-nav)', color: 'var(--text-secondary)', border: '1px solid var(--border)', borderRadius: '8px', fontSize: '14px', fontWeight: '700', cursor: 'pointer' }}
              >
                Unmatch
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Block & Report modal */}
      {pendingAction === 'block-report' && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }}>
          <div style={{ background: 'var(--bg-card)', borderRadius: '16px', padding: '32px', maxWidth: '420px', width: '100%', boxShadow: '0 24px 64px rgba(0,0,0,0.5)' }}>
            <div style={{ fontSize: '36px', textAlign: 'center', marginBottom: '10px' }}>🚫</div>
            <h2 style={{ fontSize: '18px', fontWeight: '700', color: 'var(--text-primary)', textAlign: 'center', marginBottom: '6px' }}>
              Block &amp; Report {other.name || 'this user'}?
            </h2>
            <p style={{ color: 'var(--text-secondary)', fontSize: '13px', textAlign: 'center', marginBottom: '20px', lineHeight: '1.5' }}>
              They'll be blocked and removed from your matches. A report will be sent to our team for review.
            </p>

            <div style={{ marginBottom: '14px' }}>
              <label style={{ display: 'block', color: 'var(--text-surface)', fontSize: '13px', fontWeight: '600', marginBottom: '6px' }}>
                Reason <span style={{ color: '#c53030' }}>*</span>
              </label>
              <select
                value={blockReportReason}
                onChange={(e) => setBlockReportReason(e.target.value)}
                style={{ width: '100%', padding: '10px 12px', border: '2px solid var(--border)', borderRadius: '8px', fontSize: '14px', background: 'var(--bg-input)', boxSizing: 'border-box', cursor: 'pointer' }}
              >
                <option value="">Select a reason…</option>
                {REPORT_REASONS.map((r) => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', color: 'var(--text-surface)', fontSize: '13px', fontWeight: '600', marginBottom: '6px' }}>
                Additional notes <span style={{ color: 'var(--text-disabled)', fontWeight: '400' }}>(optional)</span>
              </label>
              <textarea
                value={blockReportNotes}
                onChange={(e) => setBlockReportNotes(e.target.value.slice(0, 500))}
                placeholder="Any additional context…"
                rows={3}
                style={{ width: '100%', padding: '10px 12px', border: '2px solid var(--border)', borderRadius: '8px', fontSize: '14px', fontFamily: 'inherit', resize: 'vertical', boxSizing: 'border-box', background: 'var(--bg-input)' }}
              />
            </div>

            <div style={{ display: 'flex', gap: '10px' }}>
              <button onClick={() => setPendingAction(null)} style={{ flex: 1, padding: '11px', background: 'var(--bg-hover)', color: 'var(--text-surface)', border: '1px solid var(--border)', borderRadius: '8px', fontSize: '14px', fontWeight: '600', cursor: 'pointer' }}>
                Cancel
              </button>
              <button
                disabled={!blockReportReason}
                onClick={() => {
                  setPendingAction(null);
                  handleBlockAndReport(other.id, blockReportReason, blockReportNotes.trim() || undefined);
                }}
                style={{ flex: 1, padding: '11px', background: blockReportReason ? '#c53030' : '#fc8181', color: 'white', border: 'none', borderRadius: '8px', fontSize: '14px', fontWeight: '700', cursor: blockReportReason ? 'pointer' : 'not-allowed' }}
              >
                Block &amp; Report
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Profile modal */}
      {showProfileModal && (
        <div
          onClick={() => setShowProfileModal(false)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1050, padding: '20px' }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ background: 'var(--bg-card)', borderRadius: '20px', maxWidth: '400px', width: '100%', overflow: 'hidden', boxShadow: '0 24px 64px rgba(0,0,0,0.5)', maxHeight: '90vh', overflowY: 'auto' }}
          >
            {/* Header with gradient + avatar */}
            <div style={{ background: 'var(--gradient-brand)', padding: '32px 24px 24px', textAlign: 'center', position: 'relative' }}>
              <button
                onClick={() => setShowProfileModal(false)}
                style={{ position: 'absolute', top: '14px', right: '14px', background: 'rgba(255,255,255,0.15)', border: 'none', color: 'white', borderRadius: '50%', width: '32px', height: '32px', cursor: 'pointer', fontSize: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
              >
                ✕
              </button>

              {profileLoading && !profileData ? (
                <div style={{ fontSize: '64px', marginBottom: '12px' }} className="spinner">🐾</div>
              ) : (
                <>
                  {(profileData?.avatar_url || other.avatar_url) ? (
                    <img
                      src={avatarUrl(profileData?.avatar_url || other.avatar_url)}
                      alt="avatar"
                      onError={(e) => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'block'; }}
                      style={{ width: '96px', height: '96px', borderRadius: '50%', objectFit: 'cover', border: '4px solid rgba(255,255,255,0.25)', marginBottom: '14px' }}
                    />
                  ) : null}
                  <div style={{ fontSize: '80px', lineHeight: 1, marginBottom: '14px', display: (profileData?.avatar_url || other.avatar_url) ? 'none' : 'block' }}>
                    {animalEmoji(profileData?.animal || other.animal)}
                  </div>
                  <h2 style={{ color: 'white', fontSize: '22px', fontWeight: '800', margin: '0 0 4px' }}>
                    {profileData?.name || other.name || 'Anonymous'}
                    {profileData?.age ? <span style={{ fontWeight: '400', fontSize: '18px', opacity: 0.85 }}>, {profileData.age}</span> : null}
                  </h2>
                  <p style={{ color: 'rgba(255,255,255,0.75)', fontSize: '14px', margin: 0 }}>
                    {(() => { const a = profileData?.animal || other.animal; return a ? a.charAt(0).toUpperCase() + a.slice(1) : ''; })()}
                  </p>
                  {profileData?.location && (
                    <p style={{ color: 'rgba(255,255,255,0.55)', fontSize: '13px', marginTop: '6px' }}>📍 {profileData.location}</p>
                  )}
                </>
              )}
            </div>

            {/* Body */}
            <div style={{ padding: '20px 24px 24px' }}>
              {profileData?.bio && (
                <p style={{ color: 'var(--text-surface)', fontSize: '14px', lineHeight: '1.6', marginBottom: '16px' }}>
                  {profileData.bio}
                </p>
              )}

              {profileData?.personality_traits?.length > 0 && (
                <div style={{ marginBottom: '16px' }}>
                  <p style={{ color: 'var(--text-disabled)', fontSize: '11px', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.06em', margin: '0 0 8px' }}>
                    Personality
                  </p>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    {profileData.personality_traits.map((t, i) => (
                      <span key={i} style={{ background: 'var(--bg-hover)', color: 'var(--text-secondary)', padding: '4px 12px', borderRadius: '12px', fontSize: '12px', fontWeight: '500' }}>
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {profileData?.avatar_description && (
                <div style={{ marginBottom: '16px' }}>
                  <p style={{ color: 'var(--text-disabled)', fontSize: '11px', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.06em', margin: '0 0 8px' }}>
                    Spirit Animal
                  </p>
                  <p style={{ color: 'var(--text-secondary)', fontSize: '13px', lineHeight: '1.65', fontStyle: 'italic', margin: 0 }}>
                    {profileData.avatar_description}
                  </p>
                </div>
              )}

              {profileLoading && !profileData && (
                <p style={{ color: 'var(--text-disabled)', fontSize: '13px', textAlign: 'center', marginBottom: '16px' }}>Loading profile…</p>
              )}

              <div style={{ height: '1px', background: 'var(--border)', margin: '4px 0 16px' }} />

              <div style={{ display: 'flex', gap: '10px' }}>
                <button
                  onClick={() => { setShowProfileModal(false); handleOpenReport(other.id, other.name); }}
                  style={{ flex: 1, padding: '10px', background: 'transparent', color: 'var(--text-secondary)', border: '1px solid var(--border)', borderRadius: '10px', fontSize: '13px', fontWeight: '600', cursor: 'pointer' }}
                  onMouseEnter={(e) => e.currentTarget.style.borderColor = 'var(--accent)'}
                  onMouseLeave={(e) => e.currentTarget.style.borderColor = 'rgba(255,255,255,0.1)'}
                >
                  🚩 Report
                </button>
                <button
                  onClick={() => { setShowProfileModal(false); setBlockReportReason(''); setBlockReportNotes(''); setPendingAction('block-report'); }}
                  style={{ flex: 1, padding: '10px', background: 'transparent', color: '#c53030', border: '1px solid rgba(197,48,48,0.4)', borderRadius: '10px', fontSize: '13px', fontWeight: '600', cursor: 'pointer' }}
                  onMouseEnter={(e) => e.currentTarget.style.borderColor = '#c53030'}
                  onMouseLeave={(e) => e.currentTarget.style.borderColor = 'rgba(197,48,48,0.4)'}
                >
                  🚫 Block
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
