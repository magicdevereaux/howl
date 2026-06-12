import { router } from 'expo-router';
import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';

import { api, setUnauthenticatedHandler } from '../api/client';
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
}

interface AuthContextValue extends AuthState {
  login: (email: string, password: string) => Promise<string | null>;
  logout: () => Promise<void>;
  updateUser: (user: User) => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({ user: null, loading: true });

  useEffect(() => {
    (async () => {
      const token = await getAccessToken();
      if (!token) {
        setState({ user: null, loading: false });
        return;
      }
      const res = await api<User>('/api/auth/me');
      setState({ user: res.ok ? res.data : null, loading: false });
      if (res.ok) syncPushToken();
    })();
  }, []);

  useEffect(() => {
    setUnauthenticatedHandler(() => {
      setState({ user: null, loading: false });
      router.replace('/(auth)/login');
    });
  }, []);

  const login = useCallback(async (email: string, password: string): Promise<string | null> => {
    const res = await api<{ user: User; access_token: string; refresh_token: string }>(
      '/api/mobile/auth/login',
      { method: 'POST', body: JSON.stringify({ email, password }) },
    );
    if (!res.ok) return res.error;
    await saveTokens(res.data.access_token, res.data.refresh_token);
    setState({ user: res.data.user, loading: false });
    syncPushToken();
    return null;
  }, []);

  const logout = useCallback(async () => {
    await unregisterPushToken();
    await clearTokens();
    setState({ user: null, loading: false });
    router.replace('/(auth)/login');
  }, []);

  const updateUser = useCallback((user: User) => {
    setState((prev) => ({ ...prev, user }));
  }, []);

  const refreshUser = useCallback(async () => {
    const res = await api<User>('/api/auth/me');
    if (res.ok) setState((prev) => ({ ...prev, user: res.data }));
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, logout, updateUser, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
