/**
 * Covers GAPS #35's placeholder-hostname guard: eas.json's preview/production
 * profiles ship a `.invalid` sentinel for EXPO_PUBLIC_API_URL/WEB_URL until the
 * real Railway/Vercel hosts exist (see eas.json's `//` comments and
 * mobile/CLAUDE.md). A build made without replacing that sentinel must not
 * silently treat it as a real, configured value.
 */

import { isUnreplacedEasPlaceholder } from './config';

describe('isUnreplacedEasPlaceholder', () => {
  it('flags an eas.json-style unreplaced placeholder', () => {
    expect(isUnreplacedEasPlaceholder('https://REPLACE-WITH-RAILWAY-STAGING-HOST.invalid')).toBe(true);
  });

  it('does not flag a plausible real hostname', () => {
    expect(isUnreplacedEasPlaceholder('https://howl-production.up.railway.app')).toBe(false);
    expect(isUnreplacedEasPlaceholder('http://localhost:8001')).toBe(false);
  });

  it('is false rather than throwing on a malformed URL', () => {
    expect(isUnreplacedEasPlaceholder('not a url')).toBe(false);
  });
});

describe('WEB_URL', () => {
  const realEnv = process.env.EXPO_PUBLIC_WEB_URL;

  afterEach(() => {
    process.env.EXPO_PUBLIC_WEB_URL = realEnv;
    jest.resetModules();
  });

  it('uses a configured, non-placeholder value', () => {
    jest.resetModules();
    process.env.EXPO_PUBLIC_WEB_URL = 'https://howl-real-example.vercel.app/';
    // eslint-disable-next-line @typescript-eslint/no-require-imports -- module-load-time constant needs a fresh require per env value
    const { WEB_URL } = require('./config');
    expect(WEB_URL).toBe('https://howl-real-example.vercel.app');
  });

  it('falls back to the production default when the value is an unreplaced placeholder', () => {
    jest.resetModules();
    const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});
    process.env.EXPO_PUBLIC_WEB_URL = 'https://REPLACE-WITH-VERCEL-PRODUCTION-HOST.invalid';
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { WEB_URL } = require('./config');
    expect(WEB_URL).toBe('https://howl.vercel.app');
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('eas.json placeholder'));
    warnSpy.mockRestore();
  });

  it('falls back to the production default when unset', () => {
    jest.resetModules();
    delete process.env.EXPO_PUBLIC_WEB_URL;
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { WEB_URL } = require('./config');
    expect(WEB_URL).toBe('https://howl.vercel.app');
  });
});
