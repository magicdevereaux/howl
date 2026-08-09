import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { aUser, renderApp, signedInRoutes } from './test-utils';

/**
 * GAPS-ROUND-2 #50: "A failed swipe pops the card *and* arms Undo, so the
 * next Undo destroys the previous match."
 *
 * Two independent bugs lived in the same handler:
 *
 *  1. The deck advanced and Undo was armed *before* `res.ok` was checked (and
 *     again in the network-error catch), so a 500/409/dropped connection
 *     discarded the card the user never got an answer for and pointed the
 *     next Undo at the previous, successful swipe — `DELETE /api/swipes/last`
 *     deletes the most recent actual row, which can be a real match.
 *  2. The deck was advanced positionally (`slice(1)`) rather than by the id
 *     the user actually swiped on, so a wholesale refetch racing the swipe
 *     response could remove the wrong profile.
 *
 * These tests pin the client-visible half of the fix: only mutate on success,
 * and address by id.
 */

const aDiscoverUser = (overrides = {}) => ({
  id: 42,
  name: 'Badger',
  animal: 'badger',
  avatar_url: null,
  bio: 'I dig.',
  location: 'Boise',
  personality_traits: [],
  avatar_description: null,
  ...overrides,
});

const discoverRoute = (users) => ({ match: '/api/users/discover', body: users });

const withDiscover = (users, user = aUser()) => [
  ...signedInRoutes(user).filter((r) => r.match !== '/api/users/discover'),
  discoverRoute(users),
];

describe('a swipe the server rejects (500)', () => {
  it('leaves the card in place instead of popping it', async () => {
    const user = userEvent.setup();
    renderApp('/discover', {
      routes: [
        ...withDiscover([aDiscoverUser()]),
        { match: '/api/swipes', method: 'POST', status: 500, body: {} },
      ],
    });

    await user.click(await screen.findByTitle('Like'));

    // The banner is `⚠️ {message}` inside one span, so the element's own text
    // node is broken up — match on the message substring rather than the
    // whole (icon-prefixed) node text.
    expect(await screen.findByText(/Swipe failed — tap to try again\./)).toBeInTheDocument();
    // Still there — the "tap to try again" copy promises exactly this.
    expect(screen.getByRole('heading', { name: 'Badger', level: 2 })).toBeInTheDocument();
  });

  it('does not arm Undo', async () => {
    // The dangerous half: arming Undo here means the next Undo press deletes
    // the user's *previous* successful swipe (and its match, if any), not
    // this failed one — because no row for this swipe was ever written.
    const user = userEvent.setup();
    renderApp('/discover', {
      routes: [
        ...withDiscover([aDiscoverUser()]),
        { match: '/api/swipes', method: 'POST', status: 500, body: {} },
      ],
    });

    await user.click(await screen.findByTitle('Like'));
    await screen.findByText(/Swipe failed — tap to try again\./);

    expect(screen.queryByText('↩️ Undo')).not.toBeInTheDocument();
  });
});

describe('a swipe that fails at the network layer', () => {
  it('leaves the card in place and does not arm Undo', async () => {
    const user = userEvent.setup();
    renderApp('/discover', {
      routes: [
        ...withDiscover([aDiscoverUser()]),
        {
          match: '/api/swipes',
          method: 'POST',
          handler: () => { throw new TypeError('Failed to fetch'); },
        },
      ],
    });

    await user.click(await screen.findByTitle('Like'));

    expect(await screen.findByText(/Network error — swipe may not have saved\./)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Badger', level: 2 })).toBeInTheDocument();
    expect(screen.queryByText('↩️ Undo')).not.toBeInTheDocument();
  });
});

describe('a successful swipe racing a deck refetch', () => {
  it('removes the profile that was actually swiped on, not whatever is now first', async () => {
    // Simulates GAPS-ROUND-2 #50's second bug: a nav round-trip refetches and
    // replaces `discoverUsers` wholesale while a swipe on the *first* profile
    // is still in flight. By the time the swipe response lands, the deck has
    // been reordered — id-based removal must still remove the right one.
    const user = userEvent.setup();
    const a = aDiscoverUser({ id: 1, name: 'Aardvark' });
    const b = aDiscoverUser({ id: 2, name: 'Badger' });
    const c = aDiscoverUser({ id: 3, name: 'Coyote' });

    let discoverCalls = 0;
    let resolveSwipe;
    const swipePending = new Promise((resolve) => { resolveSwipe = resolve; });

    renderApp('/discover', {
      routes: [
        ...withDiscover([], aUser()).filter((r) => r.match !== '/api/users/discover'),
        {
          match: '/api/users/discover',
          handler: () => {
            discoverCalls += 1;
            // First load: [A, B]. Refetch (nav round-trip): reordered to
            // [B, A, C] — A is still present, just no longer first.
            const body = discoverCalls === 1 ? [a, b] : [b, a, c];
            return new Response(JSON.stringify(body), { status: 200 });
          },
        },
        {
          match: '/api/swipes',
          method: 'POST',
          handler: async () => {
            await swipePending;
            return new Response(JSON.stringify({ matched: false }), { status: 200 });
          },
        },
      ],
    });

    // Deck loads as [A, B]; A is on top.
    await screen.findByRole('heading', { name: 'Aardvark', level: 2 });

    // Swipe on A. The request is deliberately left pending.
    await user.click(screen.getByTitle('Like'));

    // While it's in flight, a nav round-trip triggers a refetch that reorders
    // the deck to [B, A, C].
    await user.click(screen.getByRole('button', { name: 'Matches ❤️' }));
    await user.click(screen.getByRole('button', { name: 'Discover' }));
    await screen.findByRole('heading', { name: 'Badger', level: 2 });

    // Now let A's original swipe response resolve.
    resolveSwipe();

    // The buggy `slice(1)` would remove whatever is first *now* (Badger),
    // snapping the visible card back to Aardvark even though the user is
    // looking at — and never decided on — Badger. The fix removes Aardvark by
    // id, so Badger stays exactly where it was.
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Badger', level: 2 })).toBeInTheDocument();
    });
    expect(screen.queryByRole('heading', { name: 'Aardvark', level: 2 })).not.toBeInTheDocument();
  });
});
