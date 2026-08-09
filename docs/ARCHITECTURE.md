# Architecture

How Howl is put together, as of the current `main`. For decisions and their reasoning see
[decisions/ADR.md](decisions/ADR.md); for known problems see [GAPS.md](GAPS.md).

## System shape

```
  ┌───────────────┐        ┌──────────────┐
  │ frontend/     │ cookie │              │
  │ React + Vite  ├───────►│              │        ┌──────────────┐
  └───────────────┘        │   FastAPI    ├───────►│  PostgreSQL  │
                           │   app/       │        │  9 tables    │
  ┌───────────────┐ bearer │              │        └──────────────┘
  │ mobile/       ├───────►│  10 routers  │
  │ Expo RN       │   +WS  │              ├───────►┌──────────────┐
  └───────────────┘        └──────┬───────┘  enqueue│    Redis     │
                                  │                │ broker + RL  │
                                  │                └──────┬───────┘
                                  │                       │
                                  ▼                       ▼
                           ┌─────────────┐        ┌──────────────────┐
                           │  Expo Push  │        │  Celery worker   │
                           └─────────────┘        │  + Celery Beat   │
                                                  └────┬──────┬──────┘
                                                       │      │
                                          Claude Haiku ▼      ▼ DALL·E 3
                                        (animal/traits/prompt)  (image)
                                                       │      │
                                                       ▼      ▼
                                                 ┌──────────────────┐
                                                 │ Cloudflare R2    │
                                                 │ (or static/ )    │
                                                 └──────────────────┘
```

## The avatar pipeline — the core feature

This is a **two-provider** pipeline. Claude does not draw the picture; it writes the brief.

