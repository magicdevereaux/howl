import { createContext, useContext } from 'react';

/**
 * One conversation: its messages, its pagination, and the actions that act on
 * it or on the person at the other end.
 *
 * Kept out of SessionContext for the same reason as DiscoverContext — a message
 * arriving should not invalidate the value the profile screen reads — and
 * because `currentMatch` is only meaningful while a chat is open.
 */
const ChatContext = createContext(null);

export const ChatProvider = ChatContext.Provider;

export function useChat() {
  const value = useContext(ChatContext);
  if (!value) throw new Error('useChat must be used inside a ChatProvider');
  return value;
}

export default ChatContext;
