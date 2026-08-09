import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

import MessageComposer from './MessageComposer';
import MessageList from './MessageList';
import { aMessage, aMessage as msg } from '../test-utils';

/**
 * GAPS #33: "No memoization, so every keystroke in the chat input re-renders
 * the whole tree."
 *
 * These tests measure that claim rather than asserting a `React.memo` call
 * exists. A render counter around MessageList is the only thing that can tell
 * the difference between memoization that works and memoization that is
 * silently defeated by a prop identity changing every render — which is the
 * usual way this regresses.
 */

/** Wraps a component and counts how many times it actually rendered. */
function countRenders(Component) {
  const renders = { count: 0 };
  const Counted = (props) => {
    renders.count += 1;
    return <Component {...props} />;
  };
  return [React.memo(Counted), renders];
}

describe('typing in the composer', () => {
  it('does not re-render the message list', async () => {
    // The measurement that matters. Before the split, the text lived on App, so
    // one character re-rendered App, every route element, ChatView, and every
    // bubble in the conversation.
    const user = userEvent.setup();
    const [CountedList, renders] = countRenders(MessageList);
    const messages = Array.from({ length: 30 }, (_, i) => msg({ id: i + 1, content: `m${i}` }));

    // A parent shaped like ChatView: a stable list beside the composer.
    const onDelete = vi.fn();
    const onReport = vi.fn();
    const onSend = vi.fn(async () => true);

    function Chat() {
      return (
        <>
          <CountedList
            messages={messages}
            otherName="Otter"
            otherId={2}
            onDelete={onDelete}
            onReport={onReport}
          />
          <MessageComposer otherName="Otter" sending={false} sendError="" onSend={onSend} onTyping={vi.fn()} />
        </>
      );
    }

    render(<Chat />);
    const initial = renders.count;

    await user.type(screen.getByPlaceholderText('Message Otter…'), 'hello there');

    expect(screen.getByPlaceholderText('Message Otter…')).toHaveValue('hello there');
    // Eleven characters, zero list re-renders.
    expect(renders.count).toBe(initial);
  });

  it('re-renders the list when the messages actually change', async () => {
    // The other half: memoization that never updates is worse than none.
    const [CountedList, renders] = countRenders(MessageList);
    const props = {
      otherName: 'Otter',
      otherId: 2,
      onDelete: vi.fn(),
      onReport: vi.fn(),
    };

    const { rerender } = render(<CountedList messages={[msg({ id: 1, content: 'one' })]} {...props} />);
    const initial = renders.count;

    rerender(
      <CountedList
        messages={[msg({ id: 1, content: 'one' }), msg({ id: 2, content: 'two' })]}
        {...props}
      />,
    );

    expect(renders.count).toBeGreaterThan(initial);
    expect(screen.getByText('two')).toBeInTheDocument();
  });

  it('does not re-render for an unrelated parent render', () => {
    const [CountedList, renders] = countRenders(MessageList);
    const messages = [msg({ id: 1, content: 'one' })];
    const props = { messages, otherName: 'Otter', otherId: 2, onDelete: vi.fn(), onReport: vi.fn() };

    const { rerender } = render(<CountedList {...props} />);
    const initial = renders.count;

    // Same props, new element — e.g. a typing indicator arriving on ChatView.
    rerender(<CountedList {...props} />);

    expect(renders.count).toBe(initial);
  });
});

