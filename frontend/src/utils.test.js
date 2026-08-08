import { describe, expect, it, vi } from 'vitest';

import { ANIMAL_EMOJI, FALLBACK_ANIMAL_EMOJI } from './shared/constants';
import { animalEmoji, avatarUrl, fetchApi } from './utils';

/**
 * These are the pure functions every view depends on, and they had zero
 * coverage — GAPS #29: "23 backend test files, and no test script in either
 * package.json."
 *
 * The cases below are chosen because each one is a real bug that shipped or
 * nearly shipped, not because they are easy to write.
 */

describe('animalEmoji', () => {
  it('maps a known animal', () => {
    expect(animalEmoji('wolf')).toBe(ANIMAL_EMOJI.get('wolf'));
  });

  it('is case-insensitive', () => {
    // `users.animal` is written by Claude, which does not guarantee casing.
    expect(animalEmoji('Wolf')).toBe(animalEmoji('wolf'));
    expect(animalEmoji('WOLF')).toBe(animalEmoji('wolf'));
  });

  it('falls back for an animal Claude invented', () => {
    // The avatar prompt ends with "etc.", so the model can legitimately return
    // something outside the map. That must render a placeholder, not undefined.
    expect(animalEmoji('pangolin')).toBe(FALLBACK_ANIMAL_EMOJI);
  });

  it.each([null, undefined, ''])('falls back for %o', (value) => {
    // avatar_status can be pending/failed, in which case animal is null.
    expect(animalEmoji(value)).toBe(FALLBACK_ANIMAL_EMOJI);
  });

  it('never returns undefined for any mapped key', () => {
    for (const key of ANIMAL_EMOJI.keys()) {
      expect(animalEmoji(key)).toBeTruthy();
    }
  });
});

describe('avatarUrl', () => {
  it('returns null when there is no avatar', () => {
    // Distinct from '' — callers branch on null to render the emoji fallback.
    expect(avatarUrl(null)).toBeNull();
    expect(avatarUrl(undefined)).toBeNull();
    expect(avatarUrl('')).toBeNull();
  });

  it('passes an absolute URL through untouched', () => {
    // R2-hosted avatars are absolute; prefixing them would 404.
    const r2 = 'https://cdn.example.com/avatars/abc.png';
    expect(avatarUrl(r2)).toBe(r2);
  });

  it('prefixes a server-relative path', () => {
    // Local-filesystem fallback stores /avatars/... and relies on the proxy.
    expect(avatarUrl('/avatars/abc.png')).toBe('/avatars/abc.png');
  });

  it('treats an http URL as absolute too, not just https', () => {
    const insecure = 'http://localhost:8001/avatars/abc.png';
    expect(avatarUrl(insecure)).toBe(insecure);
  });
});

describe('fetchApi', () => {
  it('always sends credentials', async () => {
    // Cookie auth is cross-origin in production (Vercel -> Railway). Without
    // credentials:'include' the browser silently drops the auth cookie and
    // every request 401s.
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true });

    await fetchApi('/api/profile/me');

    expect(spy).toHaveBeenCalledWith('/api/profile/me', { credentials: 'include' });
  });

  it('overrides a caller that passes the wrong credentials mode', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true });

    await fetchApi('/api/profile/me', { credentials: 'omit', method: 'POST' });

    expect(spy).toHaveBeenCalledWith('/api/profile/me', {
      credentials: 'include',
      method: 'POST',
    });
  });

  it('preserves the caller options it is not responsible for', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true });
    const body = JSON.stringify({ content: 'hi' });

    await fetchApi('/api/matches/1/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
    });

    expect(spy).toHaveBeenCalledWith('/api/matches/1/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      credentials: 'include',
    });
  });
});
