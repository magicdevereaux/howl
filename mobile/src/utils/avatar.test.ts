/**
 * Mobile half of the shared-constants coverage (GAPS #29, guarding GAPS #32).
 *
 * The animal map is duplicated byte-for-byte between the two clients — see the
 * header in src/shared/constants.ts for why, and tests/test_packaging.py for the
 * check that keeps the copies identical. What matters here is that the *mobile*
 * consumer resolves against it the same way the web one does, because the two
 * had already drifted: the same user rendered a different animal depending on
 * which client they opened.
 */

import { ANIMAL_EMOJI, FALLBACK_ANIMAL_EMOJI } from '../shared/constants';
import { animalEmoji } from './avatar';

describe('animalEmoji', () => {
  it('maps a known animal', () => {
    expect(animalEmoji('wolf')).toBe(ANIMAL_EMOJI.get('wolf'));
  });

  it('is case-insensitive', () => {
    // users.animal is written by Claude and is not casing-guaranteed.
    expect(animalEmoji('Wolf')).toBe(animalEmoji('wolf'));
    expect(animalEmoji('WOLF')).toBe(animalEmoji('wolf'));
  });

  it('falls back for an animal outside the map', () => {
    // The avatar prompt ends with "etc.", so this is expected, not exceptional.
    expect(animalEmoji('pangolin')).toBe(FALLBACK_ANIMAL_EMOJI);
  });

  it.each([null, undefined, ''])('falls back for %p', (value) => {
    // animal is null while avatar_status is pending or failed.
    expect(animalEmoji(value as unknown as string)).toBe(FALLBACK_ANIMAL_EMOJI);
  });

  it('resolves every key in the map to something renderable', () => {
    for (const key of ANIMAL_EMOJI.keys()) {
      expect(animalEmoji(key)).toBeTruthy();
    }
  });

  it('does not resolve inherited object keys', () => {
    // A Map, not an object literal — otherwise 'toString' returns a function.
    expect(animalEmoji('toString')).toBe(FALLBACK_ANIMAL_EMOJI);
    expect(animalEmoji('constructor')).toBe(FALLBACK_ANIMAL_EMOJI);
  });
});

describe('parity with the web client', () => {
  it('covers every animal the seed script can assign', () => {
    // scripts/seed_demo_users.py runs on every production deploy; a gap here is
    // a missing avatar for real seeded users. These seven were the ones the web
    // copy was missing when the maps drifted.
    const seeded = [
      'wolf', 'fox', 'bear', 'owl', 'deer', 'otter',
      'tiger', 'salmon', 'coyote', 'hummingbird', 'raven', 'lynx', 'elephant',
    ];
    expect(seeded.filter((a) => !ANIMAL_EMOJI.has(a))).toEqual([]);
  });

  it('keeps rabbit, which only the web copy used to have', () => {
    expect(ANIMAL_EMOJI.has('rabbit')).toBe(true);
  });
});
