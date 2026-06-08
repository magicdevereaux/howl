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
- `src/api/client.ts` — Authenticated fetch wrapper with silent token refresh on 401.
- `src/auth/AuthContext.tsx` — React context with `login`, `logout`, `user`, `loading`.
- `app/_layout.tsx` — Root layout wrapping all screens in `AuthProvider`.
- `app/index.tsx` — Splash redirect.
- `app/(auth)/login.tsx` — Login screen wired to backend.
- `app/(app)/_layout.tsx` — Protected layout skeleton.

### Architecture decisions
- Separate mobile auth endpoints, SecureStore over AsyncStorage, Bearer token on every request.

---

## Session 2 — Register + Profile + Avatar ✅

**Goal:** Register screen, profile view/edit, spirit animal avatar display from R2.

### Completed
- `src/theme.ts` — Single palette source.
- `src/utils/avatar.ts` — R2/relative URL resolver, emoji map, capitalise helper.
- `src/auth/AuthContext.tsx` — Extended with `updateUser`, `refreshUser`, exported `User` interface.
- `app/(auth)/register.tsx` — Full register flow.
- `app/(app)/profile.tsx` — Profile screen: avatar hero (R2 + emoji fallback, polling), spirit animal reveal, personality traits, read/edit mode, sign out.

### Architecture decisions
- No tabs yet (only one app screen). Draft state for edits. `resolveAvatarUrl` centralised in shared util.

---

## Session 3 — Tabs + Discover + Swipe Gestures ✅

**Goal:** Bottom tab navigation, discover swipe screen with gesture handling.

### Completed

#### Config updates
- `babel.config.js` — added `react-native-reanimated/plugin` (required for Reanimated to work).
- `package.json` — added `react-native-gesture-handler ~2.20.0`, `react-native-reanimated ~3.16.0`, `@expo/vector-icons ^14.0.0`.
- `app/_layout.tsx` — wrapped entire app in `GestureHandlerRootView` (required for gesture-handler).

#### Navigation
- `app/(app)/_layout.tsx` — Stack → **Tabs** (Discover / Matches / Profile). Tab bar styled to match dark twilight palette (`bgNav` background, `accentHover` active tint, gold unread badge). Uses `@expo/vector-icons` Ionicons; active tab shows solid icon, inactive shows outline.
- `index.tsx` and `login.tsx` — redirect target restored to `/(app)/discover`.

#### Screens
- `app/(app)/discover.tsx` — Full swipe screen:
  - Fetches `GET /api/users/discover` on mount; shows loading, empty-state (with Refresh), and card states.
  - **Card stack:** active card rendered in front, next card shown at 96% scale / +12px offset behind it for depth.
  - **Swipe gestures:** `GestureDetector` + `Gesture.Pan()` from gesture-handler. `translateX` / `translateY` via Reanimated `useSharedValue`.
  - **Threshold:** commit at ±100 px; spring the card to ±600 px off-screen, then call `onSwipe` via `runOnJS`.
  - **Snap-back:** releases below threshold spring back to origin with a different spring config.
  - **Visual feedback:** LIKE label (gold, right side) and PASS label (red, left side) interpolate opacity 0→1 as the card crosses the threshold. Card rotates ±18° linearly with drag distance.
  - **Tap buttons:** ✕ (pass) and ❤️ (like) as accessible alternatives to gesture.
  - **Match popup:** `Modal` with gold accent — "It's a Match!", both spirit animal emojis, "Keep Swiping" button. Shown when `POST /api/swipes` returns a match.
  - **Swipe limit:** 429 from API shown as an error banner above the buttons.
- `app/(app)/matches.tsx` — Matches list:
  - Fetches `GET /api/users/matches`, FlatList of match rows.
  - Each row: avatar (R2 or emoji), name, animal name in gold italic, last message preview or matched date.
  - Unread badge (gold) on avatar; left gold border on rows with unread messages.
  - Chat tap → coming in Session 4.

### Architecture decisions
- **`topUserIdShared` (Reanimated shared value):** The pan gesture `.onEnd` runs on the UI thread; it can't read React state directly. Storing the current top user's ID in a `useSharedValue` lets the worklet read it safely and pass it to `runOnJS(onSwipe)`.
- **Ref pattern avoided:** a shared value is cleaner than a ref for data read from a Reanimated worklet.
- **Optimistic advance:** stack shifts immediately on swipe, then API call happens. If the API fails, the error is surfaced but the card doesn't reappear (keeps UX snappy; consistent with web behaviour).
- **No Undo yet:** undo swipe (`DELETE /api/swipes/last`) is a Session 4 feature.

---

## Session 4 — Planned

- Chat screen (WebSocket messaging, message bubbles, send input)
- Tap match row in Matches → open chat
- Undo last swipe button on discover
- Typing indicators in chat
- Push notification setup (Expo Notifications)

---

## To run

```bash
cd mobile
npm install
npx expo start
```

> **Android emulator:** Set `EXPO_PUBLIC_API_URL=http://10.0.2.2:8001` in `mobile/.env.local`.
> **Physical device:** Set `EXPO_PUBLIC_API_URL=http://<your-lan-ip>:8001`.
