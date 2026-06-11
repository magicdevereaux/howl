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

## Session 6 — Planned

- Expo Notifications: push token registration, background new-message alerts
- Safe area insets: replace hardcoded `paddingTop: 56` with `useSafeAreaInsets` across all headers
- Stack → (tabs) navigation restructure for native push-slide animation into chat
- Custom fonts via expo-font (Cinzel, Cormorant Garamond) to match web typography
- Offline / network error states across all screens

---

## To run

```bash
cd mobile
npm install
npx expo start
```

> **Android emulator:** Set `EXPO_PUBLIC_API_URL=http://10.0.2.2:8001` in `mobile/.env.local`.
> **Physical device:** Set `EXPO_PUBLIC_API_URL=http://<your-lan-ip>:8001`.
