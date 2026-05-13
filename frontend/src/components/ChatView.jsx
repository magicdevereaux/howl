import React, { useEffect, useRef, useState } from 'react';
import { animalEmoji, avatarUrl } from '../utils';

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
  handleUnmatch, handleBlock, handleBlockAndReport, handleOpenReport,
  setView, fetchMatches,
}) {
  const other = currentMatch.other_user;
  const messagesEndRef = useRef(null);
  const scrollContainerRef = useRef(null);
  const prevScrollHeightRef = useRef(null); // set before prepend; triggers scroll restore
  const inputRef = useRef(null);
  const wasSending = useRef(false);
  const [pendingAction, setPendingAction] = useState(null); // 'unmatch' | 'block-report' | null
  const [menuOpen, setMenuOpen] = useState(false);
  const [blockReportReason, setBlockReportReason] = useState('');
  const [blockReportNotes, setBlockReportNotes] = useState('');

  // Close the ⋯ menu when the user clicks anywhere else on the page
  useEffect(() => {
    if (!menuOpen) return;
    const close = () => setMenuOpen(false);
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, [menuOpen]);

  useEffect(() => {
    if (prevScrollHeightRef.current !== null && scrollContainerRef.current) {
      // Older messages were prepended — restore position so the view doesn't jump.
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

  // Refocus the input whenever a send completes (success or error) so the
  // user can type their next message without clicking back into the box.
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
    <div style={{ height: '100vh', overflow: 'hidden', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', display: 'flex', flexDirection: 'column' }}>

      {/* Chat header */}
      <div style={{ background: 'rgba(0,0,0,0.2)', padding: '16px 20px', display: 'flex', alignItems: 'center', gap: '14px', flexShrink: 0 }}>
        <button
          onClick={() => { setView('matches'); fetchMatches(); }}
          style={{ background: 'rgba(255,255,255,0.15)', border: '1px solid rgba(255,255,255,0.3)', color: 'white', borderRadius: '8px', padding: '8px 14px', cursor: 'pointer', fontSize: '14px', fontWeight: '500' }}
        >
          ← Matches
        </button>
        {/* ⋯ action menu */}
        <div style={{ marginLeft: 'auto', position: 'relative' }}>
          <button
            onClick={(e) => { e.stopPropagation(); setMenuOpen((o) => !o); }}
            style={{ background: 'rgba(255,255,255,0.12)', border: '1px solid rgba(255,255,255,0.25)', color: 'white', borderRadius: '8px', padding: '6px 12px', cursor: 'pointer', fontSize: '18px', lineHeight: 1 }}
            title="More options"
          >
            ⋯
          </button>
          {menuOpen && (
            <div style={{ position: 'absolute', top: 'calc(100% + 8px)', right: 0, background: 'white', borderRadius: '12px', boxShadow: '0 8px 32px rgba(0,0,0,0.2)', overflow: 'hidden', minWidth: '180px', zIndex: 200 }}>
              <button
                onClick={() => { setMenuOpen(false); setPendingAction('unmatch'); }}
                style={{ display: 'block', width: '100%', padding: '13px 18px', background: 'none', border: 'none', textAlign: 'left', fontSize: '14px', color: '#4a5568', cursor: 'pointer', fontWeight: '500' }}
                onMouseEnter={(e) => e.currentTarget.style.background = '#f7fafc'}
                onMouseLeave={(e) => e.currentTarget.style.background = 'none'}
              >
                💔 Unmatch
              </button>
              <div style={{ height: '1px', background: '#e2e8f0' }} />
              <button
                onClick={() => { setMenuOpen(false); setBlockReportReason(''); setBlockReportNotes(''); setPendingAction('block-report'); }}
                style={{ display: 'block', width: '100%', padding: '13px 18px', background: 'none', border: 'none', textAlign: 'left', fontSize: '14px', color: '#c53030', cursor: 'pointer', fontWeight: '500' }}
                onMouseEnter={(e) => e.currentTarget.style.background = '#fff5f5'}
                onMouseLeave={(e) => e.currentTarget.style.background = 'none'}
              >
                🚫 Block &amp; Report
              </button>
            </div>
          )}
        </div>
        {other.avatar_url ? (
          <img
            src={avatarUrl(other.avatar_url)}
            alt={other.animal || 'avatar'}
            onError={(e) => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'block'; }}
            style={{ width: '44px', height: '44px', borderRadius: '50%', objectFit: 'cover', border: '2px solid rgba(255,255,255,0.4)', flexShrink: 0 }}
          />
        ) : null}
        <div style={{ fontSize: '36px', lineHeight: 1, display: other.avatar_url ? 'none' : 'block' }}>{animalEmoji(other.animal)}</div>
        <div>
          <p style={{ color: 'white', fontWeight: '700', fontSize: '17px', margin: 0 }}>{other.name || 'Anonymous'}</p>
          <p style={{ color: 'rgba(255,255,255,0.7)', fontSize: '12px', margin: 0 }}>
            {other.animal ? other.animal.charAt(0).toUpperCase() + other.animal.slice(1) : ''}
          </p>
        </div>
      </div>

      {/* Message list */}
      <div ref={scrollContainerRef} style={{ flex: 1, overflowY: 'auto', padding: '20px 16px', display: 'flex', flexDirection: 'column' }}>

        {/* Load older messages */}
        {hasMoreMessages && !messagesError && (
          <div style={{ textAlign: 'center', marginBottom: '12px' }}>
            <button
              onClick={handleLoadMore}
              disabled={loadingMore}
              style={{ padding: '6px 18px', background: 'rgba(255,255,255,0.15)', color: 'white', border: '1px solid rgba(255,255,255,0.3)', borderRadius: '20px', fontSize: '12px', fontWeight: '500', cursor: loadingMore ? 'not-allowed' : 'pointer', opacity: loadingMore ? 0.6 : 1 }}
            >
              {loadingMore ? 'Loading…' : '↑ Load older messages'}
            </button>
          </div>
        )}

        {messagesError ? (
          <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.85)', marginTop: '60px', padding: '0 20px' }}>
            <div style={{ fontSize: '36px', marginBottom: '12px' }}>⚠️</div>
            <p style={{ fontSize: '15px', marginBottom: '16px' }}>{messagesError}</p>
            <button
              onClick={() => loadMessages(currentMatch.id)}
              style={{ padding: '10px 24px', background: 'white', color: '#667eea', border: 'none', borderRadius: '10px', fontWeight: '600', cursor: 'pointer', fontSize: '14px' }}
            >
              Try again
            </button>
          </div>
        ) : messagesLoading && messages.length === 0 ? (
          <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.6)', marginTop: '40px' }}>
            <div style={{ fontSize: '32px', marginBottom: '8px' }} className="spinner">🐾</div>
            Loading…
          </div>
        ) : messages.length === 0 ? (
          <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.75)', marginTop: '60px' }}>
            <div style={{ fontSize: '48px', marginBottom: '12px' }}>👋</div>
            <p style={{ fontSize: '17px', fontWeight: '600' }}>Start the conversation!</p>
            <p style={{ fontSize: '14px', marginTop: '6px', opacity: 0.8 }}>
              Say hi to {other.name || 'them'}!
            </p>
          </div>
        ) : (
          Object.entries(grouped).map(([dateLabel, msgs]) => (
            <div key={dateLabel}>
              {/* Date divider */}
              <div style={{ textAlign: 'center', margin: '16px 0 10px' }}>
                <span style={{ background: 'rgba(0,0,0,0.25)', color: 'rgba(255,255,255,0.8)', fontSize: '11px', padding: '3px 12px', borderRadius: '10px' }}>
                  {dateLabel}
                </span>
              </div>
              {msgs.map((msg) => (
                <div key={msg.id} style={{ display: 'flex', justifyContent: msg.is_mine ? 'flex-end' : 'flex-start', alignItems: 'flex-end', gap: '6px', marginBottom: '8px' }}>
                  {!msg.is_mine && (
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
                    padding: '10px 14px',
                    borderRadius: msg.is_mine ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
                    background: msg.is_mine ? 'white' : 'rgba(255,255,255,0.15)',
                    color: msg.is_mine ? '#2d3748' : 'white',
                    boxShadow: '0 1px 4px rgba(0,0,0,0.15)',
                  }}>
                    <p style={{ margin: 0, fontSize: '15px', lineHeight: '1.45', wordBreak: 'break-word' }}>{msg.content}</p>
                    <p style={{ margin: '4px 0 0', fontSize: '10px', opacity: 0.6, textAlign: 'right' }}>
                      {formatTime(msg.created_at)}
                      {msg.is_mine && (
                        <span style={{ marginLeft: '5px', color: msg.read_at ? '#667eea' : '#a0aec0' }}>
                          {msg.read_at ? '✓✓' : '✓'}
                        </span>
                      )}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Send error */}
      {sendError && (
        <div style={{ background: '#fff5f5', borderTop: '1px solid #fed7d7', padding: '8px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
          <p style={{ color: '#c53030', fontSize: '13px', margin: 0 }}>⚠️ {sendError}</p>
          <button onClick={sendMessage} style={{ padding: '4px 12px', background: '#c53030', color: 'white', border: 'none', borderRadius: '6px', fontSize: '12px', fontWeight: '600', cursor: 'pointer' }}>
            Retry
          </button>
        </div>
      )}

      {/* Message input */}
      <div style={{ background: 'white', padding: '12px 16px', display: 'flex', gap: '10px', alignItems: 'center', flexShrink: 0, borderTop: sendError ? 'none' : '1px solid #e2e8f0' }}>
        <input
          type="text"
          value={messageInput}
          ref={inputRef}
          onChange={(e) => setMessageInput(e.target.value.slice(0, 2000))}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
          placeholder={`Message ${other.name || 'them'}…`}
          disabled={sending}
          style={{ flex: 1, padding: '11px 16px', border: '2px solid #e2e8f0', borderRadius: '24px', fontSize: '15px', outline: 'none', boxSizing: 'border-box' }}
          onFocus={(e) => e.target.style.borderColor = '#667eea'}
          onBlur={(e) => e.target.style.borderColor = '#e2e8f0'}
        />
        <button
          onClick={sendMessage}
          disabled={!messageInput.trim() || sending}
          style={{
            width: '44px', height: '44px', borderRadius: '50%', border: 'none', flexShrink: 0,
            background: (!messageInput.trim() || sending) ? '#e2e8f0' : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
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
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }}>
          <div style={{ background: 'white', borderRadius: '16px', padding: '32px', maxWidth: '360px', width: '100%', textAlign: 'center', boxShadow: '0 24px 64px rgba(0,0,0,0.35)' }}>
            <div style={{ fontSize: '36px', marginBottom: '12px' }}>💔</div>
            <h2 style={{ fontSize: '18px', fontWeight: '700', color: '#2d3748', marginBottom: '8px' }}>
              Unmatch {other.name || 'this user'}?
            </h2>
            <p style={{ color: '#718096', fontSize: '14px', marginBottom: '24px', lineHeight: '1.5' }}>
              Your match and conversation will be removed. They may reappear in discover.
            </p>
            <div style={{ display: 'flex', gap: '10px' }}>
              <button onClick={() => setPendingAction(null)} style={{ flex: 1, padding: '11px', background: '#f7fafc', color: '#4a5568', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '14px', fontWeight: '600', cursor: 'pointer' }}>
                Cancel
              </button>
              <button
                onClick={() => { setPendingAction(null); handleUnmatch(currentMatch.id); }}
                style={{ flex: 1, padding: '11px', background: '#718096', color: 'white', border: 'none', borderRadius: '8px', fontSize: '14px', fontWeight: '700', cursor: 'pointer' }}
              >
                Unmatch
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Block & Report modal */}
      {pendingAction === 'block-report' && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }}>
          <div style={{ background: 'white', borderRadius: '16px', padding: '32px', maxWidth: '420px', width: '100%', boxShadow: '0 24px 64px rgba(0,0,0,0.35)' }}>
            <div style={{ fontSize: '36px', textAlign: 'center', marginBottom: '10px' }}>🚫</div>
            <h2 style={{ fontSize: '18px', fontWeight: '700', color: '#2d3748', textAlign: 'center', marginBottom: '6px' }}>
              Block &amp; Report {other.name || 'this user'}?
            </h2>
            <p style={{ color: '#718096', fontSize: '13px', textAlign: 'center', marginBottom: '20px', lineHeight: '1.5' }}>
              They'll be blocked and removed from your matches. A report will be sent to our team for review.
            </p>

            <div style={{ marginBottom: '14px' }}>
              <label style={{ display: 'block', color: '#4a5568', fontSize: '13px', fontWeight: '600', marginBottom: '6px' }}>
                Reason <span style={{ color: '#c53030' }}>*</span>
              </label>
              <select
                value={blockReportReason}
                onChange={(e) => setBlockReportReason(e.target.value)}
                style={{ width: '100%', padding: '10px 12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '14px', background: 'white', boxSizing: 'border-box', cursor: 'pointer' }}
              >
                <option value="">Select a reason…</option>
                {REPORT_REASONS.map((r) => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', color: '#4a5568', fontSize: '13px', fontWeight: '600', marginBottom: '6px' }}>
                Additional notes <span style={{ color: '#a0aec0', fontWeight: '400' }}>(optional)</span>
              </label>
              <textarea
                value={blockReportNotes}
                onChange={(e) => setBlockReportNotes(e.target.value.slice(0, 500))}
                placeholder="Any additional context…"
                rows={3}
                style={{ width: '100%', padding: '10px 12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '14px', fontFamily: 'inherit', resize: 'vertical', boxSizing: 'border-box' }}
              />
            </div>

            <div style={{ display: 'flex', gap: '10px' }}>
              <button onClick={() => setPendingAction(null)} style={{ flex: 1, padding: '11px', background: '#f7fafc', color: '#4a5568', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '14px', fontWeight: '600', cursor: 'pointer' }}>
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
    </div>
  );
}
