import { Redirect } from 'expo-router';

import { useAuth } from '../src/auth/AuthContext';

/** Splash redirect: authenticated users go to the app, others to login. */
export default function Index() {
  const { user, loading } = useAuth();

  if (loading) return null;

  return user
    ? <Redirect href="/(app)/discover" />
    : <Redirect href="/(auth)/login" />;
}
