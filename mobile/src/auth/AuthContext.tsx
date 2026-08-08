import { router } from 'expo-router';
import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';

import { api, isConnectivityError, setUnauthenticatedHandler } from '../api/client';
import { syncPushToken, unregisterPushToken } from '../notifications/push';
import { clearTokens, getAccessToken, saveTokens } from './storage';

export interface User {
  id: number;
  email: string;
  name: string | null;
  age: number | null;
  location: string | null;
  bio: string | null;
  animal: string | null;
  avatar_url: string | null;
  avatar_status: string;
  personality_traits: string[] | null;
  avatar_description: string | null;
  is_email_verified: boolean;
  is_premium: boolean;
  profile_needs_regen: boolean;
}

interface AuthState {
  user: User | null;
  loading: boolean;
  /**
   * Set when we hold a token but could not reach the server to load the
   * profile. Distinct from `user === null`, which means "signed out".
   */
  bootError: string | null;
}

interface AuthContextValue extends AuthState {
  login: (email: string, password: string) => Promise<string | null>;
  logout: () => Promise<void>;
  updateUser: (user: User) => void;
  refreshUser: () => Promise<void>;
  /** Retry the startup profile load after a connectivity failure. */
  retryBoot: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({ user: null, loading: true, bootError: null });
  const [bootAttempt, setBootAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      const token = await getAccessToken();
      if (cancelled) return;
      if (!token) {
        setState({ user: null, loading: false, bootError: null });
        return;
      }

      const res = await api<User>('/api/auth/me');
      if (cancelled) return;

      if (res.ok) {
        setState({ user: res.data, loading: false, bootError: null });
        syncPushToken();
        return;
      }

      // A network failure at launch must not look like a logout — we still
      // hold a valid token, we just couldn't use it yet.
      if (isConnectivityError(res.status)) {
        setState({ user: null, loading: false, bootError: res.error });
        return;
      }

      // 401 already cleared the tokens inside api(); anything else here means
      // the stored session is unusable.
      setState({ user: null, loading: false, bootError: null });
    })();

    return () => { cancelled = true; };
  }, [bootAttempt]);

  useEffect(() => {
    setUnauthenticatedHandler(() => {
      setState({ user: null, loading: false, bootError: null });
      router.replace('/(auth)/login');
    });
  }, []);

  const retryBoot = useCallback(() => {
    setState((prev) => ({ ...prev, loading: true, bootError: null }));
    setBootAttempt((n) => n + 1);
  }, []);

  const login = useCallback(async (email: string, password: string): Promise<string | null> => {
    const res = await api<{ user: User; access_token: string; refresh_token: string }>(
      '/api/mobile/auth/login',
      { method: 'POST', body: JSON.stringify({ email, password }) },
    );
    if (!res.ok) return res.error;
    await saveTokens(res.data.access_token, res.data.refresh_token);
    setState({ user: res.data.user, loading: false, bootError: null });
    syncPushToken();
    return null;
  }, []);

  const logout = useCallback(async () => {
    // Best-effort server-side cleanup; a failure here must never trap the user
    // in a signed-in state they asked to leave.
    await unregisterPushToken();
    await clearTokens();
    setState({ user: null, loading: false, bootError: null });
    router.replace('/(auth)/login');
  }, []);

  const updateUser = useCallback((user: User) => {
    setState((prev) => ({ ...prev, user, bootError: null }));
  }, []);

  const refreshUser = useCallback(async () => {
    const res = await api<User>('/api/auth/me');
    if (res.ok) setState((prev) => ({ ...prev, user: res.data, bootError: null }));
  }, []);

  return (
    <AuthContext.Provider
      value={{ ...state, login, logout, updateUser, refreshUser, retryBoot }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
