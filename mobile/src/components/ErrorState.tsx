import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { isConnectivityError } from '../api/client';
import { colors as C } from '../theme';

interface Props {
  /** Human-readable message from an `ApiFailure`. */
  message: string;
  /** Synthetic or HTTP status from an `ApiFailure`, used to pick the icon/title. */
  status?: number;
  onRetry?: () => void;
  retrying?: boolean;
  /** Renders inline (banner) instead of filling the screen. */
  compact?: boolean;
}

/**
 * Full-screen or inline "this failed, try again" block. Centralises the retry
 * affordance and its accessibility labelling so every screen behaves the same.
 */
export function ErrorState({ message, status, onRetry, retrying, compact }: Props) {
  const offline = status != null && isConnectivityError(status);
  const title = offline ? 'No connection' : 'Something went wrong';

  if (compact) {
    return (
      <View style={styles.banner} accessibilityRole="alert" accessibilityLiveRegion="polite">
        <Text style={styles.bannerText}>{message}</Text>
        {onRetry && (
          <Pressable
            onPress={onRetry}
            disabled={retrying}
            hitSlop={8}
            style={styles.bannerRetry}
            accessibilityRole="button"
            accessibilityLabel="Retry"
            accessibilityState={{ disabled: !!retrying }}
          >
            <Text style={styles.bannerRetryText}>{retrying ? '…' : 'Retry'}</Text>
          </Pressable>
        )}
      </View>
    );
  }

  return (
    <View style={styles.center} accessibilityRole="alert" accessibilityLiveRegion="polite">
      <Text
        style={styles.emoji}
        accessibilityElementsHidden
        importantForAccessibility="no"
        maxFontSizeMultiplier={1.6}
      >
        {offline ? '📡' : '⚠️'}
      </Text>
      <Text style={styles.title} accessibilityRole="header">
        {title}
      </Text>
      <Text style={styles.message}>{message}</Text>
      {onRetry && (
        <Pressable
          style={({ pressed }) => [styles.button, pressed && styles.buttonPressed]}
          onPress={onRetry}
          disabled={retrying}
          accessibilityRole="button"
          accessibilityLabel="Try again"
          accessibilityState={{ disabled: !!retrying, busy: !!retrying }}
        >
          {retrying ? (
            <ActivityIndicator color={C.text} size="small" />
          ) : (
            <Text style={styles.buttonText}>Try Again</Text>
          )}
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  emoji: { fontSize: 44, marginBottom: 14 },
  title: { fontSize: 19, fontWeight: '700', color: C.text, marginBottom: 8, textAlign: 'center' },
  message: {
    fontSize: 14,
    color: C.textSec,
    textAlign: 'center',
    lineHeight: 21,
    marginBottom: 22,
  },
  button: {
    backgroundColor: C.accent,
    borderRadius: 10,
    paddingHorizontal: 28,
    paddingVertical: 13,
    minHeight: 48,
    minWidth: 140,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonPressed: { backgroundColor: C.accentHover },
  buttonText: { color: C.text, fontSize: 15, fontWeight: '600' },

  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: 'rgba(197,48,48,0.18)',
    borderColor: 'rgba(197,48,48,0.4)',
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  bannerText: { flex: 1, color: C.errorLight, fontSize: 13, lineHeight: 19 },
  bannerRetry: { paddingHorizontal: 8, paddingVertical: 6, minHeight: 32, justifyContent: 'center' },
  bannerRetryText: { color: C.text, fontSize: 13, fontWeight: '700', textDecorationLine: 'underline' },
});

export default ErrorState;
