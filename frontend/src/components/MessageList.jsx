import React, { useEffect, useMemo, useState } from 'react';

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

/**
 * The message bubbles, and the half of the chat that must not re-render.
 *
 * GAPS #33: "No memoization, so every keystroke in the chat input re-renders
 * the whole tree." The input's text was state on the root component, so typing
 * one character re-rendered App, every route element, ChatView, and every
 * bubble in the conversation. The fix is two-part, and the ordering matters:
 *
 *  1. MessageComposer owns the text now, so a keystroke re-renders one small
 *     component instead of the tree. That is the actual fix — no amount of
 *     memoization further down would have helped while the state lived at the
 *     root, because the memo boundary would be re-created on every render.
 *  2. This component is memoized so that the re-renders that *are* legitimate
 *     — a typing indicator arriving, a send failing — stop at the list instead
 *     of walking a hundred bubbles. It takes four props, all of which change
 *     only when the list genuinely changes; `onDelete` and `onReport` come from
 *     useCallback in ChatView for the same reason.
 *
 * The date grouping is `useMemo`d: it allocates a Map and calls
 * toLocaleDateString once per message, so it is the one piece of real work per
 * render here.
 */
function MessageList({ messages, otherName, otherId, onDelete, onReport }) {
  const [openMenuId, setOpenMenuId] = useState(null);

  useEffect(() => {
    if (!openMenuId) return;
    const close = () => setOpenMenuId(null);
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, [openMenuId]);

  const grouped = useMemo(() => {
    const acc = new Map();
    for (const msg of messages) {
      const label = formatDate(msg.created_at);
      if (!acc.has(label)) acc.set(label, []);
      acc.get(label).push(msg);
    }
    return Array.from(acc.entries());
  }, [messages]);

  return grouped.map(([dateLabel, msgs]) => (
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
              onClick={() => onReport(otherId, otherName, msg.id)}
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
                onClick={(e) => { e.stopPropagation(); setOpenMenuId(openMenuId === msg.id ? null : msg.id); }}
                title="Message options"
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-disabled)', fontSize: '16px', lineHeight: 1, padding: '2px 4px' }}
              >
                ⋮
              </button>
              {openMenuId === msg.id && (
                <div style={{ position: 'absolute', bottom: '100%', right: 0, background: 'var(--bg-card)', borderRadius: '10px', boxShadow: '0 4px 20px rgba(0,0,0,0.4)', overflow: 'hidden', minWidth: '160px', zIndex: 100, marginBottom: '4px' }}>
                  <button
                    onClick={() => { setOpenMenuId(null); onDelete(msg.id); }}
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
  ));
}

export default React.memo(MessageList);
