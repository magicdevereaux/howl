import { describe, expect, it } from 'vitest';

import { PATHS, chatPath, pathForView, viewForPath } from './paths';

describe('paths', () => {
  it('round-trips every view through its path', () => {
    // The `setView` shim maps old view strings onto navigate(); Nav maps the
    // path back to decide which tab is active. If the two disagree, the app
    // navigates correctly but highlights the wrong tab.
    for (const view of [
      'login',
      'register',
      'forgot-password',
      'reset-password',
      'discover',
      'matches',
      'profile',
      'privacy',
      'terms',
    ]) {
      expect(viewForPath(pathForView(view))).toBe(view);
    }
  });

  it('recognises a chat path regardless of the match id', () => {
    expect(viewForPath('/chat/7')).toBe('chat');
    expect(viewForPath('/chat/12345')).toBe('chat');
  });

  it('builds a chat path from a match id', () => {
    expect(chatPath(7)).toBe('/chat/7');
  });

  it('returns no view for an unknown path rather than guessing', () => {
    // Nav highlights nothing on an unrecognised path. Returning 'login' here
    // would make the login tab look active on a 404.
    expect(viewForPath('/nope')).toBe('');
  });

  it('falls back to login for an unknown view', () => {
    expect(pathForView('not-a-view')).toBe(PATHS.login);
  });

  it('pins the two paths the mobile client deep-links to', () => {
    // mobile/src/... links to `${WEB_URL}/privacy` and `${WEB_URL}/terms`
    // (GAPS #35). Renaming either silently breaks the mobile legal screen,
    // which both app stores require to work.
    expect(PATHS.privacy).toBe('/privacy');
    expect(PATHS.terms).toBe('/terms');
  });
});
