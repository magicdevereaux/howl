import React, { useEffect } from 'react';
import { Navigate, useParams } from 'react-router-dom';

import ChatView from '../components/ChatView';
import Splash from '../components/Splash';
import { PATHS } from './paths';

/**
 * `/chat/:matchId` — the route that makes a conversation addressable.
 *
 * The match id in the URL is the only input, so this has to work for a cold
 * deep link (pasted URL, notification tap, refresh) and not just for a click
 * from the matches grid. That means resolving the id against the match list
 * rather than relying on state a click would have set:
 *
 *   * list not fetched yet  -> spinner, decide later
 *   * fetched, id not in it -> not your match (or unmatched) -> back to /matches
 *   * fetched and found     -> open it
 *
 * `onOpen` is the old `openChat`: it loads history and lets the WebSocket
 * effect connect. It must run for a deep link too, which is why it is an effect
 * here and not a click handler on the matches grid.
 */
export default function ChatRoute({
  matches,
  matchesLoaded,
  currentMatch,
  onOpen,
  chatProps,
}) {
  const { matchId } = useParams();
  const id = Number(matchId);
  const match = Number.isFinite(id) ? matches.find((m) => m.id === id) || null : null;
  const isOpen = currentMatch?.id === id;

  useEffect(() => {
    if (match && !isOpen) onOpen(match);
  }, [match, isOpen, onOpen]);

  if (!match) {
    // Only give up once the list is known to be complete; otherwise a refresh
    // on a valid chat URL would bounce to /matches before the fetch landed.
    if (!matchesLoaded) return <Splash label="Opening conversation…" />;
    return <Navigate to={PATHS.matches} replace />;
  }

  if (!isOpen) return <Splash label="Opening conversation…" />;

  return <ChatView currentMatch={currentMatch} {...chatProps} />;
}
