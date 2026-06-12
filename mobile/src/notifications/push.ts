import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { api } from '../api/client';

// Show alerts/sounds even while the app is in the foreground.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
  }),
});

let cachedToken: string | null = null;

/** Request permission (if needed) and return this device's Expo push token. */
async function getExpoPushToken(): Promise<string | null> {
  if (cachedToken) return cachedToken;
  if (!Device.isDevice) return null; // push tokens aren't reliable on simulators

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;
  if (existingStatus !== 'granted') {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }
  if (finalStatus !== 'granted') return null;

  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('default', {
      name: 'default',
      importance: Notifications.AndroidImportance.DEFAULT,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: '#9B59D4',
    });
  }

  const projectId = Constants.expoConfig?.extra?.eas?.projectId;
  const result = await Notifications.getExpoPushTokenAsync(
    projectId ? { projectId } : undefined,
  );
  cachedToken = result.data;
  return cachedToken;
}

/** Request permission and register this device's push token with the backend. */
export async function syncPushToken(): Promise<void> {
  const token = await getExpoPushToken();
  if (!token) return;
  await api('/api/push-tokens', { method: 'POST', body: JSON.stringify({ token }) });
}

/** Remove this device's push token from the backend, e.g. on logout. */
export async function unregisterPushToken(): Promise<void> {
  const token = cachedToken;
  if (!token) return;
  await api('/api/push-tokens', { method: 'DELETE', body: JSON.stringify({ token }) });
}
