import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';

import { PATHS } from './paths';
import Splash from '../components/Splash';

/**
 * Gate for the routes that need a session.
 *
 * `booting` is the state that did not exist before routing did: the old client
 * started on the login view and swapped to the profile view once the cookie
 * check came back, so a returning user saw a flash of the login form. With
 * real URLs the same shape would be worse — a deep link to /discover would
 * bounce to /login before the session had been checked. So a redirect only
 * happens once we know the answer.
 *
 * `state.from` lets the login flow return the user where they were headed.
 */
export default function RequireAuth({ user, booting, children }) {
  const location = useLocation();

  if (booting) return <Splash />;
  if (!user) {
    return <Navigate to={PATHS.login} replace state={{ from: location.pathname }} />;
  }
  return children;
}
