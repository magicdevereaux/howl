import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { aUser, renderApp, signedInRoutes } from './test-utils';

/**
 * GAPS #32: `DAILY_SWIPE_LIMIT = 20` was hardcoded in the web client, and the
 * exhausted panel had the same 20 written into its copy.
 *
 * The backend is the sole authority — `_DAILY_SWIPE_LIMIT` in app/api/swipes.py,
 * enforced by a conditional UPDATE whose rowcount decides. The client's job is
 * to display what the API tells it, and to display nothing where the API has
 * not spoken.
 */

const SERVER_MESSAGE =
  "You've used all 20 free swipes for today. Upgrade to premium for unlimited swiping.";

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

const limitReached = (resetsAt = new Date(Date.now() + 6 * 3600000).toISOString()) => ({
  match: '/api/swipes',
  method: 'POST',
  status: 429,
  body: {
    detail: {
      code: 'daily_limit_reached',
      message: SERVER_MESSAGE,
      limit: 20,
      resets_at: resetsAt,
    },
  },
});

describe('before the server has stated the limit', () => {
  it('does not block swiping on a locally-assumed quota', async () => {
    // The old client compared daily_swipes against its own constant and greyed
    // the screen out at 20 without asking. If the server limit were raised, it
    // would lock users out early and tell them the wrong number.
    const user = userEvent.setup();
    renderApp('/discover', {
      routes: [
        ...withDiscover([aDiscoverUser()], aUser({ daily_swipes: 25 })),
        { match: '/api/swipes', method: 'POST', body: { matched: false } },
      ],
    });

    expect(await screen.findByRole('heading', { name: 'Badger', level: 2 })).toBeInTheDocument();
    expect(screen.queryByText(/out of swipes/)).not.toBeInTheDocument();

    // And it can still swipe: the server decides, and here it allowed it.
    await user.click(screen.getByTitle('Like'));
    const posted = globalThis.fetch.mock.calls.filter(
      ([url, opts]) => String(url).includes('/api/swipes') && opts?.method === 'POST',
    );
    expect(posted).toHaveLength(1);
  });

  it('shows swipes used rather than a remaining count it cannot know', async () => {
    // "N left" requires the limit. Until the server states it, the count of
    // swipes used is the truthful signal — it comes straight from UserOut.
    renderApp('/discover', {
      routes: withDiscover([aDiscoverUser()], aUser({ daily_swipes: 3 })),
    });

    expect(await screen.findByText('3 swipes used today')).toBeInTheDocument();
    expect(screen.queryByText(/left today/)).not.toBeInTheDocument();
  });

  it('says nothing at all before the first swipe of the day', async () => {
    renderApp('/discover', {
      routes: withDiscover([aDiscoverUser()], aUser({ daily_swipes: 0 })),
    });

    await screen.findByRole('heading', { name: 'Badger', level: 2 });
    expect(screen.queryByText(/swipes used today/)).not.toBeInTheDocument();
    expect(screen.queryByText(/left today/)).not.toBeInTheDocument();
  });

  it('shows nothing for a premium account, which has no quota', async () => {
    renderApp('/discover', {
      routes: withDiscover([aDiscoverUser()], aUser({ is_premium: true, daily_swipes: 99 })),
    });

    await screen.findByRole('heading', { name: 'Badger', level: 2 });
    expect(screen.queryByText(/swipes used today/)).not.toBeInTheDocument();
    expect(screen.queryByText(/out of swipes/)).not.toBeInTheDocument();
  });
});

describe('once the server refuses a swipe', () => {
  it('renders the server’s sentence, not a copy of it', async () => {
    const user = userEvent.setup();
    renderApp('/discover', {
      routes: [...withDiscover([aDiscoverUser()]), limitReached()],
    });

    await user.click(await screen.findByTitle('Like'));

    expect(await screen.findByText(SERVER_MESSAGE)).toBeInTheDocument();
    expect(screen.getByText("You're out of swipes!")).toBeInTheDocument();
  });

  it('uses the server’s reset time instead of recomputing the window', async () => {
    // The old panel added its own 86400000 to swipes_reset_at, duplicating
    // _SWIPE_WINDOW_SECONDS. `resets_at` is computed by the code that enforces
    // the window.
    const user = userEvent.setup();
    renderApp('/discover', {
      routes: [
        ...withDiscover([aDiscoverUser()]),
        limitReached(new Date(Date.now() + 6 * 3600000).toISOString()),
      ],
    });

    await user.click(await screen.findByTitle('Like'));
    expect(await screen.findByText('Resets in ~6h')).toBeInTheDocument();
  });

  it('never renders a negative countdown for a reset time in the past', async () => {
    const user = userEvent.setup();
    renderApp('/discover', {
      routes: [
        ...withDiscover([aDiscoverUser()]),
        limitReached(new Date(Date.now() - 3600000).toISOString()),
      ],
    });

    await user.click(await screen.findByTitle('Like'));
    expect(await screen.findByText('Resets in ~0h')).toBeInTheDocument();
  });

  it('does not consume the card it refused', async () => {
    // Same class of bug as the verification 403: the stack must not advance on a
    // swipe the server rejected.
    const user = userEvent.setup();
    renderApp('/discover', {
      routes: [...withDiscover([aDiscoverUser(), aDiscoverUser({ id: 43, name: 'Stoat' })]), limitReached()],
    });

    await user.click(await screen.findByTitle('Like'));
    await screen.findByText(SERVER_MESSAGE);
    expect(screen.queryByRole('heading', { name: 'Stoat', level: 2 })).not.toBeInTheDocument();
  });

  it('falls back to its own wording only if the server sends none', async () => {
    const user = userEvent.setup();
    renderApp('/discover', {
      routes: [
        ...withDiscover([aDiscoverUser()]),
        {
          match: '/api/swipes',
          method: 'POST',
          status: 429,
          body: { detail: { code: 'daily_limit_reached', limit: 20 } },
        },
      ],
    });

    await user.click(await screen.findByTitle('Like'));
    expect(
      await screen.findByText('You have used all your free swipes for today.'),
    ).toBeInTheDocument();
  });
});

describe('no client-side limit constant survives', () => {
  it('is absent from the shared constants module', async () => {
    // The shared file states the rule in its own header: quotas live in app/ and
    // must reach the client over the API. This asserts it.
    const constants = await import('./shared/constants');
    const names = Object.keys(constants);
    expect(names.filter((n) => /LIMIT|QUOTA|SWIPE/i.test(n))).toEqual([]);
  });
});
