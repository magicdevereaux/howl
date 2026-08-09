import React, { createContext, useCallback, useContext, useState } from 'react';

import { apiFetch, errorMessage, readJson } from '../api/client';
import ReportModal from '../components/ReportModal';

/**
 * Reporting a user, as one self-contained thing.
 *
 * It was previously three pieces of state and two handlers on App, a
 * `handleOpenReport` prop threaded through DiscoverView, MatchesView, ChatView
 * and the message bubbles, and a `reportModalEl` element rendered by hand in
 * four of the five route branches — remembering it in a fifth would have been
 * the obvious bug. Nothing outside this file needs to know any of that: a
 * caller wants `openReport(userId, name, messageId?)`.
 *
 * The provider renders the modal itself, so it is impossible to have the
 * opener without the dialog.
 */

const ReportContext = createContext({ openReport: () => {} });

export function ReportProvider({ children }) {
  const [target, setTarget] = useState(null); // null | { userId, name, messageId? }
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const openReport = useCallback((userId, name, messageId = undefined) => {
    setError('');
    setTarget({ userId, name, messageId });
  }, []);

  const close = useCallback(() => setTarget(null), []);

  const submit = useCallback(async (reason, notes) => {
    if (!target) return;
    setSubmitting(true);
    setError('');
    try {
      const res = await apiFetch('/api/reports', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reported_user_id: target.userId,
          reason,
          ...(notes ? { notes } : {}),
          ...(target.messageId != null ? { message_id: target.messageId } : {}),
        }),
      });
      if (res.ok) {
        setTarget(null);
      } else {
        setError(errorMessage(await readJson(res), 'Submission failed — please try again.'));
      }
    } catch (err) {
      console.error('Report submission failed', err);
      setError('Network error — please try again.');
    } finally {
      setSubmitting(false);
    }
  }, [target]);

  // Not memoized: `openReport` is the only member consumers use in a render
  // path, and it is stable. See contexts/SessionContext.jsx for the note on why
  // identity churn in these values costs nothing here.
  return (
    <ReportContext.Provider value={{ openReport }}>
      {children}
      <ReportModal
        target={target ? { name: target.name, messageId: target.messageId } : null}
        onClose={close}
        onSubmit={submit}
        submitting={submitting}
        error={error}
      />
    </ReportContext.Provider>
  );
}

export function useReport() {
  return useContext(ReportContext);
}
