import { router, Stack } from 'expo-router';
import * as Notifications from 'expo-notifications';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { GestureHandlerRootView } from 'react-native-gesture-handler';

import { AuthProvider } from '../src/auth/AuthContext';
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
    Notifications.getLastNotificationResponseAsync().then((response) => {
      if (response) handleNotificationResponse(response);
    });

    // Warm start: app was already running (foreground or background).
    const subscription = Notifications.addNotificationResponseReceivedListener(
      handleNotificationResponse,
    );
    return () => subscription.remove();
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <UnreadProvider>
        <AuthProvider>
          <StatusBar style="light" />
          <Stack screenOptions={{ headerShown: false }} />
        </AuthProvider>
      </UnreadProvider>
    </GestureHandlerRootView>
  );
}
