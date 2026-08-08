/**
 * Build-time configuration, all of it from `EXPO_PUBLIC_*` env vars.
 *
 * These are inlined by Metro at build time, so they are baked into the binary —
 * they are not secrets and must never hold one. `eas.json` sets them per build
 * profile; see mobile/CLAUDE.md.
 */

/**
 * Public web client origin, used for outbound links (the full legal text) and
 * for anything that needs to hand a user off to the browser.
 *
 * Unlike `API_URL` in src/api/client.ts, a wrong value here degrades a link
 * rather than breaking every request, so a production default is safe.
 */
export const WEB_URL = (
  process.env.EXPO_PUBLIC_WEB_URL?.trim() || 'https://howl.vercel.app'
).replace(/\/+$/, '');
