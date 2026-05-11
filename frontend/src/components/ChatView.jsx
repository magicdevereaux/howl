import React, { useEffect, useRef, useState } from 'react';
import { animalEmoji, avatarUrl } from '../utils';

export default function ChatView({
  currentMatch, messages, setMessages,
  messagesLoading, messagesError, messageInput, setMessageInput,
  sending, sendError, sendMessage, loadMessages,
  handleUnmatch, handleBlock, handleOpenReport,
  setView, fetchMatches,
}) {
  const other = currentMatch.other_user;
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const wasSending = useRef(false);
  const [pendingAction, setPendingAction] = useState(null); // 'unmatch' | 'block' | null

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

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
        <div style={{ marginLeft: 'auto', display: 'flex', gap: '8px' }}>
          <button
            onClick={() => setPendingAction('unmatch')}
            style={{ background: 'rgba(255,255,255,0.12)', border: '1px solid rgba(255,255,255,0.25)', color: 'rgba(255,255,255,0.8)', borderRadius: '8px', padding: '6px 12px', cursor: 'pointer', fontSize: '13px' }}
          >
            Unmatch
          </button>
          <button
            onClick={() => setPendingAction('block')}
            style={{ background: 'rgba(229,62,62,0.25)', border: '1px solid rgba(229,62,62,0.4)', color: '#feb2b2', borderRadius: '8px', padding: '6px 12px', cursor: 'pointer', fontSize: '13px' }}
          >
            Block
          </button>
          <button
            onClick={() => handleOpenReport(other.id, other.name)}
            title="Report this user"
            style={{ background: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.2)', color: 'rgba(255,255,255,0.6)', borderRadius: '8px', padding: '6px 10px', cursor: 'pointer', fontSize: '13px' }}
          >
            🚩
          </button>
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
      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 16px', display: 'flex', flexDirection: 'column' }}>
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

      {/* Unmatch / Block confirmation modal */}
      {pendingAction && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }}>
          <div style={{ background: 'white', borderRadius: '16px', padding: '32px', maxWidth: '360px', width: '100%', textAlign: 'center', boxShadow: '0 24px 64px rgba(0,0,0,0.35)' }}>
            <div style={{ fontSize: '36px', marginBottom: '12px' }}>{pendingAction === 'block' ? '🚫' : '💔'}</div>
            <h2 style={{ fontSize: '18px', fontWeight: '700', color: '#2d3748', marginBottom: '8px' }}>
              {pendingAction === 'block' ? `Block ${other.name || 'this user'}?` : `Unmatch ${other.name || 'this user'}?`}
            </h2>
            <p style={{ color: '#718096', fontSize: '14px', marginBottom: '24px', lineHeight: '1.5' }}>
              {pendingAction === 'block'
                ? 'They\'ll be removed from your matches and won\'t appear in discover. This cannot be undone.'
                : 'Your match and conversation will be removed. They may reappear in discover.'}
            </p>
            <div style={{ display: 'flex', gap: '10px' }}>
              <button
                onClick={() => setPendingAction(null)}
                style={{ flex: 1, padding: '11px', background: '#f7fafc', color: '#4a5568', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '14px', fontWeight: '600', cursor: 'pointer' }}
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setPendingAction(null);
                  if (pendingAction === 'unmatch') handleUnmatch(currentMatch.id);
                  else handleBlock(other.id);
                }}
                style={{ flex: 1, padding: '11px', background: pendingAction === 'block' ? '#c53030' : '#718096', color: 'white', border: 'none', borderRadius: '8px', fontSize: '14px', fontWeight: '700', cursor: 'pointer' }}
              >
                {pendingAction === 'block' ? 'Block' : 'Unmatch'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
