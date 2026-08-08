import * as SecureStore from 'expo-secure-store';

const ACCESS_KEY = 'howl_access_token';
const REFRESH_KEY = 'howl_refresh_token';

/**
 * SecureStore talks to the platform keychain/keystore and can genuinely fail
 * (locked keychain, corrupted entry, unsupported device). None of the callers
 * can do anything useful with the exception, and an unhandled rejection here
 * kills the app on launch — so every operation degrades to "no token".
 */

export async function saveTokens(accessToken: string, refreshToken: string): Promise<void> {
  try {
    await SecureStore.setItemAsync(ACCESS_KEY, accessToken);
    await SecureStore.setItemAsync(REFRESH_KEY, refreshToken);
  } catch {
    // Nothing we can do — the session simply won't survive an app restart.
  }
}

export async function saveAccessToken(accessToken: string): Promise<void> {
  try {
    await SecureStore.setItemAsync(ACCESS_KEY, accessToken);
  } catch {
    /* see saveTokens */
  }
}

export async function getAccessToken(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(ACCESS_KEY);
  } catch {
    return null;
  }
}

export async function getRefreshToken(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(REFRESH_KEY);
  } catch {
    return null;
  }
}

export async function clearTokens(): Promise<void> {
  try {
    await SecureStore.deleteItemAsync(ACCESS_KEY);
  } catch {
    /* see saveTokens */
  }
  try {
    await SecureStore.deleteItemAsync(REFRESH_KEY);
  } catch {
    /* see saveTokens */
  }
}
