/**
 * The two WebSocket events the server started sending in GAPS-ROUND-2 #49/#60.
 *
 * Both are delivered verbatim — unlike `new_message`, they carry no `message`
 * object and no `is_mine`, so the client has to reason about identity itself.
 * The field names are a contract with `app/api/chat.py`; an earlier draft of the
 * mobile client guessed `user_id`/`up_to_message_id` and silently did nothing,
 * which is exactly the failure these tests exist to make loud.
 */

import { act, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import { aMatch, aMessage, aUser, FakeWebSocket, mockApi, signedInRoutes } from './test-utils';

const MATCH = aMatch();

/** Two of the signed-in user's own messages, neither read yet. */
const myMessages = [
  aMessage({ id: 10, sender_id: 1, is_mine: true, content: 'first', read_at: null }),
  aMessage({ id: 11, sender_id: 1, is_mine: true, content: 'second', read_at: null }),
];

function routes(messages = myMessages) {
  return [
    ...signedInRoutes(aUser(), [MATCH]),
    { match: `/api/matches/${MATCH.id}/messages`, body: { messages, has_more: false } },
  ];
}

/** Deliver a server frame, flushing the state update it causes. */
function deliver(ws, payload) {
  act(() => ws.simulateMessage(payload));
}

/** Mount the app straight into the conversation and wait for the socket. */
async function openChat(messages = myMessages) {
  mockApi(routes(messages));
  render(
    <MemoryRouter initialEntries={[`/chat/${MATCH.id}`]}>
      <App />
    </MemoryRouter>,
  );
  await waitFor(() => expect(FakeWebSocket.instances.length).toBeGreaterThan(0));
  const ws = FakeWebSocket.instances.at(-1);
  act(() => ws.simulateOpen());
  await screen.findByText('first');
  return ws;
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('messages_read', () => {
  it('marks the user’s own messages read up to the high-water mark', async () => {
    const ws = await openChat();

    // Read by the *other* party (id 2), up to message 10 only.
    deliver(ws, {
      type: 'messages_read',
      match_id: MATCH.id,
      reader_id: 2,
      last_read_message_id: 10,
      read_at: '2026-08-09T12:00:00+00:00',
    });

    // ✓✓ on the message at or below the mark, ✓ on the one above it. Rendering
    // is the only observable here, which is the point — the plumbing existed
    // long before this event did, waiting for data that never arrived.
    await waitFor(() => {
      expect(screen.getByTestId('receipt-10')).toHaveTextContent('✓✓');
    });
    expect(screen.getByTestId('receipt-11')).toHaveTextContent('✓');
    expect(screen.getByTestId('receipt-11')).not.toHaveTextContent('✓✓');
  });

  it('ignores the copy echoed back to the reader’s own sockets', async () => {
    const ws = await openChat();

    // The signed-in user is id 1, and the server sends this frame to *their*
    // sockets too so a second tab can clear its badge. Applying it here would
    // show ✓✓ on messages the other party has not looked at.
    deliver(ws, {
      type: 'messages_read',
      match_id: MATCH.id,
      reader_id: 1,
      last_read_message_id: 11,
      read_at: '2026-08-09T12:00:00+00:00',
    });

    await Promise.resolve();
    expect(screen.getByTestId('receipt-10')).not.toHaveTextContent('✓✓');
    expect(screen.getByTestId('receipt-11')).not.toHaveTextContent('✓✓');
  });

  it('ignores a frame whose high-water mark is missing or not a number', async () => {
    const ws = await openChat();

    deliver(ws, { type: 'messages_read', match_id: MATCH.id, reader_id: 2 });
    deliver(ws, {
      type: 'messages_read', match_id: MATCH.id, reader_id: 2, last_read_message_id: 'ten',
    });

    await Promise.resolve();
    expect(screen.getByTestId('receipt-10')).not.toHaveTextContent('✓✓');
  });
});

describe('match_closed', () => {
  it('replaces the composer with an explanation', async () => {
    const ws = await openChat();
    expect(screen.getByPlaceholderText(/message/i)).toBeInTheDocument();

    deliver(ws, { type: 'match_closed', match_id: MATCH.id, reason: 'unmatched' });

    await screen.findByText(/this conversation has ended/i);
    // The input is gone, not merely disabled: the next send would 404, and the
    // socket is not coming back.
    expect(screen.queryByPlaceholderText(/message/i)).not.toBeInTheDocument();
  });
});

describe('unknown frames', () => {
  it('are ignored without disturbing the conversation', async () => {
    const ws = await openChat();

    deliver(ws, { type: 'something_the_server_gained_later', payload: { a: 1 } });
    deliver(ws, { not_even_a_type: true });

    await Promise.resolve();
    expect(screen.getByText('first')).toBeInTheDocument();
    expect(screen.queryByText(/this conversation has ended/i)).not.toBeInTheDocument();
  });
});
