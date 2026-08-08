import { router } from 'expo-router';
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
 * Step 1 of password recovery.
 *
 * Calls the shared web endpoint `/api/auth/forgot-password` — there is no
 * `/api/mobile/auth/forgot-password`, and this route needs no cookies, so the
 * shared one is correct for both clients. The response is deliberately generic
 * whether or not the address exists (see app/api/auth.py:230-256), so the
 * success copy must not imply the account was found.
 */
export default function ForgotPasswordScreen() {
  const [email, setEmail]     = useState('');
  const [sent, setSent]       = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    const address = email.trim().toLowerCase();
    if (!address || loading) return;
    setLoading(true);
    setError(null);

    const res = await api('/api/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email: address }),
    });

    setLoading(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    setSent(true);
  };

  return (
    <KeyboardAvoidingView
      style={styles.shell}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
    >
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.card}>
          <Text style={styles.title} accessibilityRole="header">Reset your password</Text>

          {sent ? (
            <View accessibilityLiveRegion="polite">
              <Text
                style={styles.bigEmoji}
                accessibilityElementsHidden
                importantForAccessibility="no"
                maxFontSizeMultiplier={1.5}
              >
                📬
              </Text>
              <Text style={styles.sentTitle}>Check your email</Text>
              <Text style={styles.sentBody}>
                If {email.trim().toLowerCase()} has a Howl account, we&apos;ve sent it a reset
                code. It expires in a few hours.
              </Text>

              <Pressable
                style={({ pressed }) => [styles.button, pressed && styles.buttonPressed]}
                onPress={() => router.push('/(auth)/reset-password')}
                accessibilityRole="button"
                accessibilityLabel="I have a reset code"
                accessibilityHint="Opens the screen where you enter your code and a new password"
              >
                <Text style={styles.buttonText}>I have a reset code</Text>
              </Pressable>

              <Pressable
                style={styles.link}
                onPress={() => router.replace('/(auth)/login')}
                accessibilityRole="link"
                accessibilityLabel="Back to sign in"
              >
                <Text style={styles.linkText}>Back to Sign In</Text>
              </Pressable>
            </View>
          ) : (
            <>
              <Text style={styles.subtitle}>
                Enter your email and we&apos;ll send you a code to set a new password.
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

              <Text style={styles.label} nativeID="forgot-email-label">Email</Text>
              <TextInput
                style={styles.input}
                value={email}
                onChangeText={setEmail}
                placeholder="wolf@howl.app"
                placeholderTextColor={C.textDisabled}
                autoCapitalize="none"
                autoComplete="email"
                keyboardType="email-address"
                returnKeyType="send"
                onSubmitEditing={handleSubmit}
                accessibilityLabel="Email"
                accessibilityLabelledBy="forgot-email-label"
                accessibilityHint="The address on your Howl account"
              />

              <Pressable
                style={({ pressed }) => [
                  styles.button,
                  pressed && styles.buttonPressed,
                  (loading || !email.trim()) && styles.buttonDisabled,
                ]}
                onPress={handleSubmit}
                disabled={loading || !email.trim()}
                accessibilityRole="button"
                accessibilityLabel={loading ? 'Sending reset code' : 'Send reset code'}
                accessibilityState={{ disabled: loading || !email.trim(), busy: loading }}
              >
                {loading
                  ? <ActivityIndicator color={C.text} />
                  : <Text style={styles.buttonText}>Send Reset Code</Text>
                }
              </Pressable>

              <Pressable
                style={styles.link}
                onPress={() => router.push('/(auth)/reset-password')}
                accessibilityRole="link"
                accessibilityLabel="I already have a reset code"
              >
                <Text style={styles.linkText}>I already have a code</Text>
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
