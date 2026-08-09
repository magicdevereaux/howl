import { createContext, useContext } from 'react';

/**
 * Session-scoped state: who is signed in, their avatar, their matches, and the
 * actions that change any of it.
 *
 * This is the context that removes the prop drilling GAPS #33 describes.
 * ProfileView took 24 props, DiscoverView 20 and ChatView 21, almost all of
 * them threaded from App purely because App is where the state lived. They read
 * what they need from here instead, and the four views now take **no props at
 * all** — the deepest consumer, the report button on a single message bubble,
 * previously needed a handler passed through three components to reach it.
 *
 * Shape mirrors mobile's AuthContext (`user`, `logout`, `updateUser`,
 * `refreshUser`) plus the `totalUnread` that mobile keeps in UnreadContext,
 * rather than inventing a third vocabulary for the same ideas — the two clients
 * drifting apart is GAPS #32.
 *
 * On memoization: the value is a plain object, so consumers re-render whenever
 * App does. That is not a regression — it is exactly what prop drilling from
 * App already did — and the boundary that actually matters for the chat is
 * MessageList's `React.memo`, which holds because its own props are stable.
 * Splitting this into finer providers is worth doing when a screen appears that
 * re-renders often *and* only needs part of it; nothing here does today.
 */
const SessionContext = createContext(null);

export const SessionProvider = SessionContext.Provider;

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) {
    // A view rendered outside the provider would otherwise fail on a property
    // access several frames later, with no hint of the cause.
    throw new Error('useSession must be used inside a SessionProvider');
  }
  return value;
}

export default SessionContext;
