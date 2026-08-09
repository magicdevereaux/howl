import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import {
  aMatch,
  aMessage,
  renderApp,
  renderAppInBrowser,
  signedInRoutes,
  signedOutRoutes,
} from '../test-utils';

/**
 * GAPS #33: the client had no URLs. A `view` string in App.jsx decided what
 * rendered, so the back button did nothing, nothing could be linked to, and the
 * mobile app could not point at the Privacy Policy (GAPS #35).
 *
 * These tests are about addresses, not markup: every route renders its own
 * screen, protected routes bounce when there is no session, and a chat is
 * reachable cold from its URL.
 */

const messagesRoute = (messages = [aMessage()]) => ({
  match: '/messages',
  method: 'GET',
  body: { messages, has_more: false },
});

describe('public routes', () => {
  it('renders the login screen at /login', async () => {
    renderApp('/login', { routes: signedOutRoutes() });
    expect(await screen.findByText('Welcome to Howl 🐺')).toBeInTheDocument();
  });

  it('renders the register screen at /register', async () => {
    renderApp('/register', { routes: signedOutRoutes() });
    expect(await screen.findByText('Join Howl 🐺')).toBeInTheDocument();
  });

  it('renders the privacy policy at /privacy', async () => {
    // The exact path the mobile client deep-links to. Signed out on purpose:
    // an app-store reviewer opens it without an account.
    renderApp('/privacy', { routes: signedOutRoutes() });
    expect(
      await screen.findByRole('heading', { name: 'Privacy Policy', level: 1 }),
    ).toBeInTheDocument();
  });

  it('renders the terms at /terms', async () => {
    renderApp('/terms', { routes: signedOutRoutes() });
    expect(
      await screen.findByRole('heading', { name: 'Terms of Service', level: 1 }),
    ).toBeInTheDocument();
  });

  it('renders the forgot-password screen at /forgot-password', async () => {
    renderApp('/forgot-password', { routes: signedOutRoutes() });
    expect(await screen.findByText('Reset your password')).toBeInTheDocument();
  });

  it('renders the reset-password screen at /reset-password', async () => {
    renderApp('/reset-password', { routes: signedOutRoutes() });
    expect(await screen.findByText('Set new password')).toBeInTheDocument();
  });
});

describe('protected routes', () => {
  it('sends a signed-out visitor from /discover to the login screen', async () => {
    renderApp('/discover', { routes: signedOutRoutes() });
    // Not a flash of discover then a redirect: the session probe has to settle
    // before RequireAuth decides, which is why `booting` exists.
    expect(await screen.findByText('Welcome to Howl 🐺')).toBeInTheDocument();
  });

  it('sends a signed-out visitor from a chat deep link to the login screen', async () => {
    renderApp('/chat/7', { routes: signedOutRoutes() });
    expect(await screen.findByText('Welcome to Howl 🐺')).toBeInTheDocument();
  });

  it('renders discover for a signed-in visitor', async () => {
    renderApp('/discover', { routes: signedInRoutes() });
    expect(await screen.findByText('Looking for')).toBeInTheDocument();
  });

  it('renders matches for a signed-in visitor', async () => {
    renderApp('/matches', { routes: signedInRoutes() });
    expect(await screen.findByText('Your Matches')).toBeInTheDocument();
    // By role: the card shows the name as a heading and the animal as body
    // text, and here they are both "Otter".
    expect(await screen.findByRole('heading', { name: 'Otter', level: 3 })).toBeInTheDocument();
  });

  it('renders the profile for a signed-in visitor', async () => {
    renderApp('/profile', { routes: signedInRoutes() });
    expect(await screen.findByText('Your Profile')).toBeInTheDocument();
  });
});

describe('/chat/:matchId', () => {
  it('opens the conversation from a cold deep link', async () => {
    // The whole point of the route: no click set up any state, so ChatRoute has
    // to resolve the id against the match list and load history itself.
    renderApp('/chat/7', {
      routes: [...signedInRoutes(), messagesRoute()],
    });

    expect(await screen.findByText('hello there')).toBeInTheDocument();
    // The composer is addressed to the other user, which only the chat renders.
    expect(await screen.findByPlaceholderText('Message Otter…')).toBeInTheDocument();
  });

  it('redirects to /matches when the id is not one of your matches', async () => {
    renderApp('/chat/999', {
      routes: [...signedInRoutes(), messagesRoute()],
    });
    expect(await screen.findByText('Your Matches')).toBeInTheDocument();
  });

  it('redirects to /matches for a non-numeric id instead of rendering an empty chat', async () => {
    renderApp('/chat/not-an-id', {
      routes: [...signedInRoutes(), messagesRoute()],
    });
    expect(await screen.findByText('Your Matches')).toBeInTheDocument();
  });

  it('waits for the match list before deciding a deep link is invalid', async () => {
    // The bug this pins: deciding too early sends every refresh of a valid chat
    // URL to /matches, because the list has not arrived yet.
    let releaseMatches;
    const matchesArrived = new Promise((resolve) => { releaseMatches = resolve; });

    renderApp('/chat/7', {
      routes: [
        ...signedInRoutes().filter((r) => r.match !== '/api/users/matches'),
        {
          match: '/api/users/matches',
          handler: async () => {
            await matchesArrived;
            return new Response(JSON.stringify([aMatch()]), {
              status: 200,
              headers: { 'Content-Type': 'application/json' },
            });
          },
        },
        messagesRoute(),
      ],
    });

    expect(await screen.findByText('Opening conversation…')).toBeInTheDocument();
    releaseMatches();
    expect(await screen.findByText('hello there')).toBeInTheDocument();
  });
});

describe('index and unknown routes', () => {
  it('sends / to the login screen when signed out', async () => {
    renderApp('/', { routes: signedOutRoutes() });
    expect(await screen.findByText('Welcome to Howl 🐺')).toBeInTheDocument();
  });

  it('sends / to the profile when signed in', async () => {
    renderApp('/', { routes: signedInRoutes() });
    expect(await screen.findByText('Your Profile')).toBeInTheDocument();
  });

  it('sends an unknown path home rather than rendering a blank page', async () => {
    // A `view` string had no notion of "unknown", so this case did not exist
    // before. Rendering nothing would be the easy regression.
    renderApp('/does-not-exist', { routes: signedOutRoutes() });
    expect(await screen.findByText('Welcome to Howl 🐺')).toBeInTheDocument();
  });
});

describe('navigation', () => {
  it('puts real history entries behind the browser back button', async () => {
    // The regression this guards: with a `view` string, browser Back left the
    // app entirely. Uses jsdom's own session history, not MemoryRouter's.
    const user = userEvent.setup();
    renderAppInBrowser('/profile', { routes: signedInRoutes() });

    await screen.findByText('Your Profile');
    await user.click(screen.getByRole('button', { name: 'Discover' }));
    await screen.findByText('Looking for');

    await user.click(screen.getByRole('button', { name: /Matches/ }));
    await screen.findByText('Your Matches');

    window.history.back();
    await waitFor(() => expect(screen.getByText('Looking for')).toBeInTheDocument());

    window.history.back();
    await waitFor(() => expect(screen.getByText('Your Profile')).toBeInTheDocument());
  });

  it('opens a chat by clicking a match, and ← Matches returns to the list', async () => {
    const user = userEvent.setup();
    renderApp('/matches', {
      routes: [...signedInRoutes(), messagesRoute()],
    });

    await user.click(await screen.findByRole('heading', { name: 'Otter', level: 3 }));
    expect(await screen.findByText('hello there')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '← Matches' }));
    expect(await screen.findByText('Your Matches')).toBeInTheDocument();
  });
});
