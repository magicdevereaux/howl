import { router, Stack } from 'expo-router';
import * as Notifications from 'expo-notifications';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { GestureHandlerRootView } from 'react-native-gesture-handler';

import { AuthProvider } from '../src/auth/AuthContext';
import { EmailVerificationBanner } from '../src/components/EmailVerificationBanner';
import { ErrorBoundary } from '../src/components/ErrorBoundary';
import { EmailVerificationProvider } from '../src/contexts/EmailVerificationContext';
import { UnreadProvider } from '../src/contexts/UnreadContext';

type NotificationData = { type?: string; match_id?: number | string };

/** Route the user to the relevant screen when they tap a push notification. */
function handleNotificationResponse(response: Notifications.NotificationResponse) {
  const data = response.notification.request.content.data as NotificationData;
  if (data?.type === 'message' && data.match_id != null) {
    router.push({ pathname: '/(app)/chat/[matchId]', params: { matchId: String(data.match_id) } });
  } else if (data?.type === 'match') {
    router.push('/(app)/matches');
  }
}

export default function RootLayout() {
  useEffect(() => {
    // Cold start: app was launched by tapping a notification.
    Notifications.getLastNotificationResponseAsync()
      .then((response) => {
        if (response) handleNotificationResponse(response);
      })
      .catch((err) => {
        if (__DEV__) console.warn('[push] could not read the launch notification:', err);
      });

    // Warm start: app was already running (foreground or background).
    let subscription: Notifications.Subscription | null = null;
    try {
      subscription = Notifications.addNotificationResponseReceivedListener(
        handleNotificationResponse,
      );
    } catch (err) {
      if (__DEV__) console.warn('[push] could not subscribe to notification taps:', err);
    }
    return () => subscription?.remove();
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      {/* Outer boundary: catches failures in the providers themselves. */}
      <ErrorBoundary>
        <UnreadProvider>
          <AuthProvider>
            <EmailVerificationProvider>
              <StatusBar style="light" />
              <EmailVerificationBanner />
              {/* Inner boundary: a screen-level render throw is recoverable
                  without tearing down the session. */}
              <ErrorBoundary>
                <Stack screenOptions={{ headerShown: false }} />
              </ErrorBoundary>
            </EmailVerificationProvider>
          </AuthProvider>
        </UnreadProvider>
      </ErrorBoundary>
    </GestureHandlerRootView>
  );
}
