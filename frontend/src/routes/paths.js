// ---------------------------------------------------------------------------
// The route table, as data.
//
// Before this file the client had no URLs at all: a single `view` string in
// App.jsx decided what rendered (GAPS #33), so the back button did nothing and
// nothing could be linked to. Two consequences beyond the obvious:
//
//   * the legal pages had no address, which is why the mobile client could not
//     deep-link to the canonical Privacy Policy (GAPS #35). `/privacy` and
//     `/terms` below are that link target — they are a published contract with
//     the mobile app, so do not rename them.
//   * a chat was reachable only by clicking a match, so a notification could
//     never open the conversation it was about. `/chat/:matchId` fixes that.
// ---------------------------------------------------------------------------

export const PATHS = {
  login: '/login',
  register: '/register',
  forgotPassword: '/forgot-password',
  resetPassword: '/reset-password',
  discover: '/discover',
  matches: '/matches',
  chat: '/chat/:matchId',
  profile: '/profile',
  privacy: '/privacy',
  terms: '/terms',
};

export const chatPath = (matchId) => `/chat/${matchId}`;

/**
 * `view` string -> path, for the duration of the migration.
 *
 * The old `view` values are still what the view components pass to `setView`.
 * App.jsx maps them through here onto a real `navigate()` call, so the URL is
 * authoritative while the call sites are converted incrementally.
 */
const VIEW_TO_PATH = {
  login: PATHS.login,
  register: PATHS.register,
  'forgot-password': PATHS.forgotPassword,
  'reset-password': PATHS.resetPassword,
  discover: PATHS.discover,
  matches: PATHS.matches,
  profile: PATHS.profile,
  privacy: PATHS.privacy,
  terms: PATHS.terms,
};

export const pathForView = (view) => VIEW_TO_PATH[view] || PATHS.login;

/**
 * path -> `view` string. The inverse, for components that still branch on
 * `view` (Nav's active-tab highlight, LegalPage's privacy/terms switch).
 */
export function viewForPath(pathname) {
  if (pathname.startsWith('/chat/')) return 'chat';
  const found = Object.entries(VIEW_TO_PATH).find(([, path]) => path === pathname);
  return found ? found[0] : '';
}

/** Routes that require a session. Everything else is reachable signed out. */
export const PROTECTED_PATHS = [PATHS.discover, PATHS.matches, PATHS.profile, PATHS.chat];