1. User saves a bio (`PATCH /api/profile/me`) or hits `POST /api/avatar/regenerate`.
   The endpoint sets `avatar_status = pending` and enqueues `generate_avatar.delay(user_id)`
   (via `app/services/task_queue.py`'s `enqueue()`, which fails open on a dead broker — see GAPS #43).
2. `app/tasks/avatar.py:85` calls **Claude Haiku** (`claude-haiku-4-5-20251001`, `avatar.py:136`) with
   the user's bio and asks for JSON: `{animal, personality_traits, avatar_description, image_prompt}`.
   The animal list in the prompt is suggestive, not enumerated — the value is effectively free text,
   lowercased and validated non-empty by a Pydantic model (`_ClaudeAvatarPayload`, `avatar.py:30-69`)
   before anything is persisted, so a plausible-but-wrong shape from Claude fails the avatar rather than
   writing a bad row (GAPS #38, the P0 this closed).
3. `image_prompt` is handed to `generate_avatar_image()` (`app/services/image_generation.py:155`),
   which calls **OpenAI DALL·E 3** at 1024×1024, standard quality.
4. The resulting temporary URL is downloaded with a 30s httpx client and persisted:
   `_upload_to_r2()` first, falling back to `static/avatars/<uuid4>.png` (`image_generation.py:184`).
   R2 returns a full HTTPS URL; local returns `/avatars/<file>`. Both shapes appear in `avatar_url`.
5. The row is written with `avatar_status = ready`.

**Duplicate-work protection:** `task_acks_late=True` means a worker killed after the DALL·E call but
before the commit gets the message redelivered. An already-ready check short-circuits redelivery after a
successful run, and a Redis single-flight lock (`app/services/task_lock.py`) covers concurrent/in-flight
duplicates; the lock fails open, so a Redis outage degrades to the pre-lock behavior rather than blocking
generation.

**Failure behavior:** only `anthropic.APIError` triggers a retry (3×, 60s apart, `avatar.py:209-215`).
JSON/Key/Value/shape-validation errors fail permanently. If the *image* step fails, the avatar is still
marked ready and the clients render an emoji placeholder from their animal→emoji map. If `OPENAI_API_KEY`
is unset, every avatar is a placeholder — this is the intended degraded mode.

**Queueing:** `generate_avatar` is routed onto the default Celery queue with its own soft/hard time
limit (240s/300s) so a hung Claude or DALL·E call can't park a worker indefinitely, and — as of GAPS #55 —
it can no longer queue behind a `process_bot_responses` batch, which is now routed to a separate
`bot_response` queue. See **Background work** below.

**Quota:** non-premium users get 1 regeneration per 30 days. The counter is shared between
`POST /api/avatar/regenerate` (which 429s) and a bio edit via `PATCH /api/profile/me` (which instead
silently sets `profile_needs_regen = true`). Premium users get a much higher but still finite cap
(`_PREMIUM_REGEN_LIMIT = 100`, `app/api/avatar.py`) — not unlimited, but bounded against runaway cost on
a paid endpoint.

## Request auth

One dependency resolves both clients (`app/dependencies.py:14-19`):

```
access_token cookie  →  Authorization: Bearer <jwt>  →  401
```

- **Access token**: HS256 JWT, `{sub, exp}`, 30 min default.
- **Refresh token**: opaque `token_urlsafe(32)`, stored as a plaintext DB row with `revoked` flag,
  30 days. **Never rotated on use** — refreshing mints a new access token and reuses the same refresh
  token until expiry.
- **Web** sets both as httpOnly cookies with `secure = not debug` and `samesite = none` in production
  (cross-site Vercel → Railway). **Mobile** gets them in the JSON body from `/api/mobile/auth/*`.
- Password reset does **not** revoke existing refresh tokens.
- `is_email_verified` is written by `app/services/auth_service.py` (`:237`) and enforced by
  `require_verified_email` (`app/dependencies.py`), attached to the *outbound* actions — avatar
  regenerate, chat send, swipe — via a graduated grace period rather than a hard gate at registration
  (GAPS #25). Reads stay open throughout. It is **not** attached to `PATCH /api/profile/me` or account
  deletion.

## Routers

All mounted in `app/main.py:67-76`, each carrying its own prefix.

| Router | Prefix | Endpoints |
|---|---|---|
| `auth.py` | `/api/auth` | register, login, me, refresh, logout, verify-email, resend-verification, forgot-password, reset-password |
| `mobile_auth.py` | `/api/mobile/auth` | register, login, refresh, logout, verify-email, resend-verification (tokens in body) |
| `profile.py` | `/api/profile` | GET/PATCH/DELETE `me`, GET `{user_id}` (authenticated, narrow `PublicProfileOut` — fixed, GAPS #1) |
| `avatar.py` | `/api/avatar` | status, regenerate |
| `users.py` | `/api/users` | discover, matches |
| `swipes.py` | `/api/swipes` | POST swipe, DELETE last (undo) |
| `chat.py` | `/api/matches` | WS `{id}/ws`, messages GET/POST/DELETE, unread-count, DELETE match |
| `blocks.py` | `/api/blocks` | POST, DELETE `{id}`, GET |
| `reports.py` | `/api/reports` | POST |
| `push_tokens.py` | `/api/push-tokens` | POST, DELETE |

Plus `GET /health`, `GET /health/live`, and a `StaticFiles` mount at `/avatars`.

`/health` runs `SELECT 1` against Postgres and `PING`s Redis (both ~1s timeouts) and returns 503 if
either is down, so it doubles as the Railway deploy healthcheck and a real liveness signal (GAPS #54,
closed on this branch). `/health/live` is a dependency-free always-200 path for whichever check must not
restart the container on a transient blip.

## Real-time chat

- WebSocket at `/api/matches/{match_id}/ws`, authenticated by the `access_token` cookie **or**
  `?token=<jwt>` (mobile). Close codes: `4001` bad auth, `4003` not a member of this match, `4403` email
  verification grace period expired (`WS_EMAIL_VERIFICATION_REQUIRED`, `app/dependencies.py`).
- Inbound: only `{"type":"typing"}` is handled; everything else is ignored. Messages are **sent over
  REST**, not the socket.
- Outbound: `new_message`, `message_deleted`, `typing`. `is_mine` is computed per recipient at
  broadcast time (`app/api/chat.py:192`), not stored on the message, so the same event serialises
  differently for sender and recipient.
- The connection registry (`ConnectionManager`, `app/api/chat.py:104`) owns local sockets per process,
  but fan-out across replicas is real now: `app/services/pubsub.py`'s `ChatPubSub` carries events between
  replicas over one Redis channel per match. This is no longer single-replica-only by construction — see
  [ADR-009](decisions/ADR.md). It **fails open to local-only delivery** if Redis is down (a Redis outage
  costs cross-replica fan-out, not chat correctness, since a message is committed to Postgres before it
  is broadcast).
- Send rate limit is 10 messages/60s, counted via the same Redis limiter used by login
  (`app/services/rate_limit.py`'s `check_rate_limit`), keyed per `(sender, match)` (`chat.py:43-58`) —
  no longer a DB `COUNT` per request.

## Background work

`app/celery_app.py` — Redis is both broker and result backend. `task_acks_late=True`,
`worker_prefetch_multiplier=1`, JSON serialization, UTC, `task_ignore_result=True` and bounded broker
transport timeouts (GAPS #43 — enqueueing fails open in ~2s instead of blocking ~109s on a dead broker).
`result_expires` is explicit (3600s). One Beat entry: `process_bot_responses` every 900s.

**Queue routing (GAPS #55, closed on this branch):** `process_bot_responses` — up to 20 sequential Claude
calls per tick, minutes of wall clock — is routed to its own `bot_response` queue via `task_routes`, so it
can no longer starve `generate_avatar` or the notify tasks on the shared default queue. This requires an
actual second worker consuming that queue in production; see [RUNBOOK.md](RUNBOOK.md#deploy-railway).
Every task now has an explicit soft/hard time limit via `task_annotations`, so a hung provider call raises
instead of parking a worker indefinitely.

| Task | Trigger | Queue | Time limit (soft/hard) | Retries |
|---|---|---|---|---|
| `generate_avatar` | profile save, avatar regenerate | `celery` | 240s / 300s | 3× on `anthropic.APIError` only |
| `auto_match_demo_user` | a real user likes a `demo*` account; 90% like back | `celery` | 30s / 45s | 3× generic |
| `process_bot_responses` | Beat, every 15 min | `bot_response` | 780s / 840s | **none** |
| `notify_new_message` | message send; skipped if recipient active in last 5 min | `celery` | 20s / 30s | 5× with backoff+jitter, transient failures only |
| `notify_new_match` | mutual like | `celery` | 20s / 30s | 5× with backoff+jitter, transient failures only |

## The bot population

`scripts/seed_demo_users.py` creates **1000 bot users** (`demo1@howl.app` …, `random.seed(42)`, so it's
deterministic) and runs on every production deploy via `scripts/predeploy.sh` (GAPS #56 moved it there
from `startup.sh`, so it runs once per deploy rather than once per replica). Bots are ordinary `users`
rows with `is_bot = true` and an `archetype`. Their spirit animals are **hardcoded** (20 entries,
round-robin) and their `avatar_url` is `NULL`, so they all render as emoji placeholders.

Six archetypes, each with a reply delay and a voice, defined in **three places that must be kept in
sync by hand** (`app/tasks/bot_response.py:32-46`, the prompt at `:111-116`, and the seed script's
population split at `seed_demo_users.py:199-206`):

| Archetype | Delay | Behavior |
|---|---|---|
| `responsive` | 5 min | friendly, engaged |
| `slow_burn` | 120 min | thoughtful, concise |
| `flirty` | 10 min | playful, ≤1 emoji |
| `intellectual` | 30 min | asks a real question |
| `ghost` | 1 min | terse; goes silent after 4 messages |
| `desperate` | 0 min | overeager; follows up after 2h of silence |

Every 15 minutes the Beat task scans all bots × all their matches, batches up to 10 pending
conversations into **one** Claude Haiku call, and writes the replies. A malformed or truncated response
discards the whole batch of 10.

## Data model

Nine tables. Cleanup is entirely FK-driven — `ON DELETE CASCADE` on most relationships, `ON DELETE SET
NULL` where a child row (a report) should survive the referenced row's deletion — and there is no
`relationship()` anywhere: every join is hand-written in the API layer.

- **`users`** (32 columns) — auth, profile, preferences, and the spirit-animal cluster: `animal`,
  `personality_traits` (JSON), `avatar_description`, `avatar_url`, `avatar_status` (enum
  pending/ready/failed), `avatar_status_updated_at`, `avatar_regenerations_this_month`,
  `regenerations_reset_at`, `profile_needs_regen`, plus `is_bot`/`archetype`.
- **`swipes`** — unique on `(user_id, target_user_id)`; `direction` enum where the Python member
  `pass_` maps to the DB value `pass`.
- **`matches`** — unique on `(user1_id, user2_id)`; the `user1_id < user2_id` canonical ordering is a
  real `CHECK` constraint (`ck_matches_user_order`, `app/models/match.py`), not just a comment.
- **`messages`** — the only soft-deleted entity (`deleted_at`); `read_at` for receipts.
- **`blocks`**, **`reports`** (reason enum; both `message_id` and `reported_user_id` are `SET NULL`, so
  deleting a message or the reported user leaves the report row intact instead of destroying it).
- **`refresh_tokens`**, **`password_reset_tokens`**, **`push_tokens`** — all store tokens in plaintext.

All datetimes are `DateTime(timezone=True)` with Python-side defaults and **no `server_default`**, so
raw-SQL inserts violate NOT NULL and timestamps carry app-host clock skew. Under SQLite (all tests)
they read back naive.

## Storage and deploy

Railway via `railpack.json` (`deploy.startCommand` → `scripts/startup.sh`, which now only execs
`uvicorn`) plus `railway.json` (`deploy.preDeployCommand` → `scripts/predeploy.sh`: `alembic upgrade
head` → seed unless `SKIP_SEED=true`). This split (GAPS #56) exists because a start command runs once
*per replica* — with more than one, migrations raced and the seed could partially collide on
`users.email` — while Railway's pre-deploy command runs exactly once per deploy, in its own ephemeral
container, before any replica starts. `railway.json` also sets `deploy.healthcheckPath` to `/health`
(GAPS #54). **The worker and Beat are not started here** and must be separate services — and as of GAPS
#55's queue split, a *third* service is required: a worker consuming the `bot_response` queue, alongside
one narrowed to the default `celery` queue. See [RUNBOOK.md](RUNBOOK.md#deploy-railway) for the exact
commands. `docker-compose.yml` is local-dev only (Postgres on 5433, Redis on 6379) and defines no app
service.

Avatars go to Cloudflare R2 when all five `R2_*` vars are set; otherwise to `static/avatars/`, which
Railway wipes on redeploy.
