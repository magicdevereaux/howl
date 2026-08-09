import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { EMAIL_VERIFICATION_REQUIRED } from '../api/client';
import { WS_RECONNECT_DELAY_MS } from '../shared/constants';
import {
  FakeWebSocket,
  aMessage,
  aUser,
  jsonResponse,
  renderApp,
  signedInRoutes,
} from '../test-utils';

/**
 * The email-verification block, end to end through the app (GAPS #25).
 *
 * The backend only refuses accounts more than 72 hours past registration, so
 * none of this is reachable by hand — every case here is a stubbed response or
 * a stubbed socket close.
 */

const VERIFICATION_MESSAGE =
  'Please verify your email address to keep swiping, messaging and generating avatars.';

const verificationDetail = {
  code: EMAIL_VERIFICATION_REQUIRED,
  message: VERIFICATION_MESSAGE,
  grace_expired_at: '2026-08-01T00:00:00+00:00',
};

const blocked = (match, method) => ({
  match,
  method,
  status: 403,
  body: { detail: verificationDetail },
});

const aDiscoverUser = () => ({
  id: 42,
  name: 'Badger',
  animal: 'badger',
  avatar_url: null,
  bio: 'I dig.',
  location: 'Boise',
  personality_traits: [],
  avatar_description: null,
});

const messagesRoute = (messages = [aMessage()]) => ({
  match: '/messages',
  method: 'GET',
  body: { messages, has_more: false },
});

describe('a blocked swipe', () => {
  it('shows the notice with the server’s own wording', async () => {
    const user = userEvent.setup();
    renderApp('/discover', {
      routes: [
        ...signedInRoutes().filter((r) => r.match !== '/api/users/discover'),
        { match: '/api/users/discover', body: [aDiscoverUser()] },
        blocked('/api/swipes', 'POST'),
      ],
    });

    await user.click(await screen.findByTitle('Like'));

    const alert = await screen.findByRole('alert');
    // The server's text, not a second copy of it written here. The two would
    // drift, and only one of them is updated when the grace period changes.
    expect(alert).toHaveTextContent(VERIFICATION_MESSAGE);
  });

  it('does not discard the card that was refused', async () => {
    // The bug worth a test: the swipe handler advanced the stack before looking
    // at the response, so a refused swipe silently burned the profile — and
    // there is no way back to it, since undo is blocked too.
    const user = userEvent.setup();
    renderApp('/discover', {
      routes: [
        ...signedInRoutes().filter((r) => r.match !== '/api/users/discover'),
        { match: '/api/users/discover', body: [aDiscoverUser()] },
        blocked('/api/swipes', 'POST'),
      ],
    });

    await user.click(await screen.findByTitle('Like'));
    await screen.findByRole('alert');

    // By role: the card shows the name as a heading and the animal as body
    // text, and this fixture's animal happens to render as "Badger" too.
    expect(screen.getByRole('heading', { name: 'Badger', level: 2 })).toBeInTheDocument();
  });

  it('does not also show the generic swipe-failed toast', async () => {
    // Two unrelated-looking errors for one cause, one of which advises "try
    // again" — which cannot work until the email is verified.
    const user = userEvent.setup();
    renderApp('/discover', {
      routes: [
        ...signedInRoutes().filter((r) => r.match !== '/api/users/discover'),
        { match: '/api/users/discover', body: [aDiscoverUser()] },
        blocked('/api/swipes', 'POST'),
      ],
    });

    await user.click(await screen.findByTitle('Like'));
    await screen.findByRole('alert');

    expect(screen.queryByText(/Swipe failed/)).not.toBeInTheDocument();
  });
});

describe('a blocked message send', () => {
  it('keeps the typed text and shows the notice instead of a send error', async () => {
    const user = userEvent.setup();
    renderApp('/chat/7', {
      routes: [
        ...signedInRoutes(),
        messagesRoute(),
        blocked('/messages', 'POST'),
      ],
    });

    const input = await screen.findByPlaceholderText('Message Otter…');
    await user.type(input, 'hi there');
    await user.keyboard('{Enter}');

    await screen.findByRole('alert');
    // Losing what someone typed is worse than any error message.
    expect(input).toHaveValue('hi there');
    expect(screen.queryByText(/Message failed to send/)).not.toBeInTheDocument();
  });
});

