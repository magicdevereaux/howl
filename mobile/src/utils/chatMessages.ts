/**
 * Pure logic for the chat screen's message list, extracted so it can be
 * unit-tested without rendering `app/(app)/chat/[matchId].tsx` (see the scope
 * note in jest.config.js — screens aren't rendered here, module contracts
 * are).
 *
 * Backing contract (app/services/pubsub.py, GAPS-ROUND-2 #47/#67): Redis
 * pub/sub is fire-and-forget. An event published while a replica is
 * momentarily disconnected is dropped with no replay — "acceptable because a
 * dropped socket event costs latency until the client refetches, never the
 * message itself." That promise only holds if the client actually refetches
 * and merges safely, and if it never trusts arrival order once there is more
 * than one publisher.
 */

import type { WsMessage, WsStatus } from '../hooks/useMatchWebSocket';

/**
 * Merge freshly-fetched or newly-arrived messages into the existing list.
 *
 * Two failure modes this exists to prevent:
 *
 * - **Wiping the conversation on refetch (#47).** `GET .../messages` with no
 *   `before_id` returns the latest page. If the caller dedupes against
 *   already-seen ids before calling this, a *second* refetch (e.g. on
 *   reconnect) can see zero new messages — `incoming` is empty — and a naive
 *   `setMessages(incoming)` would blank the whole screen. This function
 *   always merges into `prev`, so an empty `incoming` is a safe no-op.
 * - **Trusting arrival order (#67).** Redis pub/sub preserves order per
 *   publisher, but two concurrent `background_tasks.add_task(manager.broadcast, ...)`
 *   calls — or a second publisher entirely, like a Celery worker delivering
 *   bot replies — have no ordering guarantee relative to each other. Always
 *   sort by id, the way the web client's `Map`-keyed rebuild does.
 *
 * An incoming entry wins over an existing one with the same id, so edits,
 * soft-deletes and read-receipt patches (all of which arrive as an update to
 * an id already in the list) still take effect.
 */
export function mergeMessages(prev: WsMessage[], incoming: WsMessage[]): WsMessage[] {
  if (incoming.length === 0) return prev;
  const byId = new Map<number, WsMessage>();
  for (const m of prev) byId.set(m.id, m);
  for (const m of incoming) byId.set(m.id, m);
  return Array.from(byId.values()).sort((a, b) => a.id - b.id);
}

/**
 * True on exactly the transition that means "we may have missed events" —
 * settling into `open` from `connecting` or `reconnecting`. This covers both
 * a normal drop-and-retry and the mobile hook's deliberate background/
 * foreground close/reopen cycle, which otherwise manufactures a silent gap on
 * every app switch.
 */
export function isReconnectEdge(prevStatus: WsStatus, nextStatus: WsStatus): boolean {
  return nextStatus === 'open' && (prevStatus === 'connecting' || prevStatus === 'reconnecting');
}

/**
 * Apply a `messages_read` event: patch `read_at` onto the caller's own
 * messages up to the reader's high-water mark, so the sender's ✓ becomes ✓✓
 * without waiting for a refetch (GAPS-ROUND-2 #49). Messages that aren't the
 * caller's own, are already marked read, or are past the mark are left
 * untouched — and if nothing changes, the original array is returned so
 * callers can skip a re-render.
 */
export function applyReadReceipt(
  messages: WsMessage[],
  upToMessageId: number,
  readAt: string = new Date().toISOString(),
): WsMessage[] {
  if (!Number.isFinite(upToMessageId)) return messages;
  let changed = false;
  const next = messages.map((m) => {
    if (m.is_mine && m.id <= upToMessageId && !m.read_at) {
      changed = true;
      return { ...m, read_at: readAt };
    }
    return m;
  });
  return changed ? next : messages;
}
