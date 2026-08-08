import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { colors as C } from '../theme';

interface Props {
  children: React.ReactNode;
  /** Called after the user asks to retry, before the subtree remounts. */
  onReset?: () => void;
}

interface State {
  error: Error | null;
}

/**
 * Catches render/lifecycle exceptions anywhere below it so a single bad value
 * (a null field the API used to always send, a bad `toLocaleDateString` input)
 * shows a recoverable screen instead of an empty white app.
 *
 * React has no hook equivalent — an error boundary must be a class component.
 */
export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // No crash reporter is wired up yet; the console is all we have.
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  private handleReset = () => {
    this.props.onReset?.();
    this.setState({ error: null });
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <View style={styles.shell} accessibilityRole="alert">
        <ScrollView contentContainerStyle={styles.scroll}>
          <Text style={styles.emoji} accessibilityElementsHidden importantForAccessibility="no">
            🐺
          </Text>
          <Text style={styles.title} accessibilityRole="header">
            Something went wrong
          </Text>
          <Text style={styles.body}>
            Howl hit an unexpected problem and had to stop what it was doing. Your
            account and messages are safe.
          </Text>

          {__DEV__ && (
            <Text style={styles.detail} selectable>
              {error.message}
            </Text>
          )}

          <Pressable
            style={({ pressed }) => [styles.button, pressed && styles.buttonPressed]}
            onPress={this.handleReset}
            accessibilityRole="button"
            accessibilityLabel="Try again"
            accessibilityHint="Reloads the screen that failed"
          >
            <Text style={styles.buttonText}>Try Again</Text>
          </Pressable>
        </ScrollView>
      </View>
    );
  }
}

const styles = StyleSheet.create({
  shell: { flex: 1, backgroundColor: C.bg },
  scroll: {
    flexGrow: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
  },
  emoji: { fontSize: 56, marginBottom: 16 },
  title: {
    fontSize: 22,
    fontWeight: '700',
    color: C.text,
    marginBottom: 10,
    textAlign: 'center',
  },
  body: {
    fontSize: 15,
    color: C.textSec,
    textAlign: 'center',
    lineHeight: 22,
    marginBottom: 20,
  },
  detail: {
    fontSize: 12,
    color: C.errorLight,
    fontFamily: 'monospace',
    textAlign: 'center',
    marginBottom: 20,
  },
  button: {
    backgroundColor: C.accent,
    borderRadius: 10,
    paddingHorizontal: 32,
    paddingVertical: 14,
    minHeight: 48,
    justifyContent: 'center',
  },
  buttonPressed: { backgroundColor: C.accentHover },
  buttonText: { color: C.text, fontSize: 16, fontWeight: '600' },
});

export default ErrorBoundary;
