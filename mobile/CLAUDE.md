# CLAUDE.md — mobile

Expo SDK 53 / React Native 0.79 / React 19 / expo-router 5 / TypeScript strict. No state library, no
test runner, no linter.

## Commands

```bash
npm install --legacy-peer-deps    # plain `npm install` fails on peer deps
npx expo start
EXPO_PUBLIC_API_URL=http://192.168.x.x:8001 npx expo start   # device testing needs a LAN IP
npx tsc --noEmit                  # the only check available
```

## Routes

```
app/_layout.tsx          GestureHandlerRootView > UnreadProvider > AuthProvider; push-tap routing
app/index.tsx            redirect: user ? /(app)/discover : /(auth)/login
app/(auth)/login.tsx     ⚠ re-declares the palette locally instead of importing src/theme.ts
app/(auth)/register.tsx  bypasses AuthContext.login and calls saveTokens directly
app/(app)/_layout.tsx    Tabs + auth guard
app/(app)/discover.tsx   Reanimated swipe deck, undo, match modal
app/(app)/matches.tsx    FlatList, unread badges, pull-to-refresh
app/(app)/profile.tsx    avatar hero, 3s poll while pending, edit form
app/(app)/chat/[matchId].tsx   inverted list, cursor pagination, WS + REST dedup via seenIdsRef
```

## Conventions

- **Auth is bearer tokens in SecureStore**, keys `howl_access_token` / `howl_refresh_token`
  (`src/auth/storage.ts`). The web client uses httpOnly cookies instead — the backend supports both.
- Mobile talks to `/api/mobile/auth/*`, **not** `/api/auth/*`, for register/login/refresh/logout.
  Everything else (`/api/users`, `/api/swipes`, `/api/matches`, `/api/profile`, `/api/blocks`) is shared.
- `api()` in `src/api/client.ts` returns a discriminated union, never throws for HTTP errors. It
  auto-refreshes once on 401, then clears tokens and fires `_onUnauthenticated`.
- Styling is per-screen `StyleSheet.create` with hand-written numbers. Only `colors` is shared
  (`src/theme.ts`). There is no spacing or typography scale.

## Known gaps

- `api()` has **no timeout and no try/catch around `fetch`** — offline throws an unhandled rejection at
  every call site (`src/api/client.ts:50`). There are no error boundaries anywhere.
- `extra.eas.projectId` is missing from `app.json`, so `getExpoPushTokenAsync` fails in real builds.
  Run `eas init`.
- No profile in `eas.json` sets `EXPO_PUBLIC_API_URL`, so a production build points at
  `http://localhost:8001` (`src/api/client.ts:6`).
- WS auth passes the access token in the **query string** (`src/hooks/useMatchWebSocket.ts:57-58`) —
  it lands in proxy access logs, and there's no refresh path when it expires, just a silent 2.5s
  reconnect loop.
- **Zero accessibility attributes** in the entire app; icon buttons are bare emoji.
- No password reset or email verification — mobile users who forget their password have no in-app
  recovery path.
- No caching: every screen refetches on focus.

See [../docs/GAPS.md](../docs/GAPS.md) for the prioritized list.
