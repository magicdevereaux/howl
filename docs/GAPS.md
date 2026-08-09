# Gaps & Improvements

A prioritized audit of `main`, from a full read of the backend, both clients, the data layer, and the
tooling. Every item has a file reference. This started as a pure worklist; most of it is now closed, and
each entry records how.

- **✅ FIXED** — resolved, commit noted inline.
- **🟡 PARTLY / MOSTLY / HALF** — the substance is done but something specific is deliberately left.
  Every one says what and why, and none of them is left because it was hard.
- No marker — still open. There are two: **#3** and **#33**.

> **A second audit exists: [GAPS-ROUND-2.md](GAPS-ROUND-2.md), findings #38–#67.** It was run on
> 2026-08-08 against `c56f9f1` and deliberately does not repeat anything below. It contains **two new
> P0s** — the first since #3 — and flags **#7, #8, #15 and #23 as incompletely closed**, each with
> proof. Read it before picking up work from this file. Its headline, #38, is that nothing in the
> codebase validates the *shape* of a Claude response before persisting it.

File and line references in unstruck text describe the code *as it was when the gap was found*. Some
have moved; the struck entries note where. Two claims turned out to be **wrong on inspection** and are
withdrawn rather than "fixed" — see #23's push-token bullet.

**Status: 34 of 37 fully closed, 2 partial, 1 open** (#22, #25, #30 closed and part of #23 closed on
2026-08-08). The one open item is **#3** (email provider). **#33** is in flight. The 2 partials are #23
(`users.age` nullable / the 18+ gate remains a product call) and #35 (needs an EAS account).

Suite: **727 backend tests**, up from 539 at the start of 2026-08-08.

See [GAPS-ROUND-2.md](GAPS-ROUND-2.md) for 30 further findings; its two P0s are both fixed, and
everything from #40 down is open.

**Every P0 and P1 is closed except #3** — no email provider, so password-reset tokens go to stdout. That
one is blocked on choosing a provider, not on effort.

Suite: **539 backend tests at 90.01% coverage** (from 413, and from 15 failing on a clean checkout when
the audit started), plus **39 client-side tests** where there were zero.

The 5 partials are #22, #23, #25, #30, #35 — in each case the substance landed and something specific was
left deliberately, stated in the entry. The 2 open are **#3** (needs a provider decision) and **#33** (a
session of its own). Full breakdown under "Remaining work" at the bottom.

Note on **#5**: marked MITIGATED rather than FIXED. User text is now JSON-encoded, fenced as untrusted,
and every returned index is range-checked and de-duplicated, so a reply cannot be written into a
conversation outside its batch. A batched call still shows one user's text to a model that is writing
replies for others; full isolation means one call per conversation, at _BATCH_SIZE times the cost.

---

## P0 — Fix before any real user touches this

### 1. ~~`GET /api/profile/{user_id}` is unauthenticated and returns every user's email~~ ✅ FIXED (cf5f690)

`app/api/profile.py:132-137` has no `get_current_user` dependency and returns the full `UserOut`, which
includes `email`, `is_premium`, `daily_swipes`, and `swipes_reset_at` (`app/schemas/user.py:35-61`).
Anyone can walk `?user_id=1,2,3…` and harvest the entire user table's email addresses.

The codebase already has the right pattern — `DiscoverUserOut` and `MatchedProfileOut` are deliberately
narrow. Fix: add the auth dependency **and** return a narrow schema.

### 2. ~~`/api/mobile/auth/login` has no rate limiting~~ ✅ FIXED (cf5f690)

`app/api/mobile_auth.py:102-111` is a straight credential check. The IP + email brute-force protection
at `app/api/auth.py:136-158` doesn't exist on this path, so the mobile endpoint is an unthrottled
bypass of the web limiter. This is the login endpoint the shipped app actually uses, and it has **zero
tests**.

### 3. Password reset and verification tokens are printed to stdout

`app/services/email.py:24-32, 44-51` — there is no email provider. Every reset token goes to the
Railway log stream, which is a complete account-takeover primitive for anyone with log access. Users
also simply never receive the emails, so the reset flow is non-functional in production.

