import { router } from 'expo-router';
import { useRef, useState } from 'react';
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
import { saveTokens } from '../../src/auth/storage';
import { User, useAuth } from '../../src/auth/AuthContext';
import { colors as C } from '../../src/theme';

export default function RegisterScreen() {
  const { updateUser } = useAuth();
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm]   = useState('');
  const [error, setError]       = useState<string | null>(null);
  const [loading, setLoading]   = useState(false);

  const passwordRef = useRef<TextInput>(null);
  const confirmRef  = useRef<TextInput>(null);

  const handleRegister = async () => {
    if (!email.trim() || !password || !confirm) return;
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }
    setLoading(true);
    setError(null);

    const res = await api<{ user: User; access_token: string; refresh_token: string }>(
      '/api/mobile/auth/register',
      { method: 'POST', body: JSON.stringify({ email: email.trim().toLowerCase(), password }) },
    );

    if (!res.ok) {
      setError(res.error);
      setLoading(false);
      return;
    }

    await saveTokens(res.data.access_token, res.data.refresh_token);
    updateUser(res.data.user);
    router.replace('/(app)/profile');
  };

  return (
    <KeyboardAvoidingView
      style={styles.shell}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
    >
      <ScrollView
        contentContainerStyle={styles.scroll}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.card}>
          <Text style={styles.logo} accessibilityRole="header">Join Howl 🐺</Text>
          <Text style={styles.subtitle}>Create your account</Text>

          {error && (
            <View
              style={styles.errorBox}
              accessibilityRole="alert"
              accessibilityLiveRegion="polite"
            >
              <Text style={styles.errorText}>{error}</Text>
            </View>
          )}

          <Text style={styles.label} nativeID="register-email-label">Email</Text>
          <TextInput
            style={styles.input}
            value={email}
            onChangeText={setEmail}
            placeholder="wolf@howl.app"
            placeholderTextColor={C.textDisabled}
            autoCapitalize="none"
            autoComplete="email"
            keyboardType="email-address"
            returnKeyType="next"
            onSubmitEditing={() => passwordRef.current?.focus()}
            accessibilityLabel="Email address"
            accessibilityLabelledBy="register-email-label"
          />

          <Text style={styles.label} nativeID="register-password-label">Password</Text>
          <TextInput
            ref={passwordRef}
            style={styles.input}
            value={password}
            onChangeText={setPassword}
            placeholder="8+ characters"
            placeholderTextColor={C.textDisabled}
            secureTextEntry
            autoComplete="new-password"
            textContentType="newPassword"
            returnKeyType="next"
            onSubmitEditing={() => confirmRef.current?.focus()}
            accessibilityLabel="Password"
            accessibilityLabelledBy="register-password-label"
            accessibilityHint="At least 8 characters"
          />

          <Text style={styles.label} nativeID="register-confirm-label">Confirm password</Text>
          <TextInput
            ref={confirmRef}
            style={styles.input}
            value={confirm}
            onChangeText={setConfirm}
            placeholder="••••••••"
            placeholderTextColor={C.textDisabled}
            secureTextEntry
            autoComplete="new-password"
            textContentType="newPassword"
            returnKeyType="done"
            onSubmitEditing={handleRegister}
            accessibilityLabel="Confirm password"
            accessibilityLabelledBy="register-confirm-label"
          />

          <Pressable
            style={({ pressed }) => [
              styles.button,
              pressed && styles.buttonPressed,
              loading && styles.buttonDisabled,
            ]}
            onPress={handleRegister}
            disabled={loading}
            accessibilityRole="button"
            accessibilityLabel={loading ? 'Creating your account' : 'Create account'}
            accessibilityState={{ busy: loading, disabled: loading }}
          >
            {loading
              ? <ActivityIndicator color={C.text} />
              : <Text style={styles.buttonText}>Create Account</Text>
            }
          </Pressable>

          <View style={styles.loginRow}>
            <Text style={styles.hint}>Already have an account? </Text>
            <Pressable
              onPress={() => router.replace('/(auth)/login')}
              accessibilityRole="link"
              accessibilityLabel="Sign in to an existing account"
            >
              <Text style={styles.link}>Sign in</Text>
            </Pressable>
          </View>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  shell: {
    flex: 1,
    backgroundColor: C.bg,
  },
  scroll: {
    flexGrow: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
    paddingVertical: 40,
  },
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
  logo: {
    fontSize: 32,
    fontWeight: '700',
    color: C.text,
    textAlign: 'center',
    marginBottom: 6,
    letterSpacing: 1,
  },
  subtitle: {
    fontSize: 14,
    color: C.textSec,
    textAlign: 'center',
    marginBottom: 28,
    fontStyle: 'italic',
  },
  errorBox: {
    backgroundColor: 'rgba(197,48,48,0.15)',
    borderColor: 'rgba(197,48,48,0.4)',
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    marginBottom: 16,
  },
  errorText: {
    color: C.errorLight,
    fontSize: 13,
    textAlign: 'center',
  },
  label: {
    color: C.textSec,
    fontSize: 13,
    fontWeight: '500',
    marginBottom: 6,
    marginTop: 4,
  },
  input: {
    backgroundColor: C.bgInput,
    borderColor: C.border,
    borderWidth: 1.5,
    borderRadius: 10,
    color: C.text,
    fontSize: 16,
    paddingHorizontal: 14,
    paddingVertical: Platform.OS === 'ios' ? 14 : 11,
    marginBottom: 16,
  },
  button: {
    backgroundColor: C.accent,
    borderRadius: 10,
    paddingVertical: 15,
    alignItems: 'center',
    marginTop: 4,
    marginBottom: 20,
  },
  buttonPressed: { backgroundColor: C.accentHover },
  buttonDisabled: { opacity: 0.6 },
  buttonText: {
    color: C.text,
    fontSize: 16,
    fontWeight: '600',
    letterSpacing: 0.3,
  },
  loginRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
  },
  hint: {
    color: C.textSec,
    fontSize: 13,
  },
  link: {
    color: C.accentHover,
    fontSize: 13,
    fontWeight: '600',
    textDecorationLine: 'underline',
  },
});
