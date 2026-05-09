import React, { useState } from 'react';

const REASONS = [
  { value: 'spam_scam',             label: 'Spam or scam' },
  { value: 'inappropriate_content', label: 'Inappropriate content' },
  { value: 'harassment',            label: 'Harassment or abuse' },
  { value: 'fake_profile',          label: 'Fake or impersonating profile' },
  { value: 'underage_user',         label: 'Underage user' },
  { value: 'other',                 label: 'Other' },
];

export default function ReportModal({ target, onClose, onSubmit, submitting, error }) {
  const [reason, setReason] = useState('');
  const [notes, setNotes] = useState('');

  if (!target) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!reason) return;
    onSubmit(reason, notes.trim() || null);
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1100, padding: '20px' }}>
      <div style={{ background: 'white', borderRadius: '16px', padding: '32px', maxWidth: '420px', width: '100%', boxShadow: '0 24px 64px rgba(0,0,0,0.35)' }}>
        <div style={{ fontSize: '32px', textAlign: 'center', marginBottom: '10px' }}>🚩</div>
        <h2 style={{ fontSize: '18px', fontWeight: '700', color: '#2d3748', textAlign: 'center', marginBottom: '4px' }}>
          Report {target.name || 'this user'}
        </h2>
        <p style={{ color: '#718096', fontSize: '13px', textAlign: 'center', marginBottom: '24px' }}>
          Reports are reviewed by our team. {target.messageId ? 'The flagged message will be included.' : ''}
        </p>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '16px' }}>
            <label style={{ display: 'block', color: '#4a5568', fontSize: '13px', fontWeight: '600', marginBottom: '6px' }}>
              Reason <span style={{ color: '#c53030' }}>*</span>
            </label>
            <select
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              required
              style={{ width: '100%', padding: '10px 12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '14px', background: 'white', boxSizing: 'border-box', cursor: 'pointer' }}
            >
              <option value="">Select a reason…</option>
              {REASONS.map((r) => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          </div>

          <div style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', color: '#4a5568', fontSize: '13px', fontWeight: '600', marginBottom: '6px' }}>
              Additional notes <span style={{ color: '#a0aec0', fontWeight: '400' }}>(optional)</span>
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value.slice(0, 500))}
              placeholder="Any additional context…"
              rows={3}
              style={{ width: '100%', padding: '10px 12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '14px', fontFamily: 'inherit', resize: 'vertical', boxSizing: 'border-box' }}
            />
            <p style={{ color: '#a0aec0', fontSize: '11px', marginTop: '4px', textAlign: 'right' }}>
              {notes.length}/500
            </p>
          </div>

          {error && (
            <p style={{ color: '#c53030', fontSize: '13px', marginBottom: '12px', textAlign: 'center' }}>⚠️ {error}</p>
          )}

          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              style={{ flex: 1, padding: '11px', background: '#f7fafc', color: '#4a5568', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '14px', fontWeight: '600', cursor: 'pointer' }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!reason || submitting}
              style={{ flex: 1, padding: '11px', background: (!reason || submitting) ? '#fc8181' : '#c53030', color: 'white', border: 'none', borderRadius: '8px', fontSize: '14px', fontWeight: '700', cursor: (!reason || submitting) ? 'not-allowed' : 'pointer' }}
            >
              {submitting ? 'Submitting…' : 'Submit Report'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
