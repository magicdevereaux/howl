/**
 * GAPS-ROUND-2 #47 / #67 / #49.
 *
 * #47's trap is the reason this file exists: a naive "does it refetch on
 * reconnect?" test can pass while the reducer it exercises still blanks the
 * screen, because the interesting failure only shows up on the *second*
 * refetch once every message is already known. The tests below exercise
 * exactly that sequence.
 */

import { applyReadReceipt, isReconnectEdge, mergeMessages } from './chatMessages';
import type { WsMessage } from '../hooks/useMatchWebSocket';

function msg(overrides: Partial<WsMessage> & { id: number }): WsMessage {
  return {
    id: overrides.id,
    sender_id: overrides.sender_id ?? 1,
    content: overrides.content ?? `message ${overrides.id}`,
    created_at: overrides.created_at ?? '2026-08-09T00:00:00Z',
    read_at: overrides.read_at ?? null,
    deleted_at: overrides.deleted_at ?? null,
    is_mine: overrides.is_mine ?? false,
  };
}

describe('mergeMessages', () => {
  it('appends genuinely new messages', () => {
    const prev = [msg({ id: 1 }), msg({ id: 2 })];
    const result = mergeMessages(prev, [msg({ id: 3 })]);
    expect(result.map((m) => m.id)).toEqual([1, 2, 3]);
  });

  it('THE TRAP: a refetch that finds nothing new must not wipe the conversation', () => {
    // This is the exact shape of a reconnect refetch: the caller already has
    // messages on screen, and the server's "latest page" contains nothing
    // the caller hasn't already applied (e.g. everything already arrived
    // over the socket before the drop). A naive `setMessages(incoming)`
    // reducer would blank the screen here.
    const prev = [msg({ id: 1 }), msg({ id: 2 }), msg({ id: 3 })];
    const result = mergeMessages(prev, []);
    expect(result).toBe(prev); // same reference: no-op, not a wipe disguised as equal content
    expect(result.length).toBe(3);
  });

  it('merges a partial refetch (some already known, some new) without duplicating', () => {
    const prev = [msg({ id: 1 }), msg({ id: 2 })];
    // Server's latest page overlaps with what we already have, plus one new one.
    const result = mergeMessages(prev, [msg({ id: 2 }), msg({ id: 3 })]);
    expect(result.map((m) => m.id)).toEqual([1, 2, 3]);
  });

  it('sorts by id regardless of arrival order (#67)', () => {
    // Two independent publishers (e.g. a REST broadcast and a Celery worker
    // publish) can race; the reducer must not trust arrival order.
    const prev = [msg({ id: 1 })];
    const result = mergeMessages(prev, [msg({ id: 5 }), msg({ id: 3 })]);
    expect(result.map((m) => m.id)).toEqual([1, 3, 5]);
  });

  it('an incoming entry with an id already present overwrites (edits/deletes/read receipts)', () => {
    const prev = [msg({ id: 1, content: 'original' })];
    const result = mergeMessages(prev, [msg({ id: 1, content: null, deleted_at: '2026-08-09T00:01:00Z' })]);
    expect(result).toHaveLength(1);
    expect(result[0].deleted_at).toBe('2026-08-09T00:01:00Z');
  });
});

describe('isReconnectEdge', () => {
  it('is true settling into open from reconnecting', () => {
    expect(isReconnectEdge('reconnecting', 'open')).toBe(true);
  });

  it('is true settling into open from connecting (covers the background/foreground cycle)', () => {
    expect(isReconnectEdge('connecting', 'open')).toBe(true);
  });

  it('is false for the steady state (open to open)', () => {
    expect(isReconnectEdge('open', 'open')).toBe(false);
  });

  it('is false when leaving open (that is a drop, not a recovery)', () => {
    expect(isReconnectEdge('open', 'reconnecting')).toBe(false);
  });

  it('is false for a terminal close', () => {
    expect(isReconnectEdge('reconnecting', 'closed')).toBe(false);
  });
});

describe('applyReadReceipt', () => {
  it('marks own messages at or below the high-water mark as read', () => {
    const prev = [
      msg({ id: 1, is_mine: true }),
      msg({ id: 2, is_mine: true }),
      msg({ id: 3, is_mine: true }),
    ];
    const result = applyReadReceipt(prev, 2, '2026-08-09T01:00:00Z');
    expect(result[0].read_at).toBe('2026-08-09T01:00:00Z');
    expect(result[1].read_at).toBe('2026-08-09T01:00:00Z');
    expect(result[2].read_at).toBeNull();
  });

  it('never touches messages sent by the other party', () => {
    const prev = [msg({ id: 1, is_mine: false })];
    const result = applyReadReceipt(prev, 10, '2026-08-09T01:00:00Z');
    expect(result[0].read_at).toBeNull();
  });

  it('is a no-op (same reference) when nothing changes', () => {
    const prev = [msg({ id: 1, is_mine: true, read_at: '2026-08-09T00:30:00Z' })];
    const result = applyReadReceipt(prev, 5, '2026-08-09T01:00:00Z');
    expect(result).toBe(prev);
  });

  it('ignores a malformed high-water mark rather than throwing', () => {
    const prev = [msg({ id: 1, is_mine: true })];
    expect(() => applyReadReceipt(prev, Number.NaN)).not.toThrow();
    expect(applyReadReceipt(prev, Number.NaN)).toBe(prev);
  });
});
