import { router } from 'expo-router';
import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';

import { api, setUnauthenticatedHandler } from '../api/client';
import { clearTokens, getAccessToken, saveTokens } from './storage';

interface User {
  id: number;
  email: string;
  name: string | null;
  animal: string | null;
  avatar_url: string | null;
  avatar_status: string;
  bio: string | null;
  is_email_verified: boolean;
}

interface AuthState {
  user: User | null;
  loading: boolean;
}

interface AuthContextValue extends AuthState {
  login: (email: string, password: string) => Promise<string | null>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({ user: null, loading: true });

  // On mount: check if we have a stored token and fetch the current user.
  useEffect(() => {
    (async () => {
      const token = await getAccessToken();
      if (!token) {
        setState({ user: null, loading: false });
        return;
      }
      const res = await api<User>('/api/auth/me');
      if (res.ok) {
        setState({ user: res.data, loading: false });
      } else {
        setState({ user: null, loading: false });
      }
    })();
  }, []);

  // Wire the unauthenticated handler so the API client can force-logout.
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
    return null;
  }, []);

  const logout = useCallback(async () => {
    await clearTokens();
    setState({ user: null, loading: false });
    router.replace('/(auth)/login');
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
