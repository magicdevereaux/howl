/**
 * Build-time configuration, all of it from `EXPO_PUBLIC_*` env vars.
 *
 * These are inlined by Metro at build time, so they are baked into the binary —
 * they are not secrets and must never hold one. `eas.json` sets them per build
 * profile; see mobile/CLAUDE.md.
 */

/**
 * True for eas.json's unreplaced Railway/Vercel placeholder hostnames (see
 * mobile/CLAUDE.md and docs/GAPS.md #35 — the real hostnames aren't known
 * yet). Every placeholder deliberately uses the `.invalid` TLD, reserved by
 * RFC 2606 to never resolve, so detecting one is a plain string check
 * instead of a guess about what a "real" hostname looks like. Shared by
 * `WEB_URL` below and by `API_URL` in src/api/client.ts, so neither can
 * silently ship a build that still points at a fill-in-later value.
 */
export function isUnreplacedEasPlaceholder(url: string): boolean {
  try {
    return new URL(url).hostname.endsWith('.invalid');
  } catch {
    return false;
  }
}

/**
 * Public web client origin, used for outbound links (the full legal text) and
 * for anything that needs to hand a user off to the browser.
 *
 * Unlike `API_URL` in src/api/client.ts, a wrong value here degrades a link
 * rather than breaking every request, so a production default is safe.
 */
function resolveWebUrl(): string {
  const configured = process.env.EXPO_PUBLIC_WEB_URL?.trim();
  if (configured) {
    if (!isUnreplacedEasPlaceholder(configured)) return configured;
    // Unconditional, not __DEV__-gated: a placeholder reaching a real build
    // is a standing misconfiguration worth finding in production logs, not
    // just local ones.
    console.warn(
      `[config] EXPO_PUBLIC_WEB_URL is still the eas.json placeholder (${configured}) — ` +
      'replace it with the real Vercel host before shipping this build profile. ' +
      'Falling back to the production default.',
    );
  }
  return 'https://howl.vercel.app';
}

export const WEB_URL = resolveWebUrl().replace(/\/+$/, '');
