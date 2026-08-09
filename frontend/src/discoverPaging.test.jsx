/**
 * GAPS-ROUND-2 #58, client half.
 *
 * `GET /api/users/discover` used to return every eligible user in one response
 * and the deck simply held all of them. Now it returns a page (default 30) with
 * `X-Has-More` / `X-Next-Cursor` in the headers, so a user who swipes through a
 * page and gets nothing more has a *worse* experience than before unless the
 * client tops the deck up. That is what this covers.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import { aUser, jsonResponse, signedInRoutes } from './test-utils';
import { DISCOVER_LOW_WATER_MARK } from './shared/constants';

const profile = (id) => ({
  id,
  name: `User ${id}`,
  age: 30,
  location: 'Portland',
  bio: 'Bio.',
  animal: 'fox',
  avatar_url: null,
  personality_traits: [],
  avatar_description: null,
});

/** A discover page as the server sends it: bare array + pagination headers. */
function discoverPage(users, { hasMore, nextCursor }) {
  const res = jsonResponse(200, users);
  res.headers.set('X-Has-More', hasMore ? 'true' : 'false');
  if (nextCursor) res.headers.set('X-Next-Cursor', nextCursor);
  return res;
}

let discoverCalls;

/**
 * Serve page 1, then page 2 when the cursor comes back. Recording the URLs is
 * how we prove the client actually paged rather than refetching page 1.
 */
function mockPagedDiscover(firstPage, secondPage) {
  discoverCalls = [];
  const spy = vi.fn(async (url, options = {}) => {
    const method = (options.method || 'GET').toUpperCase();
    const href = String(url);

    if (href.includes('/api/users/discover')) {
      discoverCalls.push(href);
      return href.includes('cursor=')
        ? discoverPage(secondPage, { hasMore: false })
        : discoverPage(firstPage, { hasMore: true, nextCursor: 'CURSOR-2' });
    }
    if (href.includes('/api/swipes') && method === 'POST') {
      return jsonResponse(201, { matched: false, match: null });
    }

    const route = signedInRoutes(aUser(), []).find(
      (r) => href.includes(r.match) && (!r.method || r.method === method),
    );
    if (!route) throw new Error(`no stub for ${method} ${href}`);
    return jsonResponse(route.status ?? 200, route.body ?? {});
  });
  vi.stubGlobal('fetch', spy);
  return spy;
}

beforeEach(() => {
  vi.stubGlobal('WebSocket', class { constructor() {} close() {} send() {} });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function renderDeck() {
  render(
    <MemoryRouter initialEntries={['/discover']}>
      <App />
    </MemoryRouter>,
  );
  await screen.findByText(/User \d+/);
}

describe('discover paging', () => {
  it('asks for the next page once the deck runs low, using the server cursor', async () => {
    // One more than the low-water mark, so exactly one swipe crosses it.
    const first = Array.from({ length: DISCOVER_LOW_WATER_MARK + 1 }, (_, i) => profile(i + 1));
    mockPagedDiscover(first, [profile(500)]);
    await renderDeck();

    expect(discoverCalls).toHaveLength(1);
    expect(discoverCalls[0]).not.toContain('cursor=');

    fireEvent.click(screen.getByTitle('Like'));

    await waitFor(() => expect(discoverCalls).toHaveLength(2));
    // The cursor the server handed back, not an offset — swiping removes rows
    // from the set being paged, so offsets would skip unseen profiles.
    expect(discoverCalls[1]).toContain('cursor=CURSOR-2');
  });

  it('does not ask again when the server said there is no more', async () => {
    const first = Array.from({ length: DISCOVER_LOW_WATER_MARK + 1 }, (_, i) => profile(i + 1));
    mockPagedDiscover(first, [profile(500)]);
    await renderDeck();

    // Two swipes: the first pages in, the second finds has_more false.
    fireEvent.click(screen.getByTitle('Like'));
    await waitFor(() => expect(discoverCalls).toHaveLength(2));
    fireEvent.click(screen.getByTitle('Like'));

    await new Promise((r) => setTimeout(r, 50));
    expect(discoverCalls).toHaveLength(2);
  });

  it('appends the next page instead of replacing the deck', async () => {
    const first = Array.from({ length: DISCOVER_LOW_WATER_MARK + 1 }, (_, i) => profile(i + 1));
    mockPagedDiscover(first, [profile(500)]);
    await renderDeck();

    fireEvent.click(screen.getByTitle('Like'));
    await waitFor(() => expect(discoverCalls).toHaveLength(2));

    // The profiles that were already in the deck must still be there — a
    // replace would drop everything the user had not reached yet.
    await waitFor(() => expect(screen.getByText('User 2')).toBeInTheDocument());
  });
});
