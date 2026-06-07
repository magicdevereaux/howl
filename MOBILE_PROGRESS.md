# Howl Mobile — Build Progress

React Native / Expo build of the Howl dating app. Tracks session-by-session progress.

---

## Session 1 — Foundation ✅

**Goal:** Scaffold the project, wire auth, get a login screen connecting to the backend.

### Completed

#### Backend changes
- `app/dependencies.py` — `get_current_user` now accepts `Authorization: Bearer <token>` header as a fallback when no cookie is present. Web behaviour unchanged.
- `app/api/mobile_auth.py` — New mobile-specific auth endpoints that return tokens in the response body (not cookies):
  - `POST /api/mobile/auth/login` → `{ user, access_token, refresh_token }`
  - `POST /api/mobile/auth/register` → `{ user, access_token, refresh_token }`
  - `POST /api/mobile/auth/refresh` → `{ user, access_token }` (sends `{ refresh_token }` in body)
  - `POST /api/mobile/auth/logout` → revokes refresh token
- `app/main.py` — mobile auth router registered.

#### Mobile project (`mobile/`)
- Expo SDK 53 + Expo Router 4 scaffolded with TypeScript.
- `src/auth/storage.ts` — SecureStore wrappers for `access_token` / `refresh_token`.
- `src/api/client.ts` — Authenticated fetch wrapper:
  - Attaches `Authorization: Bearer` on every request.
  - On 401: attempts one silent token refresh, retries, then force-logs out.
  - Exposes `setUnauthenticatedHandler` so AuthContext can redirect on expiry.
- `src/auth/AuthContext.tsx` — React context with `login`, `logout`, `user`, `loading`. On mount, checks SecureStore for an existing token and fetches `/api/auth/me` to restore session.
- `app/_layout.tsx` — Root layout wrapping all screens in `AuthProvider`.
- `app/index.tsx` — Splash redirect: authenticated → `/(app)/discover`, guest → `/(auth)/login`.
- `app/(auth)/_layout.tsx` — Auth stack layout.
- `app/(auth)/login.tsx` — Login screen with email/password inputs, error display, wired to `AuthContext.login`.
- `app/(app)/_layout.tsx` — Protected layout skeleton; redirects to login if no session.

### Architecture decisions
- **Separate mobile auth endpoints** rather than patching cookie endpoints — keeps web flow unchanged and makes token handling explicit for mobile.
- **SecureStore** over AsyncStorage — encrypted at rest, the right choice for auth tokens.
- **Bearer token on every request** — the `api()` client handles this transparently; individual screens never touch tokens directly.

---

## Session 2 — Register + Profile + Avatar ✅

**Goal:** Register screen, profile view/edit, spirit animal avatar display from R2.

### Completed

#### Shared infrastructure
- `src/theme.ts` — Single source of truth for all palette constants; imported by every screen instead of duplicating hex values.
- `src/utils/avatar.ts` — `resolveAvatarUrl()` handles both full R2 `https://` URLs and server-relative paths; `animalEmoji()` maps animal names to emoji; `capitalise()` helper.
- `src/auth/AuthContext.tsx` — Extended with `updateUser(user)` (direct state update after profile save) and `refreshUser()` (re-fetches `/api/auth/me`). `User` interface exported for use across screens.

#### Screens
- `app/(auth)/register.tsx` — Full register screen: email + password + confirm, client-side validation (length ≥ 8, passwords match), calls `POST /api/mobile/auth/register`, saves tokens, redirects to profile.
- `app/(app)/profile.tsx` — Profile screen with:
  - **Avatar hero section:** circular `Image` from R2 URL with emoji fallback on error; polls `GET /api/avatar/status` every 3 s while status is `pending`/`generating`; stops polling when `ready` or `failed`.
  - **Spirit animal reveal:** "Your spirit animal" label + animal name in gold italic (matching web design); personality trait pills; avatar description text.
  - **Profile card:** read-only view (name, age, location, bio) with Edit button.
  - **Edit mode:** draft state pattern, PATCH `/api/profile/me`, calls `updateUser()` on success, triggers avatar status refetch in case bio change queued a regen.
  - **Sign out** button.

#### Navigation updates
- `index.tsx` and `login.tsx` redirect target changed from `/(app)/discover` (not yet built) to `/(app)/profile`.

### Architecture decisions
- **No bottom tabs yet** — only one app screen exists; tabs will be introduced in Session 3 when discover is added.
- **Avatar polling in the screen** — `useEffect` + `setInterval` pattern, cleaned up on unmount. The profile screen is the natural owner of this state for now; can be lifted to a context in a later session if needed.
- **Draft state for edits** — mirrors the web approach: changes are local until Save, Cancel resets without an API call.
- **`resolveAvatarUrl` in a shared util** — both the profile screen and future discover/chat screens need this logic; centralised from day one.

---

## Session 3 — Planned

- Bottom tab navigator (Profile + Discover tabs)
- Discover screen with swipe stack (Like / Pass)
- Swipe gesture handling (react-native-gesture-handler / Reanimated)
- Match popup on mutual like
- Custom fonts (Cinzel, Cormorant Garamond via expo-font) to match web typography

---

## To run

```bash
cd mobile
npm install
npx expo start
```

> **Android emulator:** Set `EXPO_PUBLIC_API_URL=http://10.0.2.2:8001` in `mobile/.env.local`.
> **Physical device:** Set `EXPO_PUBLIC_API_URL=http://<your-lan-ip>:8001`.
