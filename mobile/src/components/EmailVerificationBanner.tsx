import { useState } from 'react';
import { Platform, Pressable, StyleSheet, Text, View } from 'react-native';

import { api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { useEmailVerification } from '../contexts/EmailVerificationContext';
import { colors as C } from '../theme';

const DEFAULT_MESSAGE = 'Verify your email to keep swiping and chatting.';
const NO_EMAIL_MESSAGE = "Couldn't resend — sign in again and retry from the email you registered with.";

/**
 * Global, dismissible notice shown once any request — REST or the chat
 * WebSocket — reports the 72h post-registration grace window is over
 * (see EmailVerificationContext / src/api/client.ts). Mounted once near the
 * app root so it applies no matter which screen triggered it.
 *
 * The resend endpoint is deliberately generic (it never reveals whether an
 * address is registered or already verified), so the confirmation text here
 * stays generic too rather than branching on the response body.
 */
export function EmailVerificationBanner() {
  const { info, dismiss } = useEmailVerification();
  const { user } = useAuth();
  const [sending, setSending] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  if (!info) return null;

  const handleResend = async () => {
    if (!user?.email) {
      setFeedback(NO_EMAIL_MESSAGE);
      return;
    }
    setSending(true);
    setFeedback(null);
    // The shared cookie-free /api/auth/* endpoint — same one the mobile
    // forgot/reset-password screens use — takes the address in the body
    // rather than deriving it from the session, so it stays usable even if
    // the caller's own token has already gone stale.
    const res = await api<{ message: string }>('/api/auth/resend-verification', {
      method: 'POST',
      body: JSON.stringify({ email: user.email }),
    });
    setSending(false);
    // On success, show the server's own message rather than a duplicated
    // copy of it here — it's already worded to be account-state-agnostic
    // ("if that email is registered and not yet verified..."), and this way
    // the two can't drift apart.
    setFeedback(res.ok ? res.data.message : res.error);
  };

  return (
    <View
      style={styles.banner}
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
    >
      <View style={styles.textCol}>
        <Text style={styles.message}>{info.message || DEFAULT_MESSAGE}</Text>
        {feedback ? (
          <Text style={styles.feedback}>{feedback}</Text>
        ) : (
          <Pressable
            onPress={handleResend}
            disabled={sending}
            style={styles.resendBtn}
            accessibilityRole="button"
            accessibilityLabel={sending ? 'Sending verification email' : 'Resend verification email'}
            accessibilityState={{ disabled: sending, busy: sending }}
          >
            <Text style={styles.resendText}>{sending ? 'Sending…' : 'Resend email'}</Text>
          </Pressable>
        )}
      </View>
      <Pressable
        onPress={dismiss}
        style={styles.dismissBtn}
        hitSlop={10}
        accessibilityRole="button"
        accessibilityLabel="Dismiss this notice"
      >
        <Text style={styles.dismissText} accessibilityElementsHidden importantForAccessibility="no">✕</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
    backgroundColor: 'rgba(201,168,76,0.16)',
    borderBottomWidth: 1,
    borderBottomColor: C.gold,
    paddingHorizontal: 16,
    paddingTop: Platform.OS === 'ios' ? 54 : 28,
    paddingBottom: 12,
  },
  textCol: { flex: 1, gap: 6 },
  message: { color: C.text, fontSize: 13, lineHeight: 18 },
  feedback: { color: C.textSec, fontSize: 12, fontStyle: 'italic', lineHeight: 16 },
  resendBtn: { alignSelf: 'flex-start', paddingVertical: 4 },
  resendText: { color: C.gold, fontSize: 13, fontWeight: '700', textDecorationLine: 'underline' },
  dismissBtn: { paddingVertical: 2, paddingHorizontal: 2 },
  dismissText: { color: C.textSec, fontSize: 16, fontWeight: '600' },
});

export default EmailVerificationBanner;
