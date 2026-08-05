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
   The endpoint sets `avatar_status = pending` and enqueues `generate_avatar.delay(user_id)`.
2. `app/tasks/avatar.py:40` calls **Claude Haiku** (`claude-haiku-4-5-20251001`, `avatar.py:67`) with
   the user's bio and asks for JSON: `{animal, personality_traits, avatar_description, image_prompt}`.
   The animal list in the prompt is suggestive, not enumerated — the value is effectively free text,
   lowercased at `avatar.py:92`.
3. `image_prompt` is handed to `generate_avatar_image()` (`app/services/image_generation.py:167`),
   which calls **OpenAI DALL·E 3** at 1024×1024, standard quality.
4. The resulting temporary URL is downloaded with a 30s httpx client and persisted:
   `_upload_to_r2()` first, falling back to `static/avatars/<uuid4>.png` (`image_generation.py:183`).
   R2 returns a full HTTPS URL; local returns `/avatars/<file>`. Both shapes appear in `avatar_url`.
5. The row is written with `avatar_status = ready`.

**Failure behavior:** only `anthropic.APIError` triggers a retry (3×, 60s apart, `avatar.py:130-136`).
JSON/Key/Value errors fail permanently. If the *image* step fails, the avatar is still marked ready and
the clients render an emoji placeholder from their animal→emoji map. If `OPENAI_API_KEY` is unset, every
avatar is a placeholder — this is the intended degraded mode.

**Quota:** non-premium users get 1 regeneration per 30 days. The counter is shared between
`POST /api/avatar/regenerate` (which 429s) and a bio edit via `PATCH /api/profile/me` (which instead
silently sets `profile_needs_regen = true`). Premium users have **no cap at all** on a paid endpoint.

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
- `is_email_verified` is written at `app/api/auth.py:127` and **read nowhere** — verification is
  currently cosmetic.

## Routers

All mounted in `app/main.py:60-69`, each carrying its own prefix.

| Router | Prefix | Endpoints |
|---|---|---|
| `auth.py` | `/api/auth` | register, verify-email, login, me, refresh, logout, forgot-password, reset-password |
| `mobile_auth.py` | `/api/mobile/auth` | register, login, refresh, logout (tokens in body) |
| `profile.py` | `/api/profile` | GET/PATCH/DELETE `me`, GET `{user_id}` ⚠ unauthenticated |
| `avatar.py` | `/api/avatar` | status, regenerate |
| `users.py` | `/api/users` | discover, matches |
| `swipes.py` | `/api/swipes` | POST swipe, DELETE last (undo) |
| `chat.py` | `/api/matches` | WS `{id}/ws`, messages GET/POST/DELETE, unread-count, DELETE match |
| `blocks.py` | `/api/blocks` | POST, DELETE `{id}`, GET |
| `reports.py` | `/api/reports` | POST |
| `push_tokens.py` | `/api/push-tokens` | POST, DELETE |

Plus `GET /health` and a `StaticFiles` mount at `/avatars`.

## Real-time chat

- WebSocket at `/api/matches/{match_id}/ws`, authenticated by the `access_token` cookie **or**
  `?token=<jwt>` (mobile). Close codes: `4001` bad auth, `4003` not a member of this match.
- Inbound: only `{"type":"typing"}` is handled; everything else is ignored. Messages are **sent over
  REST**, not the socket.
- Outbound: `new_message`, `message_deleted`, `typing`. `is_mine` is computed per recipient at
  broadcast time (`app/api/chat.py:74`).
- The connection registry is an **in-process dict** (`chat.py:36-38`). This is single-replica-only by
  construction. Horizontal scaling requires a Redis pub/sub fan-out first.
- Send rate limit is 10 messages/60s, counted with a DB `COUNT` per request (`chat.py:321-332`) rather
  than via the Redis limiter used by login.

## Background work

`app/celery_app.py` — Redis is both broker and result backend. `task_acks_late=True`,
`worker_prefetch_multiplier=1`, JSON serialization, UTC. **No queue routing, no time limits, no
`result_expires`.** One Beat entry: `process_bot_responses` every 900s.

| Task | Trigger | Retries |
|---|---|---|
| `generate_avatar` | profile save, avatar regenerate | 3× on `anthropic.APIError` only |
| `auto_match_demo_user` | a real user likes a `demo*` account; 90% like back | 3× generic |
| `process_bot_responses` | Beat, every 15 min | **none** |
| `notify_new_message` | message send; skipped if recipient active in last 5 min | **none** |
| `notify_new_match` | mutual like | **none** |

## The bot population

`scripts/seed_demo_users.py` creates **1000 bot users** (`demo1@howl.app` …, `random.seed(42)`, so it's
deterministic) and runs on every production deploy via `scripts/startup.sh`. Bots are ordinary `users`
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

Nine tables, all cleanup via FK `ON DELETE CASCADE`. No `relationship()` anywhere — every join is
hand-written in the API layer.

- **`users`** (32 columns) — auth, profile, preferences, and the spirit-animal cluster: `animal`,
  `personality_traits` (JSON), `avatar_description`, `avatar_url`, `avatar_status` (enum
  pending/ready/failed), `avatar_status_updated_at`, `avatar_regenerations_this_month`,
  `regenerations_reset_at`, `profile_needs_regen`, plus `is_bot`/`archetype`.
- **`swipes`** — unique on `(user_id, target_user_id)`; `direction` enum where the Python member
  `pass_` maps to the DB value `pass`.
- **`matches`** — unique on `(user1_id, user2_id)`; the `user1_id < user2_id` canonical ordering is a
  **comment, not a CHECK constraint**.
- **`messages`** — the only soft-deleted entity (`deleted_at`); `read_at` for receipts.
- **`blocks`**, **`reports`** (reason enum; `message_id` is `SET NULL` to survive message deletion,
  but `reported_user_id` is `CASCADE`, so deleting the reported user destroys the report).
- **`refresh_tokens`**, **`password_reset_tokens`**, **`push_tokens`** — all store tokens in plaintext.

All datetimes are `DateTime(timezone=True)` with Python-side defaults and **no `server_default`**, so
raw-SQL inserts violate NOT NULL and timestamps carry app-host clock skew. Under SQLite (all tests)
they read back naive.

## Storage and deploy

Railway via `railpack.json` → `scripts/startup.sh`: `alembic upgrade head` → seed (unless
`SKIP_SEED=true`) → `uvicorn`. **The worker and Beat are not started here** and must be separate
services. `docker-compose.yml` is local-dev only (Postgres on 5433, Redis on 6379) and defines no app
service.

Avatars go to Cloudflare R2 when all five `R2_*` vars are set; otherwise to `static/avatars/`, which
Railway wipes on redeploy.