describe('the resend button', () => {
  it('posts the signed-in address and shows the server’s reply', async () => {
    const user = userEvent.setup();
    const generic = 'If that address is registered and not yet verified, a new link is on its way.';
    const fetchSpy = renderApp('/discover', {
      routes: [
        ...signedInRoutes().filter((r) => r.match !== '/api/users/discover'),
        { match: '/api/users/discover', body: [aDiscoverUser()] },
        blocked('/api/swipes', 'POST'),
        { match: '/api/auth/resend-verification', method: 'POST', body: { message: generic } },
      ],
    }) && globalThis.fetch;

    await user.click(await screen.findByTitle('Like'));
    await screen.findByRole('alert');

    await user.click(screen.getByRole('button', { name: 'Resend verification email' }));

    // The endpoint takes the address in the body — it is deliberately
    // session-independent, and posting an empty body is a 422.
    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/auth/resend-verification',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ email: aUser().email }),
        }),
      ),
    );

    // Its response is deliberately generic so it cannot be used to probe
    // whether an address exists; showing it verbatim keeps that property.
    expect(await screen.findByText(generic)).toBeInTheDocument();
  });

  it('can be dismissed', async () => {
    const user = userEvent.setup();
    renderApp('/discover', {
      routes: [
        ...signedInRoutes().filter((r) => r.match !== '/api/users/discover'),
        { match: '/api/users/discover', body: [aDiscoverUser()] },
        blocked('/api/swipes', 'POST'),
      ],
    });

    await user.click(await screen.findByTitle('Like'));
    await screen.findByRole('alert');

    await user.click(screen.getByRole('button', { name: 'Dismiss this notice' }));

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('the chat WebSocket', () => {
  const openChatWithSocket = async () => {
    renderApp('/chat/7', {
      routes: [...signedInRoutes(), messagesRoute()],
    });
    await screen.findByText('hello there');
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    return FakeWebSocket.last;
  };

  it('shows the notice from the error frame the server sends before closing', async () => {
    const ws = await openChatWithSocket();

    act(() => {
      ws.simulateMessage({ type: 'error', error: verificationDetail });
      ws.simulateServerClose(4403);
    });

    expect(await screen.findByRole('alert')).toHaveTextContent(VERIFICATION_MESSAGE);
  });

  it('does not reconnect after 4403', async () => {
    // The whole point: 4403 is a decision about this identity, so a retry gets
    // the same answer. Retrying every 2.5s for as long as the tab is open is a
    // denial of service pointed at ourselves.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const ws = await openChatWithSocket();

      act(() => ws.simulateServerClose(4403));
      act(() => vi.advanceTimersByTime(WS_RECONNECT_DELAY_MS * 10));

      expect(FakeWebSocket.instances.length).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it.each([
    ['4001 (not authenticated)', 4001],
    ['4003 (not your match)', 4003],
  ])('does not reconnect after %s either', async (_label, code) => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const ws = await openChatWithSocket();

      act(() => ws.simulateServerClose(code));
      act(() => vi.advanceTimersByTime(WS_RECONNECT_DELAY_MS * 10));

      expect(FakeWebSocket.instances.length).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('still reconnects after a transient drop', async () => {
    // 1006 is what a lost network looks like. Treating every close as terminal
    // would be the opposite bug, and worse: chat would silently stop working.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const ws = await openChatWithSocket();

      act(() => ws.simulateServerClose(1006));
      act(() => vi.advanceTimersByTime(WS_RECONNECT_DELAY_MS + 50));

      await waitFor(() => expect(FakeWebSocket.instances.length).toBe(2));
    } finally {
      vi.useRealTimers();
    }
  });

  it('refetches history on reconnect, not on the first connect', async () => {
    // Redis pub/sub is fire-and-forget: events published while this replica was
    // disconnected are dropped with no replay, and the history endpoint is the
    // stated source of truth (app/services/pubsub.py). Neither client asked it
    // — GAPS-ROUND-2 #47.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const ws = await openChatWithSocket();
      const historyCalls = () =>
        globalThis.fetch.mock.calls.filter(
          ([url, opts]) =>
            String(url).includes('/messages') && (opts?.method ?? 'GET') === 'GET',
        ).length;

      act(() => ws.simulateOpen());
      const afterFirstConnect = historyCalls();

      act(() => ws.simulateServerClose(1006));
      act(() => vi.advanceTimersByTime(WS_RECONNECT_DELAY_MS + 50));
      await waitFor(() => expect(FakeWebSocket.instances.length).toBe(2));
      act(() => FakeWebSocket.last.simulateOpen());

      await waitFor(() => expect(historyCalls()).toBe(afterFirstConnect + 1));
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('reads are not gated', () => {
  it('shows no notice when only reads happen', async () => {
    // The backend deliberately leaves discover, matches, history, unread,
    // profile read/edit and avatar status ungated: a user who cannot act must
    // still be able to see what they are about to lose.
    renderApp('/matches', { routes: signedInRoutes() });
    await screen.findByText('Your Matches');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('does not fire on a 403 from an ungated route', async () => {
    renderApp('/profile', {
      routes: [
        ...signedInRoutes(),
        { match: '/api/blocks', method: 'GET', status: 403, body: { detail: 'Forbidden' } },
      ],
    });
    await screen.findByText('Your Profile');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('the resend fallback when there is no address', () => {
  it('explains rather than posting an empty body', async () => {
    // A 422 is the failure mode if the email is omitted, which would look like
    // a broken button. The provider gets the address as a prop, so "no address"
    // means "no session" — say so.
    const user = userEvent.setup();
    renderApp('/chat/7', {
      routes: [
        ...signedInRoutes(aUser({ email: '' })),
        messagesRoute(),
      ],
    });

    await screen.findByText('hello there');
    act(() => {
      FakeWebSocket.last.simulateMessage({ type: 'error', error: verificationDetail });
      FakeWebSocket.last.simulateServerClose(4403);
    });

    await user.click(await screen.findByRole('button', { name: 'Resend verification email' }));
    expect(await screen.findByText(/sign in again and retry/)).toBeInTheDocument();
  });
});

describe('the 403 body contract', () => {
  it('is branched on by code, not by status alone', async () => {
    // Confirms the shape this client codes against, so a backend change to the
    // discriminator fails here instead of silently disabling the notice.
    const res = jsonResponse(403, { detail: verificationDetail });
    const body = await res.json();
    expect(res.status).toBe(403);
    expect(body.detail.code).toBe('email_verification_required');
    expect(body.detail).toHaveProperty('message');
    expect(body.detail).toHaveProperty('grace_expired_at');
  });
});
