import { describe, expect, it } from 'vitest';

import {
  ANIMAL_EMOJI,
  FALLBACK_ANIMAL_EMOJI,
  WS_RECONNECT_DELAY_MS,
} from './constants';

/**
 * This file is duplicated byte-for-byte at mobile/src/shared/constants.ts (see
 * the header comment there for why). `tests/test_packaging.py` enforces the two
 * copies stay identical; these tests cover what the *contents* must guarantee.
 *
 * The reason it matters: the two clients' animal maps had already drifted. The
 * web copy carried `rabbit` and was missing tiger, salmon, coyote, hummingbird,
 * raven, lynx and elephant, so the same user rendered a different creature
 * depending on which client they opened (GAPS #32).
 */

describe('ANIMAL_EMOJI', () => {
  it('covers every animal the seed script can produce', () => {
    // scripts/seed_demo_users.py assigns from this list, and it runs on every
    // production deploy — a gap here is a missing avatar for real seeded users.
    const seeded = [
      'wolf', 'fox', 'bear', 'owl', 'deer', 'otter', 'raven', 'lynx',
      'tiger', 'salmon', 'coyote', 'hummingbird', 'elephant',
    ];
    const missing = seeded.filter((a) => !ANIMAL_EMOJI.has(a));
    expect(missing).toEqual([]);
  });

  it('keeps rabbit, which the Claude prompt names explicitly', () => {
    // app/tasks/avatar.py lists rabbit in the prompt, so it is a likely output.
    expect(ANIMAL_EMOJI.has('rabbit')).toBe(true);
  });

  it('uses only lowercase keys', () => {
    // animalEmoji() lowercases before lookup, so an uppercase key is dead.
    const bad = [...ANIMAL_EMOJI.keys()].filter((k) => k !== k.toLowerCase());
    expect(bad).toEqual([]);
  });

  it('has a non-empty emoji for every key', () => {
    const empty = [...ANIMAL_EMOJI.entries()].filter(([, v]) => !v || !v.trim());
    expect(empty).toEqual([]);
  });

  it('is a Map, so .get() on an unknown key is undefined rather than inherited', () => {
    // A plain object literal would resolve 'constructor' or 'toString' to
    // something truthy and render a function as an emoji.
    expect(ANIMAL_EMOJI).toBeInstanceOf(Map);
    expect(ANIMAL_EMOJI.get('constructor')).toBeUndefined();
    expect(ANIMAL_EMOJI.get('toString')).toBeUndefined();
  });
});

describe('FALLBACK_ANIMAL_EMOJI', () => {
  it('is a non-empty string', () => {
    expect(typeof FALLBACK_ANIMAL_EMOJI).toBe('string');
    expect(FALLBACK_ANIMAL_EMOJI.length).toBeGreaterThan(0);
  });
});

describe('WS_RECONNECT_DELAY_MS', () => {
  it('is one shared value, not 2500 on one client and 3000 on the other', () => {
    expect(typeof WS_RECONNECT_DELAY_MS).toBe('number');
    expect(WS_RECONNECT_DELAY_MS).toBeGreaterThan(0);
  });
});
