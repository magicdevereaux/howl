# Howl Mobile — Build Progress

React Native / Expo build of the Howl dating app. Tracks session-by-session progress.

---

## Session 1 — Foundation ✅
Bearer-token mobile auth endpoints, SecureStore storage, authenticated API client with silent refresh, AuthContext, login screen.

## Session 2 — Register + Profile + Avatar ✅
`src/theme.ts`, `src/utils/avatar.ts`, extended AuthContext, register screen, profile screen (avatar hero, spirit animal reveal, edit mode).

## Session 3 — Tabs + Discover + Swipe Gestures ✅
Reanimated + gesture-handler, Tabs navigator, discover screen (swipe gestures, card stack, LIKE/PASS labels, match popup), matches list.

## Session 4 — Chat with WebSocket ✅
WS `?token=` auth on backend, `useMatchWebSocket` hook (reconnect, AppState), full chat screen (inverted FlatList, pagination, real-time, typing indicator, read receipts, keyboard avoiding).

---

## Session 5 — Undo Swipe + Live Unread Badge + Pull-to-Refresh + Block/Report ✅

**Goal:** Polish pass and feature completions from the Session 4 plan.

### Completed

#### New infrastructure
- `src/contexts/UnreadContext.tsx` — minimal context (`totalUnread`, `setTotalUnread`) shared between matches screen and tab layout. Wrapped at root layout level (`app/_layout.tsx`) alongside `AuthProvider`.

#### Discover — undo last swipe
- `app/(app)/discover.tsx` — stores `lastSwiped` (the top user before each swipe). After a successful swipe that didn't produce a match, an **↩ Undo** text link appears below the action buttons.
- Tapping undo calls `DELETE /api/swipes/last`; on success prepends the user back to the top of the stack.
- `lastSwiped` is cleared on: next swipe, successful undo, or match popup.
- A placeholder `View` reserves space when undo is hidden so the buttons don't shift.

#### Matches — live unread badge + pull-to-refresh
- `app/(app)/matches.tsx` — rewrote to use `useFocusEffect` (Expo Router) so matches refetch every time the tab comes into focus (including after returning from chat). This keeps the tab badge current without a persistent background WS.
- `RefreshControl` on `FlatList` for manual pull-to-refresh.
- After each fetch: `setTotalUnread(sum of unread_count)` pushes the count into `UnreadContext`.

#### Tab badge
- `app/(app)/_layout.tsx` — reads `totalUnread` from `UnreadContext`; passes it as `tabBarBadge` on the Matches tab. Badge styled gold on dark (`C.gold` / `#0D0B1A` text).

