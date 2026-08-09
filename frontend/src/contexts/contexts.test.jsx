import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import Nav from '../components/Nav';
import { ReportProvider, useReport } from './ReportContext';
import { SessionProvider, useSession } from './SessionContext';
import { useChat } from './ChatContext';
import { useDiscover } from './DiscoverContext';
import { aMessage, aUser, jsonResponse, mockApi, renderApp, signedInRoutes } from '../test-utils';

/**
 * The contexts that replaced the prop drilling in GAPS #33.
 *
 * The interesting properties are not "the value comes out again" but the two
 * failure modes this refactor can have: a consumer rendered outside its provider
 * (previously a missing prop, which was at least visible at the call site), and
 * a provider whose value causes a render loop.
 */

describe('useSession', () => {
  it('fails loudly outside a provider', () => {
    // Without the guard, a screen mounted in the wrong place fails several
    // frames later on a property access, with nothing pointing at the cause.
    const Consumer = () => <span>{useSession().user?.name}</span>;
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      expect(() => render(<Consumer />)).toThrow(/useSession must be used inside a SessionProvider/);
    } finally {
      spy.mockRestore();
    }
  });

  it('provides the session to a consumer', () => {
    const Consumer = () => <span>{useSession().user.name}</span>;
    render(
      <SessionProvider value={{ user: aUser({ name: 'Wolf' }) }}>
        <Consumer />
      </SessionProvider>,
    );
    expect(screen.getByText('Wolf')).toBeInTheDocument();
  });
});

describe.each([
  ['useChat', useChat, /useChat must be used inside a ChatProvider/],
  ['useDiscover', useDiscover, /useDiscover must be used inside a DiscoverProvider/],
])('%s', (_name, hook, message) => {
  it('fails loudly outside its provider', () => {
    const Consumer = () => {
      hook();
      return null;
    };
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      expect(() => render(<Consumer />)).toThrow(message);
    } finally {
      spy.mockRestore();
    }
  });
});

describe('Nav', () => {
  const renderNav = (session, path = '/discover') =>
    render(
      <MemoryRouter initialEntries={[path]}>
        <SessionProvider value={session}>
          <Nav />
        </SessionProvider>
      </MemoryRouter>,
    );

  it('takes no props at all', () => {
    // It used to take six, bundled as `navProps` and forwarded by all four
    // screens purely to reach it.
    expect(Nav.length).toBe(0);
  });

  it('derives the active tab from the URL, not from a prop', () => {
    // `view` used to be passed in. Now the same component highlights a
    // different tab purely because the address changed.
    renderNav({ totalUnread: 0, logout: vi.fn() }, '/matches');
    expect(screen.getByRole('button', { name: /Matches/ })).toHaveStyle({ fontWeight: '600' });
    expect(screen.getByRole('button', { name: 'Discover' })).toHaveStyle({ fontWeight: '500' });
  });

  it('highlights discover when that is the address', () => {
    renderNav({ totalUnread: 0, logout: vi.fn() }, '/discover');
    expect(screen.getByRole('button', { name: 'Discover' })).toHaveStyle({ fontWeight: '600' });
    expect(screen.getByRole('button', { name: /Matches/ })).toHaveStyle({ fontWeight: '500' });
  });

  it('shows the unread badge from the session', () => {
    renderNav({ totalUnread: 4, logout: vi.fn() });
    expect(screen.getByText('4')).toBeInTheDocument();
  });

  it('caps the badge at 99+', () => {
    renderNav({ totalUnread: 250, logout: vi.fn() });
    expect(screen.getByText('99+')).toBeInTheDocument();
  });

  it('hides the badge at zero rather than showing a 0', () => {
    renderNav({ totalUnread: 0, logout: vi.fn() });
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('signs out through the session', async () => {
    const user = userEvent.setup();
    const logout = vi.fn();
    renderNav({ totalUnread: 0, logout });

    await user.click(screen.getByRole('button', { name: 'Logout' }));
    expect(logout).toHaveBeenCalledOnce();
  });
});

describe('ReportProvider', () => {
  it('renders no dialog until something opens one', () => {
    render(
      <ReportProvider>
        <span>child</span>
      </ReportProvider>,
    );
    expect(screen.getByText('child')).toBeInTheDocument();
    expect(screen.queryByText(/^Report /)).not.toBeInTheDocument();
  });

  it('opens the dialog for the named user and submits a reason', async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.fn(async () => jsonResponse(201, { id: 1 }));
    vi.stubGlobal('fetch', fetchSpy);

    const Opener = () => {
      const { openReport } = useReport();
      return <button onClick={() => openReport(9, 'Otter')}>open</button>;
    };

    render(
      <ReportProvider>
        <Opener />
      </ReportProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'open' }));
    expect(await screen.findByText('Report Otter')).toBeInTheDocument();

    await user.selectOptions(screen.getByRole('combobox'), 'harassment');
    await user.click(screen.getByRole('button', { name: 'Submit Report' }));

    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/reports',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ reported_user_id: 9, reason: 'harassment' }),
      }),
    );
    // Closes on success.
    expect(screen.queryByText('Report Otter')).not.toBeInTheDocument();
  });

  it('includes the message id when a specific message is reported', async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.fn(async () => jsonResponse(201, { id: 1 }));
    vi.stubGlobal('fetch', fetchSpy);

    const Opener = () => {
      const { openReport } = useReport();
      return <button onClick={() => openReport(9, 'Otter', 77)}>open</button>;
    };

    render(
      <ReportProvider>
        <Opener />
      </ReportProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'open' }));
    await user.selectOptions(await screen.findByRole('combobox'), 'spam_scam');
    await user.click(screen.getByRole('button', { name: 'Submit Report' }));

    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/reports',
      expect.objectContaining({
        body: JSON.stringify({ reported_user_id: 9, reason: 'spam_scam', message_id: 77 }),
      }),
    );
  });

  it('keeps the dialog open and shows the server’s reason on failure', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(400, { detail: 'Already reported' })));

    const Opener = () => {
      const { openReport } = useReport();
      return <button onClick={() => openReport(9, 'Otter')}>open</button>;
    };

    render(
      <ReportProvider>
        <Opener />
      </ReportProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'open' }));
    await user.selectOptions(await screen.findByRole('combobox'), 'other');
    await user.click(screen.getByRole('button', { name: 'Submit Report' }));

    expect(await screen.findByText(/Already reported/)).toBeInTheDocument();
    expect(screen.getByText('Report Otter')).toBeInTheDocument();
  });

  it('is a no-op outside a provider rather than a crash', async () => {
    // The default context value. A stray consumer should not take the app down.
    const user = userEvent.setup();
    const Opener = () => {
      const { openReport } = useReport();
      return <button onClick={() => openReport(1, 'x')}>open</button>;
    };
    render(<Opener />);
    await user.click(screen.getByRole('button', { name: 'open' }));
    expect(screen.getByRole('button', { name: 'open' })).toBeInTheDocument();
  });
});

