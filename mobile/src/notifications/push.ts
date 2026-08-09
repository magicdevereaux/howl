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

/**
 * Request permission (if needed) and return this device's Expo push token.
 *
 * Every call here can reject: permission dialogs can be dismissed by the OS,
 * `getExpoPushTokenAsync` throws outright when `extra.eas.projectId` is absent
 * (see app.json / `eas init`), and channel setup fails on some Android OEMs.
 * Push is a nice-to-have, so all of it degrades to "no token" rather than
 * taking down the caller — which is the login path.
 */
async function getExpoPushToken(): Promise<string | null> {
  if (cachedToken) return cachedToken;
  if (!Device.isDevice) return null; // push tokens aren't reliable on simulators

  try {
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
    if (!projectId) {
      // Without extra.eas.projectId (populated by `eas init`, which needs the
      // account owner's EAS login — see mobile/CLAUDE.md and docs/GAPS.md #35),
      // getExpoPushTokenAsync throws and push silently never works. Logged
      // unconditionally, not gated on __DEV__: this is a standing build
      // misconfiguration rather than a transient failure, there is no crash
      // reporter wired up (see src/components/ErrorBoundary.tsx), and the
      // catch-all below would otherwise swallow this indistinguishably from
      // "user dismissed the permission dialog".
      console.warn(
        '[push] extra.eas.projectId is missing from app.json — run `eas login && ' +
        'eas init`. Push notifications cannot register until this is set.',
      );
      return null;
    }
    const result = await Notifications.getExpoPushTokenAsync({ projectId });
    cachedToken = result.data;
    return cachedToken;
  } catch (err) {
    if (__DEV__) console.warn('[push] could not obtain an Expo push token:', err);
    return null;
  }
}

/** Request permission and register this device's push token with the backend. */
export async function syncPushToken(): Promise<void> {
  const token = await getExpoPushToken();
  if (!token) return;
  const res = await api('/api/push-tokens', { method: 'POST', body: JSON.stringify({ token }) });
  if (!res.ok && __DEV__) {
    console.warn('[push] token registration failed:', res.error);
  }
}

/** Remove this device's push token from the backend, e.g. on logout. */
export async function unregisterPushToken(): Promise<void> {
  const token = cachedToken;
  if (!token) return;
  const res = await api('/api/push-tokens', { method: 'DELETE', body: JSON.stringify({ token }) });
  if (!res.ok && __DEV__) {
    console.warn('[push] token removal failed:', res.error);
  }
  // Drop the cache either way: the next sign-in re-registers it.
  cachedToken = null;
}
