# Gaps & Improvements

A prioritized audit of the current `main`, from a full read of the backend, both clients, the data
layer, and the tooling. Every item has a file reference. Nothing here has been fixed — this is the
worklist.

Items marked **✅ verified** were confirmed by direct code read rather than inference.
Items marked **✅ FIXED** have been resolved — the commit is noted inline.

**Status:** 13 of 37 resolved. Every P0 is closed except **#3** (no email provider — password-reset
tokens go to stdout), which is blocked on choosing a provider. The whole P1 cost cluster (#7–#11) is
done, so the four ways this app could bill unboundedly are all now bounded. Suite: **413 passing**, up
from 15 failing on a clean checkout at the start of the audit.

Note on **#5**: marked MITIGATED rather than FIXED. User text is now JSON-encoded, fenced as untrusted,
and every returned index is range-checked and de-duplicated, so a reply cannot be written into a
conversation outside its batch. A batched call still shows one user's text to a model that is writing
replies for others; full isolation means one call per conversation, at _BATCH_SIZE times the cost.

---

## P0 — Fix before any real user touches this

### 1. ~~`GET /api/profile/{user_id}` is unauthenticated and returns every user's email~~ ✅ FIXED (187c73e)

`app/api/profile.py:132-137` has no `get_current_user` dependency and returns the full `UserOut`, which
includes `email`, `is_premium`, `daily_swipes`, and `swipes_reset_at` (`app/schemas/user.py:35-61`).
Anyone can walk `?user_id=1,2,3…` and harvest the entire user table's email addresses.

The codebase already has the right pattern — `DiscoverUserOut` and `MatchedProfileOut` are deliberately
narrow. Fix: add the auth dependency **and** return a narrow schema.

### 2. ~~`/api/mobile/auth/login` has no rate limiting~~ ✅ FIXED (187c73e)

`app/api/mobile_auth.py:102-111` is a straight credential check. The IP + email brute-force protection
at `app/api/auth.py:136-158` doesn't exist on this path, so the mobile endpoint is an unthrottled
bypass of the web limiter. This is the login endpoint the shipped app actually uses, and it has **zero
tests**.

### 3. Password reset and verification tokens are printed to stdout

`app/services/email.py:24-32, 44-51` — there is no email provider. Every reset token goes to the
Railway log stream, which is a complete account-takeover primitive for anyone with log access. Users
also simply never receive the emails, so the reset flow is non-functional in production.

### 4. ~~All 1000 seeded bots share one committed password~~ ✅ FIXED (187c73e)

`scripts/seed_demo_users.py:208` bcrypts the literal string `"howl-demo-placeholder"`, and the seed
runs on every production deploy with `is_email_verified=True`. Anyone who reads this repo can log in as
`demo1@howl.app`. Generate a random per-deploy secret, or set an unusable hash.

### 5. ~~Prompt injection across users in the bot batch~~ ✅ MITIGATED (949e020)

`app/tasks/bot_response.py:105` interpolates raw user messages into a single prompt covering **10
different conversations** and asks for a JSON array keyed by index. One user's message can steer the
replies sent to *other* users. `:143` bounds `index < len(batch)` but not `index >= 0`, so a negative
index silently targets the wrong conversation. Batch per conversation, or validate the index range and
delimit user content.

### 6. ~~Password reset doesn't revoke sessions~~ ✅ FIXED (949e020)

`app/api/auth.py:245-277` rehashes the password but leaves every `RefreshToken` row live. A user
resetting a password because they were compromised stays compromised for up to 30 days.

---

## P1 — Correctness and cost

### 7. ~~`generate_avatar` is not idempotent under `task_acks_late=True`~~ ✅ FIXED (0787283)

`app/celery_app.py:26` plus zero guarding in `app/tasks/avatar.py:40`. A worker killed after the DALL·E
call but before the commit re-runs everything — a second Claude call and a **second paid image**. Add a
Redis lock or an "already generating" check keyed on `user_id`.

### 8. ~~Unbounded AI spend in the Beat task~~ ✅ FIXED (949e020)

`app/tasks/bot_response.py:166, 243` has no cap on `pending`. With 1000 seeded bots, every 15-minute
tick can issue `len(pending)/10` Claude calls with no ceiling and no circuit breaker. Worse, a failing
batch returns `[]` (`:145-147`) leaving the messages unanswered, so the **same failing batch is
re-selected and re-paid for on every subsequent tick, forever**.

### 9. ~~Premium users have no avatar generation cap at all~~ ✅ FIXED (ca62654)

`app/api/avatar.py:75, 87-88` — the 1-per-30-days limit applies only to non-premium. A premium account
can call a paid DALL·E endpoint in an unbounded loop.

### 10. ~~Orphaned R2 objects on every regeneration~~ ✅ FIXED (1914c93)

`app/api/avatar.py:82` nulls `avatar_url` without calling `delete_avatar()`, and
`app/tasks/avatar.py:115` overwrites it. Every regeneration leaks the previous object into R2 forever.

### 11. ~~Truncated Claude output discards 10 conversations~~ ✅ FIXED (949e020)

`app/tasks/bot_response.py:129` uses `max_tokens=1024` for up to 10 replies; overflow produces invalid
JSON and the whole batch is dropped. `:132` also does `resp.content[0].text` blindly instead of
filtering for `block.type == "text"` the way `app/tasks/avatar.py:73-76` correctly does. No
`stop_reason` check exists anywhere in the codebase.

### 12. ~~Live `ReferenceError` in the web client~~ ✅ FIXED (1df4e92)

`frontend/src/App.jsx:678` calls `setGenerationTime(null)` inside `handleRegenerate`. The state was
deleted in commit `1fbd58d`; only `setGenerationStartTime` exists (`App.jsx:41`). Clicking "Regenerate"
throws before `setAvatarStatus(data)` runs, and with no error boundary anywhere the UI dies. `:376` has
the same call in `handleUpdateBio`, which is dead code.

### 13. Mobile has no network error handling

`mobile/src/api/client.ts:50` — no timeout, no `AbortController`, no try/catch around `fetch`. Every
call site awaits `api()` without a guard, so airplane mode produces an unhandled rejection. No error
boundaries exist in either client.

### 14. Race conditions in swipe handling

`app/api/swipes.py:80-98` check-then-insert on duplicate swipes and on the `daily_swipes` increment;
`:104-118` can create duplicate `Match` rows on simultaneous mutual likes. `undo_last_swipe` orders by
`created_at` rather than `id` (`:166`), which is nondeterministic at SQLite's second resolution.

### 15. ~~Demo detection by email prefix~~ ✅ FIXED (1914c93)

`app/api/swipes.py:135` uses `target.email.startswith("demo")`. Any real user who registers
`demo.something@…` gets bot auto-match behavior. The `is_bot` column already exists — use it.

### 16. Notifications have no retries

`app/tasks/notify.py:26, 105` — neither task binds or retries, and
`app/services/push_notifications.py:49-50` swallows every exception. Expo's per-ticket errors in the
200 response body are never parsed, so `DeviceNotRegistered` tokens are never pruned and dead tokens
accumulate forever.

---

## P2 — Architecture and scale

### 17. Real-time chat is single-replica-only

`app/api/chat.py:36-38` — `ConnectionManager` is an in-process dict, correctly documented as unsafe for
multiple replicas. Any horizontal scaling silently drops delivery for users on other processes. Needs
Redis pub/sub fan-out before scaling past one web process.

### 18. `auth.py` and `mobile_auth.py` are drifting duplicates

Beyond the missing rate limit (#2), `mobile_auth.py:66` hardcodes `timedelta(days=30)` instead of
`settings.refresh_token_expire_days`, and `:85` uses `_TOKEN_EXPIRY_HOURS` (1h, the *password-reset*
constant) for email verification where web uses 24h — mobile verification links expire 24× sooner.
`:19-26` imports four names it never uses. Extract a shared auth service; keep the two routers as thin
token-delivery shells.

### 19. N+1 query storms

- `app/tasks/bot_response.py:168-206` — all bots, then per bot all matches, then per match a
  `db.get(User)`, a last-message query, and a count. At 1000 bots this runs every 15 minutes against
  the same database serving requests.
- `app/api/blocks.py:94-96` — per-block `db.get(User, ...)`, in contrast to the deliberately optimized
  `list_matches`.

### 20. Missing indexes on hot paths

- `swipes.target_user_id` (`app/models/swipe.py:25-27`) — no index, and it's the reciprocal-like lookup
  at `app/api/swipes.py:108, 193` and `app/api/blocks.py:29-30`. Every match check scans.
- `messages.sender_id` (`app/models/message.py:20-22`) — FK, no index, queried at `app/api/chat.py:326`.
- `reports.message_id` (`app/models/report.py:30-32`) — `SET NULL` FK with no index forces a `reports`
  scan on every message delete.
- No composite `(match_id, created_at)` for chat pagination.

### 21. Alembic autogenerate produces wrong output

Four model/migration drifts mean `--autogenerate` proposes destructive DDL:
- `ix_users_is_bot` exists in migration `l3f4g5h6i7j8:20` but the model has no `index=True`
  (`app/models/user.py:72-77`) — autogenerate will **drop** it.
- All four token tables declare `unique=True, index=True` in the model (a unique index) but the
  migrations create a non-unique index *plus* a separately named `UniqueConstraint`. Autogenerate wants
  to rebuild all of them.
- `alembic/env.py:42` sets neither `compare_type=True` nor `compare_server_default=True`, so type and
  default drift is silently invisible.

Also: `downgrade base` → `upgrade head` **fails on Postgres** because migration `246bc2dd05a6` never
drops the `avatar_status` enum type on downgrade, and `m4g5h6i7j8k9:20-22` is an irreversible no-op
downgrade (contradicting ADR-005's "each reversible" claim).

### 22. Timezone handling is ad hoc

Every datetime column is `DateTime(timezone=True)` with a Python-side default and **no
`server_default=func.now()`** (all 9 models). Consequences: raw-SQL and bulk inserts violate NOT NULL;
timestamps carry app-host clock skew rather than DB time; `updated_at`'s Python `onupdate` is skipped by
bulk `.update()`. Under SQLite (the entire test suite) these read back naive, and the
`replace(tzinfo=utc)` normalization is applied in only a couple of places —
`swipes_reset_at`, `regenerations_reset_at`, `avatar_status_updated_at`,
`email_verification_token_expires_at`, `message.read_at` and `deleted_at` have none.

### 23. Missing constraints

- `matches.user1_id < user2_id` is a comment (`app/models/match.py:16`), not a CHECK.
- `age_preference_min <= age_preference_max` is never cross-validated —
  `app/schemas/user.py:123-135` validates each field in isolation.
- `users.age` is nullable, so the 18+ gate is bypassed entirely by simply never setting an age.
- No CHECK tying `avatar_status = 'ready'` to the presence of `avatar_url`/`animal`.
- `push_tokens.token` is globally unique with no `(user_id, token)` pair constraint — a shared device
  re-registering under a second account hits a unique violation instead of reassigning.
- `app/db.py:13-18` — `get_db()` has no `except: db.rollback()`, so a failed request can return a
  dirty session to the pool.

### 24. Report evidence is destroyed by cascade

`app/models/report.py:29` sets `message_id` to `SET NULL` explicitly "so reports survive message
deletion" — but `reporter_id` and `reported_user_id` are `CASCADE` (`:24, 27`). Deleting the reported
user deletes the report. The stated intent and the constraints contradict each other.

### 25. `is_email_verified` is never enforced

Written at `app/api/auth.py:127`, read nowhere. Unverified accounts have full access including
messaging. There's also no resend-verification endpoint. Either enforce it on a dependency or drop the
flow.

### 26. Rate limiting is login-only and defeatable

Registration, forgot-password, reset-password, verify-email, and message send are unthrottled. The IP
bucket trusts the first `X-Forwarded-For` value unconditionally (`app/api/auth.py:136-139`) with no
`TrustedHostMiddleware` or proxy allowlist, so it's spoofable. Chat's send limit uses a DB `COUNT` per
request (`app/api/chat.py:321-332`) instead of the existing Redis limiter. WS `typing` events have no
limit at all (`chat.py:202-203`).

---

## P3 — Engineering hygiene

### 27. ~~No CI, and none of the configured quality tools ever run~~ ✅ FIXED (8ed5e59, 59d42f1)

There is no `.github/`, no pre-commit, no Makefile. **372 tests exist and nothing runs them
automatically.** ruff (`pyproject.toml:36-41`) and mypy `strict=true` (`:43-46`) are both configured and
installed and have **zero invocation points** in the repo.

This is the single highest-leverage fix on this list: a GitHub Actions workflow running
`pytest` + `ruff check` on PRs costs an hour and permanently protects everything above.

### 28. `pyproject.toml` dependencies are stale and would install a broken app

`pyproject.toml:10-24` omits `openai`, `boto3`, `sentry-sdk`, `httpx`, and `pydantic[email]` — all
present in `requirements.txt:11-18` and imported by the app. `pip install -e .` yields an app that
can't start. Pick one source of truth.

### 29. Zero client-side tests

23 backend test files, and **no test script in either `package.json`**. No jest, vitest, RTL, Detox, or
Playwright. No ESLint or Prettier config in either client either.

### 30. Untested backend surfaces

- `app/api/mobile_auth.py` — **zero tests**, and it is the entire auth surface the shipped mobile app
  uses.
- The R2 upload path (`app/services/image_generation.py:53-113`) — the *production* avatar persistence
  path, never exercised. Tests only cover the local-filesystem fallback.
- `app/services/push_notifications.py` and `app/services/rate_limit.py` — never called, only mocked at
  their call sites.
- `scripts/seed_demo_users.py` — 375 lines that run on every production deploy, untested.

### 31. No coverage gate

`[tool.coverage]` has no `fail_under`, and coverage isn't in pytest's `addopts`. `.coverage` and
`htmlcov/` in the repo root are ~2 months stale relative to the code.

### 32. Two clients duplicating drifting logic

Discover, matches, messages, swipes, blocks and reports are each implemented twice. The duplication has
already drifted: the two animal→emoji maps disagree (`mobile/src/utils/avatar.ts:4-8` has
tiger/salmon/coyote/hummingbird/raven/lynx/elephant; `frontend/src/utils.js:13-17` has rabbit instead
and omits those), reconnect delays differ (2500ms vs 3000ms), and `DAILY_SWIPE_LIMIT = 20` is
hardcoded client-side in `frontend/src/App.jsx:815` while the backend is the real authority.

A shared `packages/shared` for the animal map, reason lists, and limit constants would stop the bleed.

### 33. Web client is one 1073-line component

`frontend/src/App.jsx` has ~45 `useState` hooks (`:19-82`), a `view` string standing in for routing
(`:905-1072`), and heavy prop drilling — `ProfileView` takes 24 props (`:1039-1068`), `DiscoverView`
20, `ChatView` 21. No memoization, so every keystroke in the chat input re-renders the tree. No URL
routes means the back button and deep links don't work.

### 34. Mobile accessibility is absent

**Zero** `accessibilityLabel` / `accessibilityRole` / `accessibilityHint` in the entire app. Icon-only
buttons are bare emoji (`discover.tsx:260, 267`, `chat/[matchId].tsx:228, 297`). All font sizes are
fixed numbers, so no dynamic type. The web client has exactly one `aria-label`.

### 35. Mobile is not actually shippable yet

- `extra.eas.projectId` is missing from `app.json`, so `getExpoPushTokenAsync` fails in real builds.
- No `eas.json` profile sets `EXPO_PUBLIC_API_URL`, so a production build points at
  `http://localhost:8001` (`mobile/src/api/client.ts:6`).
- `submit.production` in `eas.json` is an empty object — `eas submit` isn't configured.
- No privacy policy URL in the app config, which both stores require given push + user-generated
  content. The web client has `LegalPage.jsx` but mobile doesn't link it.
- No password reset or email verification on mobile at all — forgotten passwords have no in-app path.
- WS auth puts the access token in the query string (`mobile/src/hooks/useMatchWebSocket.ts:57-58`),
  where it lands in proxy logs, with no refresh-on-expiry path.

### 36. Docs were stale before this pass

Now corrected in `CLAUDE.md` / `RUNBOOK.md`, but `README.md` still says: `DATABASE_URL` on port 5432
with password `howl` (`:107` — actually 5433/`howl_dev`), "18 migrations" (`:253` — there are 21), an
API table omitting every mobile and push-token endpoint (`:141-172`), a project tree missing six files,
a test table missing `test_push_tokens.py`, and run instructions omitting Celery Beat (`:127-136`).
`ALLOWED_ORIGINS` is listed as required at `:470-477` but appears nowhere in `.env.example`. ADR.md says
"five related tables" (there are nine) and "9 migration files" (21). There's no LICENSE file despite
`README:537` claiming MIT.

### 37. Repo litter

- Three empty directories named `c:UsersnathaDocumentsmagicshit…` — created by `mkdir -p` on a Windows
  path inside Git Bash, where backslashes were eaten as escapes. Untracked, empty, safe to delete.
- `env/` — a dead 26 MB venv containing only pip and setuptools. `.venv/` is the real one.
- `.coverage`, `htmlcov/`, `.pytest_cache/`, `__pycache__/` present locally (all gitignored).
- `.claude/settings.local.json` contains a hardcoded PID (`Get-Process -Id 6108,27180`) and a one-shot
  `alembic revision -m "Add User model"` allow-rule.

---

## Suggested order

~~1. **#1, #2, #3, #4** — data exposure and credential problems.~~ done except #3
~~2. **#27** — CI.~~ done
~~3. **#7, #8, #9, #10** — the four ways this app can bill you unboundedly.~~ done

What's left, in order:

1. **#3** — wire a real email provider. The only remaining P0; blocked on picking one. Until then
   password reset is non-functional and reset tokens sit in the log stream.
2. **#13** — mobile has no network error handling; offline throws an unhandled rejection at every
   call site. The most likely crash a real user hits.
3. **#14** — swipe race conditions, and **#16** — notifications never retry.
4. **#18** — consolidate the auth routers before they drift further.
5. **#20** — missing indexes; gates swipe volume. **#17** gates horizontal scaling.
6. **#21** — the Alembic drift, before someone trusts `--autogenerate`.

## Product-shaped ideas

Not defects — directions the spirit-animal concept opens up that the current app doesn't use:

- **The animal is generated but never used as a mechanic.** No filtering by animal, no compatibility
  between animals, no rarity, no "you both got wolves". It's currently just a picture. This is the most
  obvious untapped surface in the product.
- **`personality_traits` is stored and displayed but never matched on.** Discover filters only on age
  and gender; the AI-derived traits are decorative.
- **`avatar_description` is written by Claude and shown nowhere prominent** — it's the most
  characterful text the pipeline produces.
- Regeneration is capped at 1/month for free users, which makes the core delight of the app scarce for
  exactly the users deciding whether to stay.
- Bots are indistinguishable from real users in the UI. That's a product and ethics decision worth
  making deliberately rather than by default.
