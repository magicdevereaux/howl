import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { api } from '../../src/api/client';
import { colors as C } from '../../src/theme';

/**
 * Step 2 of password recovery — completes what forgot-password started.
 *
 * Calls the shared web endpoint `/api/auth/reset-password` for the same reason
 * forgot-password does: the route is cookie-free, so one endpoint serves both
 * clients and there is no mobile twin to keep in sync.
 *
 * The token arrives out of band. There is no deep link yet (that needs an
 * `expo-linking` scheme plus a backend redirect), so the user pastes it — and
 * because `app/services/email.py` has no provider wired, in practice today the
 * token is read out of the server log. That is GAPS #3 and it is the reason this
 * screen accepts a pasted code rather than assuming a tapped link.
 *
 * `token` is also read from the route params, so a deep link can drop straight
 * in here later without changing the screen.
 */
export default function ResetPasswordScreen() {
  const params = useLocalSearchParams<{ token?: string }>();

  const [token, setToken]       = useState(params.token ?? '');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm]   = useState('');
  const [done, setDone]         = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [loading, setLoading]   = useState(false);

  // Mirrors the backend's minimum (app/services/auth_service.py), so the user
  // finds out before spending a round trip — the server is still the authority.
  const MIN_PASSWORD = 8;

  const handleSubmit = async () => {
    if (loading) return;

    const code = token.trim();
    if (!code) {
      setError('Enter the reset code from your email.');
      return;
    }
    if (password.length < MIN_PASSWORD) {
      setError(`Your new password must be at least ${MIN_PASSWORD} characters.`);
      return;
    }
    if (password !== confirm) {
      setError('The two passwords do not match.');
      return;
    }

    setLoading(true);
    setError(null);

    const res = await api('/api/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ token: code, new_password: password }),
    });

    setLoading(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    // Every existing session was just revoked server-side (GAPS #6), so there is
    // nothing to restore — send them to sign in with the new password.
    setDone(true);
  };

  return (
    <KeyboardAvoidingView
      style={styles.shell}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
    >
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.card}>
          {done ? (
            <>
              <Text style={styles.bigEmoji} accessibilityElementsHidden>🎉</Text>
              <Text style={styles.sentTitle} accessibilityRole="header">
                Password updated
              </Text>
              <Text style={styles.sentBody}>
                You&apos;ve been signed out everywhere else for safety. Sign in with your new
                password.
              </Text>
              <Pressable
                style={({ pressed }) => [styles.button, pressed && styles.buttonPressed]}
                onPress={() => router.replace('/(auth)/login')}
                accessibilityRole="button"
                accessibilityLabel="Go to sign in"
              >
                <Text style={styles.buttonText}>Sign In</Text>
              </Pressable>
            </>
          ) : (
            <>
              <Text style={styles.title} accessibilityRole="header">Choose a new password</Text>
              <Text style={styles.subtitle}>
                Paste the reset code we sent you, then pick a new password.
              </Text>

              {error && (
                <View
                  style={styles.errorBox}
                  accessibilityRole="alert"
                  accessibilityLiveRegion="polite"
                >
                  <Text style={styles.errorText}>{error}</Text>
                </View>
              )}

              <Text style={styles.label} nativeID="reset-token-label">Reset code</Text>
              <TextInput
                style={styles.input}
                value={token}
                onChangeText={setToken}
                autoCapitalize="none"
                autoCorrect={false}
                editable={!loading}
                placeholder="Paste your reset code"
                placeholderTextColor={C.textSec}
                accessibilityLabel="Reset code"
                accessibilityLabelledBy="reset-token-label"
              />

              <Text style={styles.label} nativeID="reset-password-label">New password</Text>
              <TextInput
                style={styles.input}
                value={password}
                onChangeText={setPassword}
                secureTextEntry
                autoCapitalize="none"
                autoComplete="new-password"
                textContentType="newPassword"
                editable={!loading}
                accessibilityLabel="New password"
                accessibilityLabelledBy="reset-password-label"
                accessibilityHint={`At least ${MIN_PASSWORD} characters`}
              />

              <Text style={styles.label} nativeID="reset-confirm-label">Confirm new password</Text>
              <TextInput
                style={styles.input}
                value={confirm}
                onChangeText={setConfirm}
                secureTextEntry
                autoCapitalize="none"
                autoComplete="new-password"
                textContentType="newPassword"
                editable={!loading}
                onSubmitEditing={handleSubmit}
                returnKeyType="go"
                accessibilityLabel="Confirm new password"
                accessibilityLabelledBy="reset-confirm-label"
              />

              <Pressable
                style={({ pressed }) => [
                  styles.button,
                  pressed && styles.buttonPressed,
                  loading && styles.buttonDisabled,
                ]}
                onPress={handleSubmit}
                disabled={loading}
                accessibilityRole="button"
                accessibilityLabel={loading ? 'Updating password' : 'Update password'}
                accessibilityState={{ busy: loading, disabled: loading }}
              >
                {loading
                  ? <ActivityIndicator color={C.text} />
                  : <Text style={styles.buttonText}>Update Password</Text>}
              </Pressable>

              <Pressable
                style={styles.link}
                onPress={() => router.replace('/(auth)/login')}
                accessibilityRole="link"
                accessibilityLabel="Back to sign in"
              >
                <Text style={styles.linkText}>Back to Sign In</Text>
              </Pressable>
            </>
          )}
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  shell:  { flex: 1, backgroundColor: C.bg },
  scroll: { flexGrow: 1, justifyContent: 'center', alignItems: 'center', padding: 20, paddingVertical: 40 },
  card: {
    backgroundColor: C.bgCard,
    borderRadius: 16,
    padding: 32,
    width: '100%',
    maxWidth: 400,
    shadowColor: '#000',
    shadowOpacity: 0.5,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 10 },
    elevation: 12,
  },
  title:    { fontSize: 24, fontWeight: '700', color: C.text, textAlign: 'center', marginBottom: 8 },
  subtitle: { fontSize: 14, color: C.textSec, textAlign: 'center', marginBottom: 24, lineHeight: 20 },

  bigEmoji:  { fontSize: 44, textAlign: 'center', marginTop: 8, marginBottom: 12 },
  sentTitle: { fontSize: 16, fontWeight: '700', color: C.text, textAlign: 'center', marginBottom: 8 },
  sentBody:  { fontSize: 14, color: C.textSec, textAlign: 'center', lineHeight: 21, marginBottom: 24 },

  errorBox: {
    backgroundColor: 'rgba(197,48,48,0.15)',
    borderColor: 'rgba(197,48,48,0.4)',
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    marginBottom: 16,
  },
  errorText: { color: C.errorLight, fontSize: 13, textAlign: 'center' },

  label: { color: C.textSec, fontSize: 13, fontWeight: '500', marginBottom: 6 },
  input: {
    backgroundColor: C.bgInput,
    borderColor: C.border,
    borderWidth: 1.5,
    borderRadius: 10,
    color: C.text,
    fontSize: 16,
    paddingHorizontal: 14,
    paddingVertical: Platform.OS === 'ios' ? 14 : 11,
    marginBottom: 20,
    minHeight: 48,
  },
  button: {
    backgroundColor: C.accent,
    borderRadius: 10,
    paddingVertical: 15,
    minHeight: 50,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonPressed:  { backgroundColor: C.accentHover },
  buttonDisabled: { opacity: 0.6 },
  buttonText:     { color: C.text, fontSize: 16, fontWeight: '600' },

  link:     { alignItems: 'center', paddingVertical: 12, marginTop: 4 },
  linkText: { color: C.textSec, fontSize: 13, textDecorationLine: 'underline' },
});
