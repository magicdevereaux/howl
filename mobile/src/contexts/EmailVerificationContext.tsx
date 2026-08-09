import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';

import {
  EmailVerificationRequiredInfo,
  setEmailVerificationRequiredHandler,
} from '../api/client';

interface EmailVerificationContextValue {
  /**
   * Non-null once any request — a REST call or the chat WebSocket — has
   * reported that the account is past its 72h post-registration grace
   * window. Stays set until the user verifies (a fresh sign-in / app
   * restart clears it); `dismiss()` only hides the banner, since the next
   * blocked write will report it again anyway.
   */
  info: EmailVerificationRequiredInfo | null;
  dismiss: () => void;
}

const EmailVerificationContext = createContext<EmailVerificationContextValue>({
  info: null,
  dismiss: () => {},
});

export function EmailVerificationProvider({ children }: { children: React.ReactNode }) {
  const [info, setInfo] = useState<EmailVerificationRequiredInfo | null>(null);

  useEffect(() => {
    setEmailVerificationRequiredHandler(setInfo);
    return () => setEmailVerificationRequiredHandler(null);
  }, []);

  const dismiss = useCallback(() => setInfo(null), []);

  return (
    <EmailVerificationContext.Provider value={{ info, dismiss }}>
      {children}
    </EmailVerificationContext.Provider>
  );
}

export function useEmailVerification(): EmailVerificationContextValue {
  return useContext(EmailVerificationContext);
}
