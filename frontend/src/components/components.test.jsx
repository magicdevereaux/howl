import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import ForgotPasswordView from './ForgotPasswordView';
import ResetPasswordView from './ResetPasswordView';
import PreferenceFilters from './PreferenceFilters';
import { PATHS } from '../routes/paths';
import {
  aMessage,
  aUser,
  renderApp,
  signedInRoutes,
} from '../test-utils';

/**
 * The behaviour behind the GAPS #29 lint findings. Each of these was a warning
 * that turned out to be describing something real; the tests pin the fix rather
 * than the warning.
 */

describe('PreferenceFilters', () => {
  // Replaces the sync effect whose missing `preferenceFilters` dependency ESLint
  // flagged. The dependency could not be added — the prop was a new object every
  // render, so it would have looped — so the effect is gone and the parent
  // remounts this component by key instead.

  it('seeds its draft from the saved values', () => {
    render(
      <PreferenceFilters
        initial={{ lookingFor: 'women', gender: 'man', sexuality: '', agePrefMin: '25', agePrefMax: '40' }}
        onApply={vi.fn()}
      />,
    );

    expect(screen.getByLabelText('Looking for')).toHaveValue('women');
    expect(screen.getByLabelText('Gender')).toHaveValue('man');
    expect(screen.getByLabelText('Minimum age')).toHaveValue(25);
  });

  it('tolerates a partial or missing initial value', () => {
    // The profile fields are all nullable, so half-empty is the normal case.
    render(<PreferenceFilters initial={{ gender: 'woman' }} onApply={vi.fn()} />);
    expect(screen.getByLabelText('Gender')).toHaveValue('woman');
    expect(screen.getByLabelText('Looking for')).toHaveValue('');
  });

  it('does not save on every keystroke — only on Apply', async () => {
    // The draft is local on purpose: each change would otherwise be a PATCH and
    // a discover refetch.
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(<PreferenceFilters initial={{}} onApply={onApply} />);

    await user.selectOptions(screen.getByLabelText('Gender'), 'woman');
    expect(onApply).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({ gender: 'woman' }));
  });

  it('clears every field and saves the cleared set', async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(
      <PreferenceFilters
        initial={{ lookingFor: 'men', gender: 'woman', sexuality: 'gay', agePrefMin: '20', agePrefMax: '30' }}
        onApply={onApply}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Clear all' }));

    expect(onApply).toHaveBeenCalledWith({
      lookingFor: '', gender: '', sexuality: '', agePrefMin: '', agePrefMax: '',
    });
    expect(screen.getByLabelText('Looking for')).toHaveValue('');
  });

  it('remounts with new saved values when its key changes', () => {
    // This is the mechanism that replaced the effect: a different key is a
    // different component instance, so useState re-seeds.
    const { rerender } = render(
      <PreferenceFilters key="a" initial={{ gender: 'man' }} onApply={vi.fn()} />,
    );
    expect(screen.getByLabelText('Gender')).toHaveValue('man');

    rerender(<PreferenceFilters key="b" initial={{ gender: 'woman' }} onApply={vi.fn()} />);
    expect(screen.getByLabelText('Gender')).toHaveValue('woman');
  });
});

