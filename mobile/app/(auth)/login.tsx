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

import { useAuth } from '../../src/auth/AuthContext';
import { colors as C } from '../../src/theme';

export default function LoginScreen() {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const passwordRef = useRef<TextInput>(null);

  const handleLogin = async () => {
    if (!email.trim() || !password || loading) return;
    setLoading(true);
    setError(null);
    const err = await login(email.trim().toLowerCase(), password);
    if (err) {
      setError(err);
      setLoading(false);
    } else {
      router.replace('/(app)/discover');
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.shell}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
    >
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.card}>
          {/* Logo */}
          <Text
            style={styles.logo}
            accessibilityRole="header"
            accessibilityLabel="Howl"
          >
            Howl 🐺
          </Text>
          <Text style={styles.subtitle}>Sign in to find your spirit animal</Text>

          {error && (
            <View
              style={styles.errorBox}
              accessibilityRole="alert"
              accessibilityLiveRegion="polite"
            >
              <Text style={styles.errorText}>{error}</Text>
            </View>
          )}

          {/* Email */}
          <Text style={styles.label} nativeID="login-email-label">Email</Text>
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
            accessibilityLabel="Email"
            accessibilityLabelledBy="login-email-label"
            accessibilityHint="Enter the email address you registered with"
          />

          {/* Password */}
          <Text style={styles.label} nativeID="login-password-label">Password</Text>
          <TextInput
            ref={passwordRef}
            style={styles.input}
            value={password}
            onChangeText={setPassword}
            placeholder="••••••••"
            placeholderTextColor={C.textDisabled}
            secureTextEntry
            autoComplete="current-password"
            returnKeyType="done"
            onSubmitEditing={handleLogin}
            accessibilityLabel="Password"
            accessibilityLabelledBy="login-password-label"
          />

          {/* Sign in button */}
          <Pressable
            style={({ pressed }) => [
              styles.button,
              pressed && styles.buttonPressed,
              loading && styles.buttonDisabled,
            ]}
            onPress={handleLogin}
            disabled={loading}
            accessibilityRole="button"
            accessibilityLabel={loading ? 'Signing in' : 'Sign in'}
            accessibilityState={{ disabled: loading, busy: loading }}
          >
            {loading
              ? <ActivityIndicator color={C.text} />
              : <Text style={styles.buttonText}>Sign In</Text>
            }
          </Pressable>

          <Pressable
            style={styles.link}
            onPress={() => router.push('/(auth)/forgot-password')}
            accessibilityRole="link"
            accessibilityLabel="Forgot your password?"
            accessibilityHint="Opens the password reset screen"
          >
            <Text style={styles.linkText}>Forgot your password?</Text>
          </Pressable>

          <View style={styles.registerRow}>
            <Text style={styles.registerHint}>Don&apos;t have an account? </Text>
            <Pressable
              onPress={() => router.push('/(auth)/register')}
              hitSlop={8}
              accessibilityRole="link"
              accessibilityLabel="Create an account"
            >
              <Text style={styles.createLink}>Create one</Text>
            </Pressable>
          </View>

          <View style={styles.legalRow}>
            <Pressable
              onPress={() => router.push({ pathname: '/legal', params: { doc: 'privacy' } })}
              hitSlop={8}
              accessibilityRole="link"
              accessibilityLabel="Privacy Policy"
            >
              <Text style={styles.legalLink}>Privacy Policy</Text>
            </Pressable>
            <Text
              style={styles.legalDot}
              accessibilityElementsHidden
              importantForAccessibility="no"
            >
              ·
            </Text>
            <Pressable
              onPress={() => router.push({ pathname: '/legal', params: { doc: 'terms' } })}
              hitSlop={8}
              accessibilityRole="link"
              accessibilityLabel="Terms of Service"
            >
              <Text style={styles.legalLink}>Terms of Service</Text>
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
    minHeight: 48,
  },
  button: {
    backgroundColor: C.accent,
    borderRadius: 10,
    paddingVertical: 15,
    minHeight: 50,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 4,
    marginBottom: 8,
  },
  buttonPressed: {
    backgroundColor: C.accentHover,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    color: C.text,
    fontSize: 16,
    fontWeight: '600',
    letterSpacing: 0.3,
  },
  link: {
    alignItems: 'center',
    paddingVertical: 10,
    marginBottom: 6,
  },
  linkText: {
    color: C.textSec,
    fontSize: 13,
    textDecorationLine: 'underline',
  },
  registerRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    flexWrap: 'wrap',
  },
  registerHint: {
    color: C.textSec,
    fontSize: 13,
  },
  createLink: {
    color: C.accentHover,
    fontSize: 13,
    fontWeight: '600',
    textDecorationLine: 'underline',
  },
  legalRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 20,
  },
  legalLink: {
    color: C.textDisabled,
    fontSize: 12,
    textDecorationLine: 'underline',
  },
  legalDot: {
    color: C.textDisabled,
    fontSize: 12,
  },
});