describe('the report dialog is reachable from every screen that offers it', () => {
  // It used to be a `reportModalEl` element rendered by hand in four of the five
  // route branches. Forgetting it in a fifth would have made the button dead.
  it('from the matches grid', async () => {
    const user = userEvent.setup();
    renderApp('/matches', { routes: signedInRoutes() });

    // Wait for the screen to settle before acting: entering /matches triggers a
    // refetch, and clicking mid-flight races the re-render it causes.
    await screen.findByText('Your Matches');
    await user.click(await screen.findByTitle('Report this user'));
    expect(await screen.findByRole('heading', { name: 'Report Otter' })).toBeInTheDocument();
  });

  it('from the discover card', async () => {
    const user = userEvent.setup();
    renderApp('/discover', {
      routes: [
        ...signedInRoutes().filter((r) => r.match !== '/api/users/discover'),
        {
          match: '/api/users/discover',
          body: [{ id: 42, name: 'Badger', animal: 'badger', avatar_url: null, bio: '', personality_traits: [] }],
        },
      ],
    });

    await user.click(await screen.findByRole('button', { name: 'Report this person' }));
    expect(await screen.findByText('Report Badger')).toBeInTheDocument();
  });

  it('from a message in a chat', async () => {
    const user = userEvent.setup();
    renderApp('/chat/7', {
      routes: [
        ...signedInRoutes(),
        { match: '/messages', method: 'GET', body: { messages: [aMessage()], has_more: false } },
      ],
    });

    await screen.findByText('hello there');
    await user.click(screen.getByTitle('Report message'));
    expect(await screen.findByText('Report Otter')).toBeInTheDocument();
  });
});

describe('provider values do not loop', () => {
  it('renders the profile a bounded number of times', async () => {
    // The regression this guards is real: making ProfileView's blocked-users
    // effect depend on `fetchBlocks` looped infinitely until `fetchBlocks`
    // became a useCallback, because a new identity each render re-ran the
    // effect, which set state, which re-rendered. A fetch counter is the
    // cheapest detector — a loop shows up as an unbounded request count.
    mockApi(signedInRoutes());
    renderApp('/profile');

    await screen.findByText('Your Profile');
    const blockCalls = () =>
      globalThis.fetch.mock.calls.filter(([url]) => String(url).includes('/api/blocks')).length;

    const first = blockCalls();
    await new Promise((r) => setTimeout(r, 50));
    expect(blockCalls()).toBe(first);
    expect(first).toBeLessThanOrEqual(2); // StrictMode double-invokes effects
  });
});