### 4. ~~All 1000 seeded bots share one committed password~~ ✅ FIXED (cf5f690)

`scripts/seed_demo_users.py:208` bcrypts the literal string `"howl-demo-placeholder"`, and the seed
runs on every production deploy with `is_email_verified=True`. Anyone who reads this repo can log in as
`demo1@howl.app`. Generate a random per-deploy secret, or set an unusable hash.

### 5. ~~Prompt injection across users in the bot batch~~ ✅ MITIGATED (b2efe68)

`app/tasks/bot_response.py:105` interpolates raw user messages into a single prompt covering **10
different conversations** and asks for a JSON array keyed by index. One user's message can steer the
replies sent to *other* users. `:143` bounds `index < len(batch)` but not `index >= 0`, so a negative
index silently targets the wrong conversation. Batch per conversation, or validate the index range and
delimit user content.

### 6. ~~Password reset doesn't revoke sessions~~ ✅ FIXED (b2efe68)

`app/api/auth.py:245-277` rehashes the password but leaves every `RefreshToken` row live. A user
resetting a password because they were compromised stays compromised for up to 30 days.

---

## P1 — Correctness and cost

### 7. ~~`generate_avatar` is not idempotent under `task_acks_late=True`~~ ✅ FIXED (e4f64ba)

`app/celery_app.py:26` plus zero guarding in `app/tasks/avatar.py:40`. A worker killed after the DALL·E
call but before the commit re-runs everything — a second Claude call and a **second paid image**. Add a
Redis lock or an "already generating" check keyed on `user_id`.

### 8. ~~Unbounded AI spend in the Beat task~~ ✅ FIXED (b2efe68)

`app/tasks/bot_response.py:166, 243` has no cap on `pending`. With 1000 seeded bots, every 15-minute
tick can issue `len(pending)/10` Claude calls with no ceiling and no circuit breaker. Worse, a failing
batch returns `[]` (`:145-147`) leaving the messages unanswered, so the **same failing batch is
re-selected and re-paid for on every subsequent tick, forever**.

### 9. ~~Premium users have no avatar generation cap at all~~ ✅ FIXED (78bde8e)

`app/api/avatar.py:75, 87-88` — the 1-per-30-days limit applies only to non-premium. A premium account
can call a paid DALL·E endpoint in an unbounded loop.

### 10. ~~Orphaned R2 objects on every regeneration~~ ✅ FIXED (eda6430)

`app/api/avatar.py:82` nulls `avatar_url` without calling `delete_avatar()`, and
`app/tasks/avatar.py:115` overwrites it. Every regeneration leaks the previous object into R2 forever.

### 11. ~~Truncated Claude output discards 10 conversations~~ ✅ FIXED (b2efe68)

`app/tasks/bot_response.py:129` uses `max_tokens=1024` for up to 10 replies; overflow produces invalid
JSON and the whole batch is dropped. `:132` also does `resp.content[0].text` blindly instead of
filtering for `block.type == "text"` the way `app/tasks/avatar.py:73-76` correctly does. No
`stop_reason` check exists anywhere in the codebase.

### 12. ~~Live `ReferenceError` in the web client~~ ✅ FIXED (d4a69b4)

`frontend/src/App.jsx:678` calls `setGenerationTime(null)` inside `handleRegenerate`. The state was
deleted in commit `1fbd58d`; only `setGenerationStartTime` exists (`App.jsx:41`). Clicking "Regenerate"
throws before `setAvatarStatus(data)` runs, and with no error boundary anywhere the UI dies. `:376` has
the same call in `handleUpdateBio`, which is dead code.

### 13. ~~Mobile has no network error handling~~ ✅ FIXED (85554af)

`mobile/src/api/client.ts:50` — no timeout, no `AbortController`, no try/catch around `fetch`. Every
call site awaits `api()` without a guard, so airplane mode produces an unhandled rejection. No error
boundaries exist in either client.

### 14. ~~Race conditions in swipe handling~~ ✅ FIXED (a7e7ef3)

`app/api/swipes.py:80-98` check-then-insert on duplicate swipes and on the `daily_swipes` increment;
`:104-118` can create duplicate `Match` rows on simultaneous mutual likes. `undo_last_swipe` orders by
`created_at` rather than `id` (`:166`), which is nondeterministic at SQLite's second resolution.

