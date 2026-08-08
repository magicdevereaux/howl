import { Redirect } from 'expo-router';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { useAuth } from '../src/auth/AuthContext';
import { ErrorState } from '../src/components/ErrorState';
import { STATUS_OFFLINE } from '../src/api/client';
import { colors } from '../src/theme';

/** Splash redirect: authenticated users go to the app, others to login. */
export default function Index() {
  const { user, loading, bootError, retryBoot } = useAuth();

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator
          color={colors.accentHover}
          size="large"
          accessibilityLabel="Loading Howl"
        />
      </View>
    );
  }

  // We hold a session token but couldn't reach the server. Offer a retry
  // instead of dumping the user on the sign-in screen they don't need.
  if (bootError) {
    return (
      <View style={styles.shell}>
        <ErrorState message={bootError} status={STATUS_OFFLINE} onRetry={retryBoot} />
      </View>
    );
  }

  return user
    ? <Redirect href="/(app)/discover" />
    : <Redirect href="/(auth)/login" />;
}

const styles = StyleSheet.create({
  shell:  { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.bg },
});