#### Chat — block & report
- `app/(app)/chat/[matchId].tsx`:
  - Reads `otherUserId` from route params (already passed by matches screen since Session 4).
  - **`⋯` button** in the header right slot opens a bottom-sheet `Modal` with Report / Block / Cancel options.
  - **Report flow:** secondary `Modal` with radio-button reason picker (6 reasons matching web). Submits `POST /api/reports`. On success: success toast, modal dismissed.
  - **Block flow:** calls `POST /api/blocks` directly from the menu; on success navigates back to matches (which will refetch and remove the blocked user's match).
  - **Action feedback toast** appears at the bottom for 3 s after successful report.

### Architecture decisions
- **`useFocusEffect` for badge freshness** — avoids a persistent background WebSocket for the unread count. Every tab focus triggers a silent refetch (~200 ms); the badge is always accurate when the user is looking at matches. True push-driven updates require Expo Notifications (Session 6).
- **`UnreadContext` at root level** — shared between `(app)/_layout.tsx` (reads) and `matches.tsx` (writes). Placing it in the root layout avoids re-mounting it on navigation between app screens.
- **Undo as client-side optimistic revert** — the card is removed from state immediately on swipe (Session 3 design). Undo puts it back on `DELETE /api/swipes/last` success; no re-fetch needed since we saved the full user object in `lastSwiped`.

---

## Session 6 — Push Notifications + App Store Prep ✅

**Goal:** Expo push notifications for new matches/messages, and baseline app.json config for store submission.

### Completed

#### Backend
- `app/models/push_token.py` — new `PushToken` model (`user_id`, `token` unique, `created_at`). Migration `n5h6i7j8k9l0_add_push_tokens`.
- `app/api/push_tokens.py` — `POST /api/push-tokens` (register/upsert, reassigns a shared-device token to whoever is currently logged in) and `DELETE /api/push-tokens` (unregister, e.g. on logout). Both require auth.
- `app/services/push_notifications.py` — `send_push_notifications()` posts to the Expo push API (`exp.host/--/api/v2/push/send`). Fail-open: errors are logged, never raised.
- `app/tasks/notify.py`:
  - `notify_new_message` now also sends a push (`{type: "message", match_id}`) to all of the recipient's registered devices, independent of the `email_notifications` preference (which only gates the email).
  - New `notify_new_match` task sends a push (`{type: "match", match_id}`) to the user who didn't trigger the match.
- Wired `notify_new_match.delay(...)`:
  - `app/api/swipes.py` — on a mutual-like match, notifies the other user.
  - `app/tasks/auto_match.py` — on a demo-user auto-match-back, notifies the real user.
- Tests: `tests/test_push_tokens.py` (register/reassign/unregister), new cases in `tests/test_notify.py` (push on new message, push sent even when email notifications are off, `notify_new_match` payload). Added an autouse `_mock_notify_new_match` fixture in `tests/conftest.py` so match-creating tests don't require Redis.

#### Mobile
- Added `expo-notifications`, `expo-device`, `expo-constants` dependencies.
- `src/notifications/push.ts`:
  - `syncPushToken()` — requests notification permission, fetches the Expo push token (skipped on simulators via `Device.isDevice`), sets up the Android notification channel, and registers the token via `POST /api/push-tokens`.
  - `unregisterPushToken()` — calls `DELETE /api/push-tokens` with the cached token.
- `src/auth/AuthContext.tsx` — calls `syncPushToken()` after a successful initial `/api/auth/me` check and after login; calls `unregisterPushToken()` before clearing tokens on logout.
- `app/_layout.tsx` — registers `Notifications.addNotificationResponseReceivedListener` (warm/background tap) and checks `getLastNotificationResponseAsync()` (cold start tap). Routes `{type: "message", match_id}` → `/(app)/chat/[matchId]`, `{type: "match"}` → `/(app)/matches`.
- `app.json` — app store prep: `ios.bundleIdentifier` / `android.package` set to `app.howl.mobile`, `ios.buildNumber` / `android.versionCode`, dark `userInterfaceStyle` + `backgroundColor`, and the `expo-notifications` config plugin (accent color `#9B59D4`).

### Architecture decisions
- **Push tokens keyed by token, not device id** — `PushToken.token` is globally unique; re-registering on a different account reassigns the row. Simple and handles the shared-device case without extra device-fingerprinting.
- **Push notifications are not gated by `email_notifications`** — that preference is described as an email setting; push uses its own opt-in (the OS permission prompt). A user can decline the OS push permission to opt out entirely.
- **Match notification goes to the "other" user only** — the user who performed the swipe already sees the match popup in the UI immediately, so a push to themselves would be redundant.

### Remaining for app store submission
- **App icon / splash / adaptive icon assets** — no image assets exist yet in `mobile/assets/`. `app.json` does not reference icon/splash paths (Expo's defaults are used); real branded assets need to be created and added (`icon.png`, `splash.png`, `android adaptiveIcon.foregroundImage`, and an `expo-notifications` icon) before a production build.
- **EAS project setup** — `syncPushToken()` reads `Constants.expoConfig?.extra?.eas?.projectId` for push token scoping; run `eas init` to populate this once an Expo account/project exists.
- **iOS push capability** — enabling push notifications in the Apple Developer portal + APNs key/cert configuration (handled by EAS during the build).
- **Privacy policy / app store metadata** — descriptions, screenshots, privacy policy URL (required for both stores given push notifications + user-generated content).
- **Safe area insets**: replace hardcoded `paddingTop: 56` with `useSafeAreaInsets` across all headers
- **Stack → (tabs) navigation restructure** for native push-slide animation into chat
- **Custom fonts via expo-font** (Cinzel, Cormorant Garamond) to match web typography
- **Offline / network error states** across all screens

---

## Session 7 — App Icon, Splash Screen, EAS Build Setup, README ✅

**Goal:** Final pre-submission polish — branded icon/splash assets, EAS build profiles, and a combined web + mobile README. Get the app into a state where it could be submitted to the App Store and Play Store (pending the user's own Expo/Apple/Google accounts).

### Completed

#### App icon, adaptive icon, splash, notification icon
- `mobile/scripts/generate_assets.py` — new Python/Pillow script that programmatically generates all four image assets from the twilight palette (`src/theme.ts`):
  - **Mark:** a geometric, front-facing wolf-head silhouette (two ear triangles + notch + pointed snout) set against a gold moon (with soft glow) and two gold eyes.
  - `assets/icon.png` — 1024×1024, full-bleed vertical gradient (`bgBrand` → `bg`), RGB (no alpha) for iOS.
  - `assets/adaptive-icon.png` — 1024×1024 transparent, mark scaled to ~62% to sit inside Android's adaptive-icon safe zone.
  - `assets/splash-icon.png` — 1024×1024 transparent, mark scaled to ~56% for the splash screen.
  - `assets/notification-icon.png` — 256×256 transparent, flat silhouette only (no eyes/glow, per Android's notification-icon rules — the OS renders status-bar icons from the alpha channel only).
  - Run via `python mobile/scripts/generate_assets.py` to regenerate if the palette or mark design changes.
- Added `expo-splash-screen` (`npx expo install expo-splash-screen`).
- `app.json` updated:
  - `icon: "./assets/icon.png"`
  - `android.adaptiveIcon.foregroundImage: "./assets/adaptive-icon.png"`, `backgroundColor: "#0D0B1A"`
  - `expo-notifications` plugin now points `icon` at `./assets/notification-icon.png`
  - New `expo-splash-screen` plugin entry: `image: "./assets/splash-icon.png"`, `imageWidth: 200`, `resizeMode: "contain"`, `backgroundColor: "#0D0B1A"`
  - Removed the stray top-level `backgroundColor` key (not a valid Expo config field; superseded by the splash-screen plugin's `backgroundColor`)

#### EAS Build setup
- New `mobile/eas.json` with three profiles:
  - **`development`** — dev client, internal distribution, Android `:app:assembleDebug`
  - **`preview`** — internal distribution, Android `.apk` (for quick install/testing without a store)
  - **`production`** — `autoIncrement: true`, Android app bundle (`.aab`) for Play Store submission
  - `submit.production: {}` placeholder so `eas submit --platform ...` works once a production build exists
- `mobile/.gitignore` extended with EAS/credential artifacts: `dist/`, `web-build/`, `*.jks`, `*.p8`, `*.p12`, `*.key`, `*.mobileprovision`, `*.tsbuildinfo`, plus `.expo/` (carried over from Session 6's SDK upgrade).

#### Verification
- `npx tsc --noEmit` — clean, no errors.
- `npx expo-doctor` — 17/17 checks passed.
- `npx expo export --platform android` — succeeded (1429 modules bundled, 43 assets, 4.13 MB Android `.hbc` bundle). Export output was a one-off sanity check and was deleted afterward (now covered by `.gitignore`'s `dist/` entry anyway).
- `eas build` itself **could not be run** in this environment — `npx eas-cli whoami` reports "Not logged in", and `eas build` fails with "An Expo user account is required to proceed." This requires the project owner's own Expo account and is documented as a manual follow-up step (see below).

#### README
- Root `README.md` updated to cover both apps:
  - Intro now mentions the mobile app and links to the new Mobile App section.
  - `## Tech Stack` gained a **Mobile** subsection (Expo SDK 53, RN 0.79, React 19, Expo Router, TypeScript, SecureStore, expo-notifications, Reanimated/Gesture Handler).
  - New **`## Mobile App`** section: mobile feature list, architecture/file-tree overview, "Running Locally (Expo Go)" instructions (including `.env.local` / `EXPO_PUBLIC_API_URL` guidance for LAN device, Android emulator, iOS simulator), "Building with EAS" walkthrough (`eas login` → `eas init` → `eas build` per profile → `eas submit`), and an App Store Submission Checklist.
  - Project structure tree now lists `mobile/` alongside `app/`, `frontend/`, etc.
  - Corrected stale test count (355 → **372**, current `pytest --collect-only` total) in both the project-structure tree and the "Running Tests" section.
  - Roadmap: marked mobile app + push notifications as done, replaced the old "Push notifications" / "Mobile responsive improvements" items with "Mobile app (Expo, iOS + Android) with push notifications" (done) and "App Store / Play Store submission (EAS account setup + builds remain)" (pending).

### Architecture decisions
- **Generated (not hand-drawn) icon assets** — a Python/Pillow script keeps the mark reproducible and tied directly to the theme palette constants, so a future palette change can regenerate all four assets with one command instead of re-exporting from a design tool.
- **Notification icon has no eyes/glow** — Android composites notification icons using only the alpha channel and a single tint color; including the gold eye/glow detail would either disappear or render as solid white blobs, so the notification variant is a simplified flat silhouette.
- **No fabricated production API URL** — `eas.json` does not hardcode a backend URL. The README instead documents setting `EXPO_PUBLIC_API_URL` via EAS environment variables or `.env.production` once a deployed backend URL exists, avoiding a stale/incorrect URL baked into store builds.

### Remaining for app store submission
- **`eas login` + `eas init`** — requires the project owner's Expo account. `eas init` will link the project and populate `extra.eas.projectId` in `app.json` (needed for push notification scoping, per Session 6's `syncPushToken()`).
- **Run the actual EAS builds** — once logged in:
  ```bash
  eas build --platform android --profile preview
  eas build --platform ios --profile preview
  # ... then production profiles for store submission
  ```
- **iOS push capability / APNs key** — configured automatically by EAS during the first iOS build, once an Apple Developer account is linked.
- **Apple/Google developer accounts** — required for `eas submit`.
- **Privacy policy URL + store listing metadata** (descriptions, screenshots) — required by both stores given push notifications and user-generated content.
- **Production `EXPO_PUBLIC_API_URL`** — set once the backend has a stable deployed URL (e.g. Railway).
- Carried over from Session 6 (still open): safe-area-inset cleanup, Stack→(tabs) navigation restructure, custom fonts, offline/network error states.

---

## To run

```bash
cd mobile
npm install
npx expo start
```

> **Android emulator:** Set `EXPO_PUBLIC_API_URL=http://10.0.2.2:8001` in `mobile/.env.local`.
> **Physical device:** Set `EXPO_PUBLIC_API_URL=http://<your-lan-ip>:8001`.

## To build for app stores (EAS)

```bash
cd mobile
npm install -g eas-cli
eas login
eas init        # first time only — links Expo account/project
eas build --platform android --profile preview
eas build --platform ios --profile preview
```

See the README's [Building with EAS](../README.md#mobile-app) section for the full profile breakdown and submission checklist.
