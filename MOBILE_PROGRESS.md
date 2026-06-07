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

### To run
```bash
cd mobile
npm install
npx expo start
```

> **Android emulator:** The default `API_URL` points to `localhost:8001`. Android emulators can't reach the host machine at `localhost` — set `EXPO_PUBLIC_API_URL=http://10.0.2.2:8001` in a `.env.local` file inside `mobile/` before starting.

> **Physical device:** Set `EXPO_PUBLIC_API_URL=http://<your-lan-ip>:8001`.

### Architecture decisions
- **Separate mobile auth endpoints** rather than patching cookie endpoints — keeps web flow unchanged and makes token handling explicit for mobile.
- **SecureStore** over AsyncStorage — encrypted at rest, the right choice for auth tokens.
- **Bearer token on every request** — the `api()` client handles this transparently; individual screens never touch tokens directly.

---

## Session 2 — Planned

- Profile / spirit animal reveal screen
- Discover stack (swipe cards)
- Bottom tab navigator
- Avatar image display