describe('ResetPasswordView without a token', () => {
  // /reset-password has a real address, so the tokenless case is reachable —
  // by typing the URL, by a refresh after the effect stripped the query, or by
  // a refresh after the token was spent. This behaviour was carried over from
  // the PasswordReset component this screen replaced.
  it('explains the link is incomplete instead of offering a form that cannot work', () => {
    render(
      <MemoryRouter>
        <ResetPasswordView token="" onSubmit={vi.fn()} />
      </MemoryRouter>,
    );

    expect(screen.getByText('This reset link is incomplete')).toBeInTheDocument();
    // Submitting would have POSTed an empty token and blamed the user's link
    // for expiring.
    expect(screen.queryByLabelText(/New password/)).not.toBeInTheDocument();
  });

  it('offers a route to a fresh link', () => {
    render(
      <MemoryRouter>
        <ResetPasswordView token="" onSubmit={vi.fn()} />
      </MemoryRouter>,
    );
    // A <Link> now, not a setView callback — the screen it points at has an
    // address of its own.
    expect(screen.getByRole('link', { name: /new link/i })).toHaveAttribute(
      'href', PATHS.forgotPassword,
    );
  });

  it('renders the form when a token is present', () => {
    render(
      <MemoryRouter>
        <ResetPasswordView token="abc123" onSubmit={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.getByText('Choose a new password (8+ characters).')).toBeInTheDocument();
  });

  it('does not submit when the two passwords differ', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <MemoryRouter>
        <ResetPasswordView token="abc123" onSubmit={onSubmit} />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText(/New password/), 'hunter2secure');
    await user.type(screen.getByLabelText(/Confirm/), 'hunter2secXre');
    await user.click(screen.getByRole('button', { name: /reset password/i }));

    // The mismatch is a property of the form, answerable without a request —
    // so it must not cost one.
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

describe('ForgotPasswordView', () => {
  it('reports the same thing whether or not the address is registered', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(null);
    render(
      <MemoryRouter>
        <ForgotPasswordView onSubmit={onSubmit} />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText(/email/i), 'wolf@howl.app');
    await user.click(screen.getByRole('button', { name: /send/i }));

    expect(onSubmit).toHaveBeenCalledWith('wolf@howl.app');
    // The server deliberately cannot distinguish the two cases; the screen
    // must not either.
    await screen.findByText(/if that address has an account/i);
  });
});

describe('blocking from a chat', () => {
  // `handleBlock` was passed to ChatView and never called: the profile modal's
  // "🚫 Block" button opened the Block & Report modal, which requires a reason.
  // The label promised one action and delivered another. Not dead code — a
  // mis-wired control.
  const messagesRoute = { match: '/messages', method: 'GET', body: { messages: [aMessage()], has_more: false } };

  it('blocks without filing a report', async () => {
    const user = userEvent.setup();
    renderApp('/chat/7', {
      routes: [
        ...signedInRoutes(),
        messagesRoute,
        { match: '/api/blocks', method: 'POST', body: {} },
      ],
    });

    await screen.findByText('hello there');
    await user.click(screen.getByTitle('View profile'));
    await user.click(await screen.findByRole('button', { name: '🚫 Block' }));

    // A confirmation, like the unmatch flow and the discover card's inline
    // confirm — blocking is not undoable from here.
    expect(await screen.findByText('Block Otter?')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Block' }));

    const posted = globalThis.fetch.mock.calls.filter(
      ([url, opts]) => String(url).includes('/api/blocks') && opts?.method === 'POST',
    );
    expect(posted).toHaveLength(1);
    // The point of the fix: no report is filed by a button labelled "Block".
    const reports = globalThis.fetch.mock.calls.filter(([url]) => String(url).includes('/api/reports'));
    expect(reports).toHaveLength(0);
  });

  it('leaves the reporting path where it was', async () => {
    // Block & Report is still reachable from the ⋯ menu, and still demands a
    // reason before it will submit.
    const user = userEvent.setup();
    renderApp('/chat/7', { routes: [...signedInRoutes(), messagesRoute] });

    await screen.findByText('hello there');
    await user.click(screen.getByTitle('More options'));
    await user.click(await screen.findByRole('button', { name: '🚫 Block & Report' }));

    expect(await screen.findByText('Block & Report Otter?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Block & Report' })).toBeDisabled();
  });
});

describe('session expiry', () => {
  it('a 401 from a background fetch returns you to the login screen', async () => {
    // Previously this swapped the view but left `user` set, so the profile
    // screen would still render from a session that no longer existed.
    renderApp('/matches', {
      routes: [
        { match: '/api/profile/me', method: 'GET', body: aUser() },
        { match: '/api/avatar/status', body: { avatar_status: 'ready' } },
        { match: '/api/users/matches', status: 401, body: { detail: 'Not authenticated' } },
      ],
    });

    expect(await screen.findByText('Welcome to Howl 🐺')).toBeInTheDocument();
    expect(await screen.findByText('Session expired. Please sign in again.')).toBeInTheDocument();
  });
});
