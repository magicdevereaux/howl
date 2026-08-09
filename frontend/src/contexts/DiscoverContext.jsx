import { createContext, useContext } from 'react';

/**
 * The discover screen's own state: the card stack, the swipe actions, the
 * preference filters and whatever the server has said about the daily quota.
 *
 * Separate from SessionContext because it is the one screen that uses it, and
 * because it changes on every swipe — keeping it out of the session value means
 * a swipe does not invalidate the context that the chat and profile screens
 * read from.
 */
const DiscoverContext = createContext(null);

export const DiscoverProvider = DiscoverContext.Provider;

export function useDiscover() {
  const value = useContext(DiscoverContext);
  if (!value) throw new Error('useDiscover must be used inside a DiscoverProvider');
  return value;
}

export default DiscoverContext;
