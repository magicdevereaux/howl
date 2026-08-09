import React, { useEffect, useRef, useState } from 'react';

const MAX_LENGTH = 2000;
const TYPING_DEBOUNCE_MS = 500;

/**
 * The chat input, and the reason it exists as a component.
 *
 * The text used to be `messageInput` state on App — the root. Every keystroke
 * therefore re-rendered App, which re-created every route element, which
 * re-rendered ChatView and every message bubble in the conversation. That is
 * the concrete complaint in GAPS #33 ("no memoization, so every keystroke in
 * the chat input re-renders the whole tree"), and no `React.memo` further down
 * could have fixed it: the memo boundaries were being re-created by the same
 * render.
 *
 * Owning the text here means a keystroke re-renders this component and nothing
 * else. It also owns the send-error bar, because the bar's Retry button needs
 * the text that failed.
 *
 * `onSend` returns a promise for whether the message was accepted; the field is
 * cleared only on success. The previous version cleared optimistically and
 * restored on failure, which flickered and lost the text outright if the
 * restore path was ever missed.
 */
export default function MessageComposer({ otherName, sending, sendError, onSend, onTyping }) {
  const [text, setText] = useState('');
  const inputRef = useRef(null);
  const typingDebounceRef = useRef(null);
  const wasSending = useRef(false);

  useEffect(
    () => () => { if (typingDebounceRef.current) clearTimeout(typingDebounceRef.current); },
    [],
  );

  // Return focus to the field once a send completes, so a conversation can be
  // held from the keyboard alone.
  useEffect(() => {
    if (wasSending.current && !sending) inputRef.current?.focus();
    wasSending.current = sending;
  }, [sending]);

  const submit = async () => {
    const content = text.trim();
    if (!content || sending) return;
    const ok = await onSend(content);
    if (ok) setText('');
  };

  const handleChange = (e) => {
    setText(e.target.value.slice(0, MAX_LENGTH));
    if (typingDebounceRef.current) clearTimeout(typingDebounceRef.current);
    typingDebounceRef.current = setTimeout(() => onTyping?.(), TYPING_DEBOUNCE_MS);
  };

  const disabled = !text.trim() || sending;

  return (
    <>
      {sendError && (
        <div style={{ background: 'rgba(197,48,48,0.15)', borderTop: '1px solid rgba(197,48,48,0.3)', padding: '8px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
          <p style={{ color: '#fc8181', fontSize: '13px', margin: 0 }}>⚠️ {sendError}</p>
          <button onClick={submit} style={{ padding: '4px 12px', background: '#c53030', color: 'white', border: 'none', borderRadius: '6px', fontSize: '12px', fontWeight: '600', cursor: 'pointer' }}>
            Retry
          </button>
        </div>
      )}

      <div style={{ background: 'var(--bg-card)', padding: '12px 16px', display: 'flex', gap: '10px', alignItems: 'center', flexShrink: 0, borderTop: sendError ? 'none' : '1px solid var(--border)' }}>
        <input
          type="text"
          value={text}
          ref={inputRef}
          onChange={handleChange}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } }}
          placeholder={`Message ${otherName || 'them'}…`}
          disabled={sending}
          style={{ flex: 1, padding: '11px 16px', border: '2px solid var(--border)', borderRadius: '24px', fontSize: '15px', outline: 'none', boxSizing: 'border-box', background: 'var(--bg-input)', color: 'var(--text-primary)' }}
          onFocus={(e) => e.target.style.borderColor = '#6B3FA0'}
          onBlur={(e) => e.target.style.borderColor = 'rgba(255,255,255,0.1)'}
        />
        <button
          onClick={submit}
          disabled={disabled}
          aria-label="Send message"
          style={{
            width: '44px', height: '44px', borderRadius: '50%', border: 'none', flexShrink: 0,
            background: disabled ? 'var(--bg-hover)' : 'var(--gradient-brand)',
            cursor: disabled ? 'not-allowed' : 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px',
            transition: 'background 0.15s',
          }}
        >
          ➤
        </button>
      </div>
    </>
  );
}
