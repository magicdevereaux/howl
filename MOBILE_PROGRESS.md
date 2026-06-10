# Howl Mobile — Build Progress

React Native / Expo build of the Howl dating app. Tracks session-by-session progress.

---

## Session 1 — Foundation ✅

**Goal:** Scaffold the project, wire auth, get a login screen connecting to the backend.

### Completed
- Bearer-token mobile auth endpoints, SecureStore storage, authenticated API client with silent refresh, AuthContext, login screen.

### Architecture decisions
- Separate mobile auth endpoints, SecureStore over AsyncStorage, Bearer token on every request.

---

## Session 2 — Register + Profile + Avatar ✅

**Goal:** Register screen, profile view/edit, spirit animal avatar display from R2.

### Completed
- `src/theme.ts` — palette constants. `src/utils/avatar.ts` — URL resolver + emoji map.
- `src/auth/AuthContext.tsx` — extended with `updateUser`, `refreshUser`.
- Register screen, profile screen (avatar hero with R2/emoji, spirit animal reveal, edit mode).

---

## Session 3 — Tabs + Discover + Swipe Gestures ✅

**Goal:** Bottom tab navigation, discover swipe screen with gesture handling.

### Completed
- Reanimated + gesture-handler wired; GestureHandlerRootView in root layout.
- Tabs navigator (Discover / Matches / Profile) with twilight tab bar.
- Discover screen: swipe gestures, card stack depth, LIKE/PASS labels, match popup, swipe limit handling.
- Matches screen: FlatList with avatars, gold unread badges, last message previews.

---

## Session 4 — Chat with WebSocket ✅

**Goal:** Chat screen with real-time WebSocket messaging.

### Completed

#### Backend change
- `app/api/chat.py` — WebSocket handler now accepts `?token=<JWT>` query param alongside the httpOnly cookie. Mobile clients connect with their Bearer token this way; web clients continue to use the cookie unchanged. All 47 chat tests pass.

#### Mobile
- `src/hooks/useMatchWebSocket.ts` — reusable WebSocket hook:
  - Connects to `ws(s)://host/api/matches/{id}/ws?token=<token>`.
  - Reconnects after 2.5 s on unexpected close.
  - Closes on app background (saves battery); reconnects on foreground via `AppState`.
  - `onEventRef` pattern — event callback is always current without restarting the socket.
  - Exposes `sendTyping()` for typing indicator events.
- `app/(app)/chat/[matchId].tsx` — full chat screen:
  - **Message history:** `GET /api/matches/{id}/messages` on mount (oldest-first); displayed with `inverted` FlatList (newest at bottom).
  - **Pagination:** `onEndReached` on the inverted list triggers `before_id` cursor load for older messages; dedup via `seenIds` Set prevents REST + WS duplicates.
  - **Real-time:** WS `new_message` appends to list; `message_deleted` updates in-place.
  - **Typing indicator:** WS `typing` event shows `"{name} is typing…"` for 3 s; auto-hides.
  - **Sending:** `POST /api/matches/{id}/messages`; also adds directly in case WS is momentarily disconnected; input restored on error.
  - **Keyboard:** `KeyboardAvoidingView` with `padding` (iOS) / `height` (Android); multiline input with 120 px max height.
  - **Bubbles:** accent-purple for sent, subtle dark for received; read receipts ✓ / ✓✓; soft-deleted placeholder.
  - **Header:** back button → Matches, name, animal name in gold italic.
- `app/(app)/_layout.tsx` — added `chat/[matchId]` as a hidden Tabs.Screen (`href: null`, `tabBarStyle: { display: 'none' }`) so tab bar disappears in chat.
- `app/(app)/matches.tsx` — match rows now `Pressable`, navigate to `/(app)/chat/[matchId]` passing name, animal, otherUserId as params.

### Architecture decisions
- **`?token=` on WebSocket** — the standard approach for mobile WS auth where cookies aren't available. The query param is short-lived (30 min access token); acceptable for a WebSocket connection that is established and then kept alive.
- **`onEventRef` pattern** — avoids restarting the WebSocket on every render by keeping the callback in a ref. The hook's `connect` function only depends on `matchId`, so the socket is stable for the lifetime of the chat screen.
- **Dedup via `seenIds` Set** — messages can arrive via both REST (initial load) and WS (new_message event). Deduplication prevents double-rendering without requiring complex state merging.
- **Optimistic send with fallback** — message is cleared from input immediately; if the POST fails the input is restored and an error is shown. WS echo + direct append means the message appears even if the WS hasn't delivered it yet.
- **Tab bar hidden in chat** — `tabBarStyle: { display: 'none' }` on the Tabs.Screen hides the tab bar in the chat screen. If push-navigation feel is needed (slide from right), restructure to Stack → (tabs) in Session 5.

---

## Session 5 — Planned

- Undo last swipe on the discover screen
- Unread badge count on the Matches tab (live, updated by WS events)
- Stack → (tabs) navigation restructure for proper push animation into chat
- Pull-to-refresh on the matches list
- Block / Report from within chat (long-press or header menu)

---

## To run

```bash
cd mobile
npm install
npx expo start
```

> **Android emulator:** Set `EXPO_PUBLIC_API_URL=http://10.0.2.2:8001` in `mobile/.env.local`.
> **Physical device:** Set `EXPO_PUBLIC_API_URL=http://<your-lan-ip>:8001`.
