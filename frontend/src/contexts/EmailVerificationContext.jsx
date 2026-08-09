import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';

import { setVerificationRequiredHandler } from '../api/client';

/**
 * One piece of state for the whole "your email is not verified" condition.
 *
 * The backend gates four writes (swipe, undo swipe, send message, regenerate
 * avatar) once an account is 72 hours past registration without verifying, and
 * rejects the chat WebSocket at connect with close code 4403. That is five
 * places it can surface, and the user must not see five different errors — so
 * `api/client.js` recognises every one of them and reports here.
 *
 * Deliberately mirrors mobile/src/contexts/EmailVerificationContext.tsx: same
 * name, same `info` / `dismiss` shape. Two clients solving the same problem two
 * different ways is how GAPS #32 happened.
 *
 * `dismiss` only hides the notice. It does not clear the condition, because it
 * cannot: the next blocked write reports it again. Verifying is the only exit.
 */

const EmailVerificationContext = createContext({
  info: null,
  dismiss: () => {},
  email: null,
});

export function EmailVerificationProvider({ email = null, children }) {
  const [info, setInfo] = useState(null);

  useEffect(() => setVerificationRequiredHandler(setInfo), []);

  const dismiss = useCallback(() => setInfo(null), []);

  // `email` is the address the resend endpoint needs. It comes in as a prop
  // rather than being read from a session here, because the provider sits
  // inside the component that owns the user.
  const value = React.useMemo(() => ({ info, dismiss, email }), [info, dismiss, email]);

  return (
    <EmailVerificationContext.Provider value={value}>
      {children}
    </EmailVerificationContext.Provider>
  );
}

export function useEmailVerification() {
  return useContext(EmailVerificationContext);
}

export default EmailVerificationContext;
