import { Redirect, Stack } from 'expo-router';

import { useAuth } from '../../src/auth/AuthContext';

/** Protected layout — redirects to login if not authenticated. */
export default function AppLayout() {
  const { user, loading } = useAuth();

  if (loading) return null;
  if (!user) return <Redirect href="/(auth)/login" />;

  return <Stack screenOptions={{ headerShown: false }} />;
}
