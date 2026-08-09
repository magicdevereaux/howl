// ---------------------------------------------------------------------------
// Shared client constants — DUPLICATED ON PURPOSE.
//
// This file exists twice, byte-for-byte identical:
//
//   frontend/src/shared/constants.js   (Vite / React web client)
//   mobile/src/shared/constants.ts     (Expo / Metro React Native client)
//
// It is data-only, and written so that the same source is simultaneously
// valid JavaScript and valid TypeScript under `strict: true`. That means the
// two copies can be verified mechanically:
//
//   diff frontend/src/shared/constants.js mobile/src/shared/constants.ts
//
// Any edit must be applied to both copies. A single `packages/shared`
// workspace would remove the duplication outright, but Metro does not resolve
// out-of-tree workspace packages without extra metro.config.js + package.json
// wiring, so the duplication is the deliberate cheaper option for now.
// See docs/GAPS.md #32.
//
// Rule for this file: the backend is the authority for anything it enforces.
// Nothing here may encode a server-side rule. Quotas (daily swipe limit,
// monthly regeneration limit) live in app/ and must reach the client over the
// API — they are not constants and do not belong here.
// ---------------------------------------------------------------------------

// animal -> emoji, used as the avatar fallback whenever a user has no
// generated image (avatar_status != ready, or DALL-E was unavailable).
//
// Keys are lowercased `users.animal` values. This set is the 20 animals used
// by scripts/seed_demo_users.py, plus `rabbit`, which the Claude prompt in
// app/tasks/avatar.py names explicitly. That prompt ends with "etc.", so
// Claude can legitimately return an animal that is not listed here; unknown
// animals fall through to FALLBACK_ANIMAL_EMOJI rather than being an error.
//
// A Map rather than an object literal: `.get()` is correctly typed as
// `string | undefined` in the TypeScript copy without a type annotation that
// would be a syntax error in the JavaScript copy.
export const ANIMAL_EMOJI = new Map([
  ['bear', '🐻'],
  ['cat', '🐱'],
  ['coyote', '🐺'],
  ['crow', '🐦‍⬛'],
  ['deer', '🦌'],
  ['dolphin', '🐬'],
  ['eagle', '🦅'],
  ['elephant', '🐘'],
  ['fox', '🦊'],
  ['hawk', '🦅'],
  ['hummingbird', '🐦'],
  ['lion', '🦁'],
  ['lynx', '🐱'],
  ['otter', '🦦'],
  ['owl', '🦉'],
  ['panther', '🐆'],
  ['rabbit', '🐰'],
  ['raven', '🐦‍⬛'],
  ['salmon', '🐟'],
  ['tiger', '🐯'],
  ['wolf', '🐺'],
]);

// Shown for any animal missing from ANIMAL_EMOJI, and when animal is null
// (avatar generation still pending or failed).
export const FALLBACK_ANIMAL_EMOJI = '🐾';

// Backoff before retrying a dropped chat WebSocket. Web used 3000ms and
// mobile 2500ms; unified on the shorter value so the two clients recover from
// a network glitch at the same speed.
export const WS_RECONNECT_DELAY_MS = 2500;

// Fetch the next page of discover profiles once the deck is this short.
// Discover is cursor-paginated (GAPS-ROUND-2 #58, default page 30), so without
// a top-up the deck simply runs out mid-session and the user has to navigate
// away and back. Deliberately well above zero: a swipe should never wait on a
// request, and the request has a whole page of swipes to complete in.
export const DISCOVER_LOW_WATER_MARK = 8;
