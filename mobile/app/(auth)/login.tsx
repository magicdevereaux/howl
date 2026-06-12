import { router } from 'expo-router';
import { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { useAuth } from '../../src/auth/AuthContext';

const BRAND = '#2D1B69';
const ACCENT = '#6B3FA0';
const ACCENT_HOVER = '#9B59D4';
const GOLD = '#C9A84C';
const BG = '#0D0B1A';
const CARD = '#130D2E';
const INPUT_BG = '#0F0B22';
const TEXT = '#FFFFFF';
const TEXT_SEC = '#B8A9D4';
const TEXT_DIS = '#7B6BA8';
const BORDER = 'rgba(255,255,255,0.1)';

export default function LoginScreen() {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleLogin = async () => {
    if (!email.trim() || !password) return;
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
      <View style={styles.card}>
        {/* Logo */}
        <Text style={styles.logo}>Howl 🐺</Text>
        <Text style={styles.subtitle}>Sign in to find your spirit animal</Text>

        {error && (
          <View style={styles.errorBox}>
            <Text style={styles.errorText}>{error}</Text>
          </View>
        )}

        {/* Email */}
        <Text style={styles.label}>Email</Text>
        <TextInput
          style={styles.input}
          value={email}
          onChangeText={setEmail}
          placeholder="wolf@howl.app"
          placeholderTextColor={TEXT_DIS}
          autoCapitalize="none"
          autoComplete="email"
          keyboardType="email-address"
          returnKeyType="next"
        />

        {/* Password */}
        <Text style={styles.label}>Password</Text>
        <TextInput
          style={styles.input}
          value={password}
          onChangeText={setPassword}
          placeholder="••••••••"
          placeholderTextColor={TEXT_DIS}
          secureTextEntry
          returnKeyType="done"
          onSubmitEditing={handleLogin}
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
        >
          {loading
            ? <ActivityIndicator color={TEXT} />
            : <Text style={styles.buttonText}>Sign In</Text>
          }
        </Pressable>

        <View style={styles.registerRow}>
          <Text style={styles.registerHint}>Don't have an account? </Text>
          <Pressable onPress={() => router.push('/(auth)/register')}>
            <Text style={[styles.linkText, { color: ACCENT_HOVER, fontWeight: '600' }]}>Create one</Text>
          </Pressable>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  shell: {
    flex: 1,
    backgroundColor: BG,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  card: {
    backgroundColor: CARD,
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
    color: TEXT,
    textAlign: 'center',
    marginBottom: 6,
    letterSpacing: 1,
  },
  subtitle: {
    fontSize: 14,
    color: TEXT_SEC,
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
    color: '#fc8181',
    fontSize: 13,
    textAlign: 'center',
  },
  label: {
    color: TEXT_SEC,
    fontSize: 13,
    fontWeight: '500',
    marginBottom: 6,
    marginTop: 4,
  },
  input: {
    backgroundColor: INPUT_BG,
    borderColor: BORDER,
    borderWidth: 1.5,
    borderRadius: 10,
    color: TEXT,
    fontSize: 16,
    paddingHorizontal: 14,
    paddingVertical: Platform.OS === 'ios' ? 14 : 11,
    marginBottom: 16,
  },
  button: {
    backgroundColor: ACCENT,
    borderRadius: 10,
    paddingVertical: 15,
    alignItems: 'center',
    marginTop: 4,
    marginBottom: 20,
  },
  buttonPressed: {
    backgroundColor: ACCENT_HOVER,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    color: TEXT,
    fontSize: 16,
    fontWeight: '600',
    letterSpacing: 0.3,
  },
  link: {
    alignItems: 'center',
    marginBottom: 12,
  },
  linkText: {
    color: TEXT_SEC,
    fontSize: 13,
    textDecorationLine: 'underline',
  },
  registerRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
  },
  registerHint: {
    color: TEXT_SEC,
    fontSize: 13,
  },
});
