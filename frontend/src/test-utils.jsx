import React from 'react';
import { render } from '@testing-library/react';
import { BrowserRouter, MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';

import App from './App';

/**
 * Test helpers shared by the routing / context / verification suites.
 *
 * The client is cookie-authenticated and talks to ten endpoints, so a test that
 * mounts <App/> has to answer whatever it asks for. `mockApi` is a tiny router
 * over `fetch`: match on a substring of the URL (plus optional method) and
 * return a status and body. Anything unmatched is a loud 500 rather than a
 * silent undefined, because a forgotten stub that looks like an empty list is
 * the kind of thing that makes a green suite meaningless.
 */

export const aUser = (overrides = {}) => ({
  id: 1,
  email: 'wolf@howl.app',
  name: 'Wolf',
  age: 30,
  location: 'Portland',
  bio: 'I howl at the moon.',
  animal: 'wolf',
  avatar_url: null,
  avatar_status: 'ready',
  personality_traits: ['loyal'],
  avatar_description: 'A wolf.',
  profile_needs_regen: false,
  is_email_verified: true,
  email_notifications: true,
  is_premium: false,
  daily_swipes: 0,
  swipes_reset_at: null,
  created_at: '2026-01-01T00:00:00+00:00',
  updated_at: '2026-01-01T00:00:00+00:00',
  ...overrides,
});

export const aMatch = (overrides = {}) => ({
  id: 7,
  matched_at: '2026-02-01T00:00:00+00:00',
  unread_count: 0,
  last_message: null,
  other_user: {
    id: 2,
    name: 'Otter',
    animal: 'otter',
    avatar_url: null,
    bio: 'I float.',
    personality_traits: [],
    avatar_description: null,
  },
  ...overrides,
});

export const aMessage = (overrides = {}) => ({
  id: 100,
  content: 'hello there',
  sender_id: 2,
  is_mine: false,
  created_at: '2026-02-02T10:00:00+00:00',
  read_at: null,
  deleted_at: null,
  ...overrides,
});

/** Build a JSON Response. Real `Response`, so `.clone()` works — the
 *  verification check in api/client.js clones a 403 before reading it. */
export const jsonResponse = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

/**
 * Install a fetch stub.
 *
 * @param routes  Array of { match, method?, status?, body?, handler? }.
 *                `match` is a substring of the URL. First match wins.
 * @returns the vi.fn() spy, so tests can assert on calls.
 */
export function mockApi(routes) {
  const spy = vi.fn(async (url, options = {}) => {
    const method = (options.method || 'GET').toUpperCase();
    const route = routes.find(
      (r) => String(url).includes(r.match) && (!r.method || r.method.toUpperCase() === method),
    );
    if (!route) {
      throw new Error(`mockApi: no stub for ${method} ${url}`);
    }
    if (route.handler) return route.handler(url, options);
    return jsonResponse(route.status ?? 200, route.body ?? {});
  });
  vi.stubGlobal('fetch', spy);
  return spy;
}

/** The stubs a signed-in <App/> needs just to boot. */
export const signedInRoutes = (user = aUser(), matches = [aMatch()]) => [
  { match: '/api/profile/me', method: 'GET', body: user },
  {
    match: '/api/avatar/status',
    body: {
      avatar_status: user.avatar_status,
      avatar_url: user.avatar_url,
      animal: user.animal,
      personality_traits: user.personality_traits,
      avatar_description: user.avatar_description,
      avatar_status_updated_at: '2026-02-01T00:00:00+00:00',
    },
  },
  { match: '/api/users/matches', body: matches },
  { match: '/api/users/discover', body: [] },
  { match: '/api/blocks', method: 'GET', body: [] },
];

/** The stubs a signed-out <App/> needs: a 401 on the session probe. */
export const signedOutRoutes = () => [
  { match: '/api/profile/me', method: 'GET', status: 401, body: { detail: 'Not authenticated' } },
];

/**
 * Stand-in for the chat WebSocket.
 *
 * jsdom ships a real WebSocket that would try to dial ws://localhost and then
 * fail asynchronously, which in this app means the reconnect timer starts — a
 * test that leaks a live reconnect loop is exactly the class of hang the pytest
 * suite already suffers from with real Redis (see CLAUDE.md). So: no sockets.
 *
 * Instances are recorded so a test can drive the connection: deliver a frame,
 * or close it with a specific application code.
 */
export class FakeWebSocket {
  static instances = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.sent = [];
    this.onmessage = null;
    this.onclose = null;
    this.onerror = null;
    this.onopen = null;
    FakeWebSocket.instances.push(this);
  }

  send(data) {
    this.sent.push(data);
  }

  close() {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code: 1000, wasClean: true });
  }

  /** Pretend the handshake completed. */
  simulateOpen() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.({});
  }

  /** Deliver a server frame (object; it is JSON-encoded for you). */
  simulateMessage(payload) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  /** Server-side close with an application code (4001 / 4003 / 4403). */
  simulateServerClose(code) {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code, wasClean: false });
  }

  static get last() {
    return FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
  }

  static reset() {
    FakeWebSocket.instances = [];
  }
}

export function stubWebSocket() {
  FakeWebSocket.reset();
  vi.stubGlobal('WebSocket', FakeWebSocket);
  return FakeWebSocket;
}

/** Render <App/> at a path, with fetch and WebSocket stubbed. */
export function renderApp(path = '/', { routes } = {}) {
  if (routes) mockApi(routes);
  stubWebSocket();
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

/**
 * Render against jsdom's real session history rather than MemoryRouter's.
 *
 * Needed for anything that exercises the *browser*: `window.history.back()`,
 * and the `?token=` / `?verify=` email links, which App reads straight off
 * `window.location.search`. MemoryRouter's history is invisible to both.
 */
export function renderAppInBrowser(url = '/', { routes } = {}) {
  if (routes) mockApi(routes);
  stubWebSocket();
  window.history.replaceState({}, '', url);
  return render(
    <BrowserRouter>
      <App />
    </BrowserRouter>,
  );
}