describe('MessageComposer', () => {
  it('clears the field only when the send succeeded', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn(async () => true);
    render(<MessageComposer otherName="Otter" sending={false} sendError="" onSend={onSend} onTyping={vi.fn()} />);

    const input = screen.getByPlaceholderText('Message Otter…');
    await user.type(input, 'hi');
    await user.click(screen.getByRole('button', { name: 'Send message' }));

    expect(onSend).toHaveBeenCalledWith('hi');
    expect(input).toHaveValue('');
  });

  it('keeps the text when the send failed', async () => {
    // Losing what someone typed is worse than any error message.
    const user = userEvent.setup();
    const onSend = vi.fn(async () => false);
    render(<MessageComposer otherName="Otter" sending={false} sendError="" onSend={onSend} onTyping={vi.fn()} />);

    const input = screen.getByPlaceholderText('Message Otter…');
    await user.type(input, 'hi');
    await user.keyboard('{Enter}');

    expect(input).toHaveValue('hi');
  });

  it('sends on Enter but not on Shift+Enter', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn(async () => true);
    render(<MessageComposer otherName="Otter" sending={false} sendError="" onSend={onSend} onTyping={vi.fn()} />);

    await user.type(screen.getByPlaceholderText('Message Otter…'), 'hi');
    await user.keyboard('{Shift>}{Enter}{/Shift}');
    expect(onSend).not.toHaveBeenCalled();

    await user.keyboard('{Enter}');
    expect(onSend).toHaveBeenCalledOnce();
  });

  it('refuses to send whitespace', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn(async () => true);
    render(<MessageComposer otherName="Otter" sending={false} sendError="" onSend={onSend} onTyping={vi.fn()} />);

    await user.type(screen.getByPlaceholderText('Message Otter…'), '   ');
    await user.keyboard('{Enter}');

    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled();
  });

  it('trims before sending', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn(async () => true);
    render(<MessageComposer otherName="Otter" sending={false} sendError="" onSend={onSend} onTyping={vi.fn()} />);

    await user.type(screen.getByPlaceholderText('Message Otter…'), '  hi  ');
    await user.keyboard('{Enter}');

    expect(onSend).toHaveBeenCalledWith('hi');
  });

  it('caps input at the length the server accepts', async () => {
    const user = userEvent.setup();
    render(<MessageComposer otherName="Otter" sending={false} sendError="" onSend={vi.fn()} onTyping={vi.fn()} />);

    const input = screen.getByPlaceholderText('Message Otter…');
    await user.click(input);
    await user.paste('x'.repeat(2500));

    expect(input.value).toHaveLength(2000);
  });

  it('debounces the typing event instead of firing per keystroke', async () => {
    // The WS typing frame is unthrottled server-side (chat.py), so the debounce
    // here is the only thing between a fast typist and a frame per character.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const onTyping = vi.fn();
      render(<MessageComposer otherName="Otter" sending={false} sendError="" onSend={vi.fn()} onTyping={onTyping} />);

      await user.type(screen.getByPlaceholderText('Message Otter…'), 'hello');
      vi.advanceTimersByTime(600);

      expect(onTyping).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('offers a retry that resends what is still in the field', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn(async () => false);
    render(
      <MessageComposer
        otherName="Otter"
        sending={false}
        sendError="Message failed to send — please try again."
        onSend={onSend}
        onTyping={vi.fn()}
      />,
    );

    await user.type(screen.getByPlaceholderText('Message Otter…'), 'hi');
    await user.click(screen.getByRole('button', { name: 'Retry' }));

    expect(onSend).toHaveBeenCalledWith('hi');
  });
});

describe('MessageList', () => {
  it('groups by day', () => {
    const today = new Date().toISOString();
    render(
      <MessageList
        messages={[
          aMessage({ id: 1, created_at: '2026-01-05T10:00:00Z', content: 'old' }),
          aMessage({ id: 2, created_at: today, content: 'new' }),
        ]}
        otherName="Otter"
        otherId={2}
        onDelete={vi.fn()}
        onReport={vi.fn()}
      />,
    );

    expect(screen.getByText('Today')).toBeInTheDocument();
    expect(screen.getByText('old')).toBeInTheDocument();
  });

  it('renders a deleted message as a tombstone, not as its content', () => {
    render(
      <MessageList
        messages={[aMessage({ id: 1, content: 'secret', deleted_at: '2026-02-02T11:00:00Z' })]}
        otherName="Otter"
        otherId={2}
        onDelete={vi.fn()}
        onReport={vi.fn()}
      />,
    );

    expect(screen.getByText('🗑 Message deleted')).toBeInTheDocument();
    expect(screen.queryByText('secret')).not.toBeInTheDocument();
  });

  it('offers delete only on your own messages', () => {
    render(
      <MessageList
        messages={[
          aMessage({ id: 1, is_mine: false, content: 'theirs' }),
          aMessage({ id: 2, is_mine: true, content: 'mine' }),
        ]}
        otherName="Otter"
        otherId={2}
        onDelete={vi.fn()}
        onReport={vi.fn()}
      />,
    );

    // One ⋮ menu (mine) and one 🚩 report button (theirs).
    expect(screen.getAllByTitle('Message options')).toHaveLength(1);
    expect(screen.getAllByTitle('Report message')).toHaveLength(1);
  });

  it('keeps messages in id order regardless of arrival order', () => {
    // GAPS-ROUND-2 #67 notes the web client is the correct side here — it sorts
    // by id where mobile appends blindly. This pins that it stays sorted.
    render(
      <MessageList
        messages={[
          aMessage({ id: 1, content: 'first', created_at: '2026-02-02T10:00:00Z' }),
          aMessage({ id: 2, content: 'second', created_at: '2026-02-02T10:01:00Z' }),
          aMessage({ id: 3, content: 'third', created_at: '2026-02-02T10:02:00Z' }),
        ]}
        otherName="Otter"
        otherId={2}
        onDelete={vi.fn()}
        onReport={vi.fn()}
      />,
    );

    const rendered = screen.getAllByText(/first|second|third/).map((el) => el.textContent);
    expect(rendered).toEqual(['first', 'second', 'third']);
  });
});