### 15. ~~Demo detection by email prefix~~ ✅ FIXED (eda6430)

`app/api/swipes.py:135` uses `target.email.startswith("demo")`. Any real user who registers
`demo.something@…` gets bot auto-match behavior. The `is_bot` column already exists — use it.

### 16. ~~Notifications have no retries~~ ✅ FIXED (9933488)

`app/tasks/notify.py:26, 105` — neither task binds or retries, and
`app/services/push_notifications.py:49-50` swallows every exception. Expo's per-ticket errors in the
200 response body are never parsed, so `DeviceNotRegistered` tokens are never pruned and dead tokens
accumulate forever.

---

## P2 — Architecture and scale

### 17. ~~Real-time chat is single-replica-only~~ ✅ FIXED (b2a36f8)

`app/api/chat.py:36-38` — `ConnectionManager` is an in-process dict, correctly documented as unsafe for
multiple replicas. Any horizontal scaling silently drops delivery for users on other processes. Needs
Redis pub/sub fan-out before scaling past one web process.

### 18. ~~`auth.py` and `mobile_auth.py` are drifting duplicates~~ ✅ FIXED (5583de5)

Beyond the missing rate limit (#2), `mobile_auth.py:66` hardcodes `timedelta(days=30)` instead of
`settings.refresh_token_expire_days`, and `:85` uses `_TOKEN_EXPIRY_HOURS` (1h, the *password-reset*
constant) for email verification where web uses 24h — mobile verification links expire 24× sooner.
`:19-26` imports four names it never uses. Extract a shared auth service; keep the two routers as thin
token-delivery shells.

### 19. ~~N+1 query storms~~ ✅ FIXED (5698a72, a7e7ef3)

- `app/tasks/bot_response.py:168-206` — all bots, then per bot all matches, then per match a
  `db.get(User)`, a last-message query, and a count. At 1000 bots this runs every 15 minutes against
  the same database serving requests.
- `app/api/blocks.py:94-96` — per-block `db.get(User, ...)`, in contrast to the deliberately optimized
  `list_matches`.

### 20. ~~Missing indexes on hot paths~~ ✅ FIXED (026ef4b)

- `swipes.target_user_id` (`app/models/swipe.py:25-27`) — no index, and it's the reciprocal-like lookup
  at `app/api/swipes.py:108, 193` and `app/api/blocks.py:29-30`. Every match check scans.
- `messages.sender_id` (`app/models/message.py:20-22`) — FK, no index, queried at `app/api/chat.py:326`.
- `reports.message_id` (`app/models/report.py:30-32`) — `SET NULL` FK with no index forces a `reports`
  scan on every message delete.
- No composite `(match_id, created_at)` for chat pagination.

### 21. ~~Alembic autogenerate produces wrong output~~ ✅ FIXED (026ef4b)

Verified end to end, not assumed: `alembic revision --autogenerate` now emits an **empty**
migration, and `downgrade base` → `upgrade head` completes on PostgreSQL. Checked against a
throwaway database, never the dev one.

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

### 22. ~~Timezone handling is ad hoc~~ ✅ FIXED (026ef4b, 97029f7)

**Done:** every *creation* timestamp now carries `server_default=func.now()`, so raw-SQL and bulk
inserts no longer violate NOT NULL and history records DB time rather than app-host clock skew.
`tests/test_schema_constraints.py` asserts this for all six tables and proves a raw `INSERT` gets a
`created_at`.

**Still open, deliberately:** the scattered `replace(tzinfo=utc)` normalization. Under SQLite (the whole
test suite) these columns read back **naive**, so the normalization is load-bearing wherever a stored
timestamp is compared against `datetime.now(UTC)`. Sites still lacking it: `regenerations_reset_at`,
`avatar_status_updated_at`, `message.read_at`, `deleted_at`. (`swipes_reset_at` and
`email_verification_token_expires_at` were normalized as part of #14 and #18.) The right fix is one
helper used everywhere rather than fixing them one at a time — a `TypeDecorator` on the column would
also work and would remove the need to remember.

**Both halves are now closed (2026-08-08, 97029f7)**, and one of them was closed by discovering the
claim was false:

- The scattered normalisation is replaced by **one mechanism**: `app/models/types.py`'s `UtcDateTime`
  `TypeDecorator`, applied to **all 18** timestamp columns across all nine models — not just the four
  that were missing it, since a mechanism applied to half the columns teaches the wrong lesson. Inbound
  naive is assumed UTC (the convention every writer already follows); an aware non-UTC value is
  *converted*, not stripped, so the instant never moves. No migration: the DDL is identical, proven by
  autogenerate emitting a bare `pass` against a throwaway Postgres at head, plus a standing assertion
  that `UtcDateTime().compile()` is byte-equal to `DateTime(timezone=True)` on both dialects.
- **The `updated_at` claim below was WRONG and is withdrawn.** Measured, not assumed: Core `update()`,
  `Query.update()` and `bulk_update_mappings` **all fire** the Python-side `onupdate` — SQLAlchemy's
  compiler adds the column to the SET clause whenever it compiles a Column-aware statement. Only raw
  `text()` does not, and `app/` contains no raw SQL writes. So `app/api/swipes.py` was already correct
  and `app/tasks/notify.py` no longer bulk-updates at all (its bulk statement is a `.delete()`). No fix
  was landed, deliberately, and the behaviour is pinned by tests so nobody adds a Postgres trigger for a
  non-problem. A column-level server-side `onupdate` was not available anyway: Postgres has no
  `ON UPDATE` column clause, and on SQLite `CURRENT_TIMESTAMP` drops to whole-second precision.

Six `replace(tzinfo=utc)` sites are now redundant no-ops, left in place to avoid cross-branch conflicts
and safe to delete in a follow-up: `app/api/avatar.py:43`, `app/api/profile.py:43`, `app/api/swipes.py:56`,
`app/dependencies.py:85`, `app/services/auth_service.py:102`, `app/tasks/bot_response.py:79`.

<details><summary>The withdrawn claim, for history</summary>

`updated_at`'s Python `onupdate` being skipped by bulk `.update()` is unchanged and is still a real
trap: `app/api/swipes.py` and `app/tasks/notify.py` both use bulk updates now.

</details>

### 23. ~~Missing constraints~~ 🟡 MOSTLY FIXED (026ef4b)

**Done:**
- `ck_matches_user_order` makes `user1_id < user2_id` a real CHECK. `uq_match_users` only blocked an
  exact duplicate pair, so the same two people could hold both `(a, b)` and `(b, a)`. Being strict also
  makes a self-match impossible.
- `age_preference_min <= age_preference_max` is cross-validated with a pydantic `model_validator`.
  Per-field checks could never catch it: 40 and 25 are both individually legal, but the range matches
  nobody and silently empties the discover queue.
- `get_db()` rolls back on exception, so a request that raises mid-flush cannot hand a dirty session
  back to the pool for the next request to commit.

**This bullet was WRONG and is withdrawn:** `push_tokens.token` should *not* gain a `(user_id, token)`
pair constraint. The global uniqueness is deliberate — one physical device must only ever receive pushes
for the account currently signed in on it, and a pair constraint would let two accounts both hold the
same device and both get its notifications. `app/api/push_tokens.py` already reassigns the row instead
of inserting, which is the correct behaviour. Pinned by
`test_shared_device_reassigns_its_push_token` so a future "fix" cannot regress it.

**Deferred, with reasons:**
- `users.age` stays nullable. Making it NOT NULL breaks every existing row, and the 18+ gate needs an
  API-layer decision about what to do with accounts that never set an age — reject them at login, or
  force a completion step. That is a product call.
- No CHECK ties `avatar_status = 'ready'` to `avatar_url`/`animal`. The avatar pipeline writes these in
  more than one step, so a CHECK would need the whole transition to be transactional first.

### 24. ~~Report evidence is destroyed by cascade~~ ✅ FIXED (026ef4b)

Resolved in favour of retention: all three FKs are now `SET NULL`, so a deletion anonymises a
report but never destroys it. The abuser deleting their own account was erasing the case against
them.

`app/models/report.py:29` sets `message_id` to `SET NULL` explicitly "so reports survive message
deletion" — but `reporter_id` and `reported_user_id` are `CASCADE` (`:24, 27`). Deleting the reported
user deletes the report. The stated intent and the constraints contradict each other.

### 25. ~~`is_email_verified` is never enforced~~ ✅ FIXED — enforcement is live, graduated

**Decided and shipped on 2026-08-08.** Nathan's call was "do the right thing / whatever is typical
industry practice". That is a **grace window**, not a hard gate at registration:

- An unverified account keeps full access for `settings.email_verification_grace_period_hours`
  (default **72**), measured from `users.created_at`. No new column — derived, so no migration.
- After that window the **outbound** actions close: `POST /api/swipes`, `DELETE /api/swipes/last`,
  `POST /api/matches/{id}/messages`, `POST /api/avatar/regenerate`, and the chat WebSocket (rejected at
  connect with an error frame then close **4403**, fitting the existing 4001/4003 scheme; placed *after*
  the match-authorisation check so a non-member still gets 4003 and learns nothing).
- Reads stay open throughout — discover, matches, message history, unread count, avatar status — plus
  profile read/edit, resend-verification, logout, push-token registration and account deletion. The user
  can see what they are about to lose, which is the point.
- `settings.enforce_email_verification` (default **True**) is the operator kill switch, read at call
  time so flipping it needs no code change.
- **403 contract**, asserted by an exact-key-set test so a rename fails loudly:
  `{"detail": {"code": "email_verification_required", "message": …, "grace_expired_at": <ISO8601>}}`
- `scripts/backfill_email_verification.py` grandfathers pre-enforcement accounts. **Dry-run is the
  default**; `--apply` is required, `--cutoff` accepts an ISO datetime (naive read as UTC, not
  server-local, or the cutoff silently shifts by the host offset).
- Seeded bots were already `is_email_verified=True`; that is now pinned by a test so a future seed edit
  fails loudly.
- The bio-edit walk-around is closed: `PATCH /api/profile/me` still saves, but withholds the paid DALL·E
  call when unverified past grace and leaves `profile_needs_regen=True` so it runs once verified — and
  the check happens *before* a regen slot is consumed, so a withheld image doesn't bill the quota.

**Two corrections to what this entry used to claim:**

1. **The old rationale was not literally true.** This entry said enforcement would "empty the discover
   queue" by locking out the 1000 bots. Discover filters on `avatar_status`, not verification, and bots
   act through Celery tasks that write directly, bypassing the HTTP gate entirely. The real invariant
   (no seeded bot is ever refused) is what got pinned.
2. **`test_require_verified_email_is_not_wired_to_any_route` is gone**, replaced by its inverse: a
   tripwire asserting the dependency IS wired to exactly the intended route set, so a refactor that
   silently drops it fails.

**The known weak point, and it is real:** email is **not editable anywhere** — `ProfileUpdate` has no
`email` field. So resend-verification re-sends to the same wrong address, and combined with **#3** (no
provider; tokens print to stdout) a typo'd signup is permanently stuck once grace expires. The kill
switch is the only remedy. Making email editable, or an admin repair route, is the natural follow-up.

`DELETE /api/matches/{id}` (unmatch) was left **ungated** on purpose and deliberately not pinned: it is
arguably remediation — getting away from someone — rather than an outbound action. That one is still a
product call.

<details><summary>Original entry (for history)</summary>

**Done:** the missing resend-verification endpoint now exists on both routers, rate-limited, with a
generic response that does not reveal whether an address has an account or is already verified. A
`require_verified_email` dependency is built and tested (403, not 401 — the caller authenticated fine,
re-authenticating won't help).

**Not done, on purpose:** the dependency is attached to **no route**. Turning it on retroactively locks
out every account created before enforcement existed, including all 1000 seeded bot users, which would
empty the discover queue and break every demo conversation. That is a product decision, not a code one.

`test_require_verified_email_is_not_wired_to_any_route` asserts it stays unwired and will fail loudly
the moment someone enables it — at which point delete the test and decide:
1. which routes get it (messaging and swiping are the plausible ones; profile editing probably not, or
   users can't fix a typo'd email), and
2. what happens to existing accounts — backfill `is_email_verified = true` for everything created before
   a cutoff, and set it on the bots in `scripts/seed_demo_users.py`.

Blocked in practice by **#3** anyway: with no email provider wired, a user who is locked out cannot
receive the link that would unlock them.

</details>

### 26. ~~Rate limiting is login-only and defeatable~~ ✅ FIXED (5583de5, b2a36f8)

Registration, forgot-password, reset-password, verify-email, and message send are unthrottled. The IP
bucket trusts the first `X-Forwarded-For` value unconditionally (`app/api/auth.py:136-139`) with no
`TrustedHostMiddleware` or proxy allowlist, so it's spoofable. Chat's send limit uses a DB `COUNT` per
request (`app/api/chat.py:321-332`) instead of the existing Redis limiter. WS `typing` events have no
limit at all (`chat.py:202-203`).

---

## P3 — Engineering hygiene

### 27. ~~No CI, and none of the configured quality tools ever run~~ ✅ FIXED (419f580, 2b37407)

There is no `.github/`, no pre-commit, no Makefile. **372 tests exist and nothing runs them
automatically.** ruff (`pyproject.toml:36-41`) and mypy `strict=true` (`:43-46`) are both configured and
installed and have **zero invocation points** in the repo.

This is the single highest-leverage fix on this list: a GitHub Actions workflow running
`pytest` + `ruff check` on PRs costs an hour and permanently protects everything above.

### 28. ~~`pyproject.toml` dependencies are stale and would install a broken app~~ ✅ FIXED (658cf2b)

`pyproject.toml:10-24` omits `openai`, `boto3`, `sentry-sdk`, `httpx`, and `pydantic[email]` — all
present in `requirements.txt:11-18` and imported by the app. `pip install -e .` yields an app that
can't start. Pick one source of truth.

### 29. ~~Zero client-side tests~~ ✅ FIXED (2488c3a)

23 backend test files, and **no test script in either `package.json`**. No jest, vitest, RTL, Detox, or
Playwright. No ESLint or Prettier config in either client either.

### 30. ~~Untested backend surfaces~~ ✅ FIXED (cf5f690, 9933488, 5583de5, + 2026-08-08)

**Now covered:**
- `app/api/mobile_auth.py` — was **zero tests** while being the entire auth surface the shipped mobile
  app uses. Now covered by `test_mobile_auth.py` plus `test_auth_hardening.py`, which specifically pins
  the two drift bugs from #18.
- `app/services/push_notifications.py` — was never called outside mocks. `test_push_notifications.py`
  is 29 tests against the real module, including the Expo ticket parsing.
- `app/services/rate_limit.py` — now exercised directly, including the client-IP derivation and the
  fail-open-on-Redis-error path.

**Now covered too (2026-08-08), closing this entry:**
- The **R2 upload path** — driven against a real `boto3` S3 client backed by `moto`, injected at the
  existing `_get_r2_client()` seam (no production code changed). Key naming, `ContentType`, URL
  construction, `delete_avatar()`, and the credential/network failure paths all verified.
  `moto[s3]` was added to `[project.optional-dependencies].dev` in `pyproject.toml` only —
  `requirements.txt` stays the runtime source of truth per #28.
  **One honest limitation:** `moto`'s `@mock_aws` only intercepts `*.amazonaws.com` hostnames, so a
  client pointed at R2's `*.r2.cloudflarestorage.com` `endpoint_url` is *not* intercepted. Everything
  downstream of client construction is now proven; the actual dial-out to a real R2 endpoint still has
  never executed and cannot be tested without live credentials.
- `scripts/seed_demo_users.py` — driven end to end against a private in-memory SQLite engine
  (`SessionLocal` monkeypatched, never the shared dev Postgres). Covers idempotency across simulated
  repeat deploys, the #4 random per-deploy password (pinned against regressing to the old committed
  literal), `is_bot`/`is_email_verified`, `avatar_status=ready` with `avatar_url=None`, the #23 age
  CHECK, and the archetype distribution.

**Two real bugs found by writing these tests, documented as tests rather than fixed** (both are behaviour
calls, not test gaps):
- `delete_avatar()` extracts the S3 key by string-stripping the *current* `_r2_public_base()` off the
  stored `avatar_url`. Rotate `R2_PUBLIC_URL` (a custom-domain migration) and the prefix stops matching
  for already-stored avatars: `key` becomes the whole old URL, `delete_object` is called with the wrong
  Key, and the object leaks forever with no exception and no distinguishing log. Defeats #10's goal.
  Pinned by `test_delete_avatar_key_extraction_breaks_if_public_url_base_has_rotated`.
- The seed's delete filter `email LIKE 'demo%@howl.app'` matches any address merely *starting* with
  "demo" — a real `demolition@howl.app` account would be wiped on every deploy. Pinned by
  `test_seed_delete_filter_also_matches_lookalike_demo_prefixed_emails`. See **GAPS-ROUND-2 #39**, which
  is the far more serious version of this same delete.

### 31. ~~No coverage gate~~ ✅ FIXED (658cf2b)

Measured 90.0%; `fail_under = 88` so the gate passes today and can ratchet.

`[tool.coverage]` has no `fail_under`, and coverage isn't in pytest's `addopts`. `.coverage` and
`htmlcov/` in the repo root are ~2 months stale relative to the code.

### 32. ~~Two clients duplicating drifting logic~~ ✅ FIXED (658cf2b)

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

### 34. ~~Mobile accessibility is absent~~ ✅ FIXED (85554af, 567b3ef)

Zero accessibility props → 173, across every file containing an interactive element.

**Zero** `accessibilityLabel` / `accessibilityRole` / `accessibilityHint` in the entire app. Icon-only
buttons are bare emoji (`discover.tsx:260, 267`, `chat/[matchId].tsx:228, 297`). All font sizes are
fixed numbers, so no dynamic type. The web client has exactly one `aria-label`.

### 35. ~~Mobile is not actually shippable yet~~ 🟡 MOSTLY FIXED (85554af) — **one item needs an EAS account**

**Done:**
- every `eas.json` build profile now sets `EXPO_PUBLIC_API_URL` (and `EXPO_PUBLIC_WEB_URL`). A
  production build previously pointed at `http://localhost:8001`, which on a real phone resolves to the
  phone itself. `client.ts` also no longer falls back to localhost outside dev — a missing value now
  surfaces as a diagnosable configuration error instead of an opaque network failure.
- `submit.production` documents exactly which values need the Apple/Google accounts, and notes that the
  Play service-account JSON is a credential that must stay out of the repo.
- password reset exists on mobile at all now — there was previously **no in-app path** for a forgotten
  password. Two new screens, using the shared cookie-free `/api/auth/*` endpoints.
- a legal screen is reachable in-app, which both stores require given push plus user-generated content.
  It is a substantive summary plus an outbound link rather than a copy of the web page's 213 lines,
  because duplicated legal text that disagrees with itself is worse than a summary. It cannot deep-link
  to the canonical page yet — the web client addresses legal by a `view` string, not a URL (see #33).
- the WS token is still in the query string (moving it needs a backend change) but now has the
  refresh-on-expiry path it was missing.

**Needs Nathan:** `eas login && eas init` to populate `extra.eas.projectId` in `app.json`.
`getExpoPushTokenAsync` fails in real builds without it. The Railway/Vercel hostnames in `eas.json` are
placeholders and need the real ones.

### 36. ~~Docs were stale before this pass~~ ✅ FIXED (658cf2b)

Now corrected in `CLAUDE.md` / `RUNBOOK.md`, but `README.md` still says: `DATABASE_URL` on port 5432
with password `howl` (`:107` — actually 5433/`howl_dev`), "18 migrations" (`:253` — there are 21), an
API table omitting every mobile and push-token endpoint (`:141-172`), a project tree missing six files,
a test table missing `test_push_tokens.py`, and run instructions omitting Celery Beat (`:127-136`).
`ALLOWED_ORIGINS` is listed as required at `:470-477` but appears nowhere in `.env.example`. ADR.md says
"five related tables" (there are nine) and "9 migration files" (21). There's no LICENSE file despite
`README:537` claiming MIT.

### 37. ~~Repo litter~~ ✅ FIXED (658cf2b)

- Three empty directories named `c:UsersnathaDocumentsmagicshit…` — created by `mkdir -p` on a Windows
  path inside Git Bash, where backslashes were eaten as escapes. Untracked, empty, safe to delete.
- `env/` — a dead 26 MB venv containing only pip and setuptools. `.venv/` is the real one.
- `.coverage`, `htmlcov/`, `.pytest_cache/`, `__pycache__/` present locally (all gitignored).
- `.claude/settings.local.json` contains a hardcoded PID (`Get-Process -Id 6108,27180`) and a one-shot
  `alembic revision -m "Add User model"` allow-rule.

---

## Remaining work

**30 fully closed, 5 partial, 2 open.** What is actually left:

1. **#3 — wire an email provider.** The only open P0, and the only one blocking a real launch. Password
   reset is non-functional and reset tokens print to the Railway log stream, which is an account-takeover
   primitive for anyone with log access. Needs a decision: Resend, Postmark or SES. Everything else in
   the reset flow is built and tested and will work the moment `app/services/email.py` has a transport.
   This also unblocks the second half of **#25**.

2. **#25 enforcement — a product decision.** The dependency and the resend endpoint exist; attaching it
   locks out every pre-existing account and all 1000 bots. See the entry for the two questions to answer.

3. **#33 — decompose `App.jsx`.** Untouched: still one 1073-line component, ~45 `useState` hooks, a
   `view` string instead of routing, `ProfileView` taking 24 props. It is a session of its own, and it
   is also what blocks mobile from deep-linking to a real `/privacy` URL (see #35). The new ESLint config
   already reports eight missing hook dependencies and several dead bindings in here.

4. **Leftovers inside otherwise-closed entries**, each documented in place:
   - **#22** — the `replace(tzinfo=utc)` sites still scattered across four columns. Wants one helper or a
     `TypeDecorator`, not four more one-off fixes.
   - **#23** — `users.age` nullable (the 18+ gate) is still a product call. The CHECK is **done**:
     migration `t1n2o3p4q5r6` adds `ck_users_ready_avatar_has_animal`
     (`avatar_status <> 'ready' OR animal IS NOT NULL`). Deliberately about `animal`, **not**
     `avatar_url` — two legitimate states hold `ready` with a null url (the 1000 seeded bots, and a
     best-effort DALL·E failure falling back to an emoji), so a url-based CHECK would have aborted the
     seed step of every production deploy.
   - **#30** — the R2 upload path, i.e. the production avatar persistence path, still never exercised.
   - **#35** — `eas login && eas init` for `extra.eas.projectId`, plus the real deploy hostnames.
   - **#29** — 21 real findings the new linters surface in existing client code (dead code, four
     swallowed `err` bindings, eight missing hook deps). Left for a deliberate pass rather than an
     autofix that would have collided with the rest of this work.
   - CI typechecks mobile against expo-router's permissive `Href` fallback, because
     `.expo/types/router.d.ts` is generated and gitignored — so a bad route path will not fail CI.

### Notes for whoever picks this up

Two traps in the test harness, both now handled in `tests/conftest.py`, both of which will waste an hour
if you hit them cold:

- **pysqlite breaks SAVEPOINTs by default.** It never emits `BEGIN` before DML, so a `SAVEPOINT` lands
  outside any transaction and effectively autocommits — work inside `begin_nested()` *survives a
  rollback*. `IntegrityError`-recovery code is correct on Postgres and silently untestable without the
  workaround. Same spirit as the `PRAGMA foreign_keys=ON` that was already there.
- **Redis is real in this suite and leaks across tests and across runs.** Three autouse fixtures exist
  for this now: the login limiter, the chat send limiter (keyed on `(user_id, match_id)` — both repeat),
  and `ChatPubSub`, whose supervised reader task otherwise keeps each test's event loop open and hangs
  the entire run. `test_chat_pubsub.py` opts out via a `real_pubsub` marker because there the fan-out is
  the thing under test.

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
