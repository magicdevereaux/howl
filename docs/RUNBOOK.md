# Runbook

Operating Howl: local setup, the processes that must be running, and how to diagnose the failures this
system actually produces.

## Local setup

```bash
source .venv/Scripts/activate          # Git Bash on Windows. env/ is a dead venv — ignore it.
pip install -r requirements.txt        # NOT `pip install -e .` (pyproject deps are incomplete)
cp .env.example .env                   # then fill in the required values below
docker compose up -d
alembic upgrade head
python -m scripts.seed_demo_users      # optional: 1000 bots to swipe on
```

`.env` must exist before anything imports `app.config` — `database_url`, `redis_url`, `secret_key`, and
`anthropic_api_key` have no defaults, so even `pytest` fails on a fresh clone without it.

Correct local values (the README's are wrong — port and password both):

```
DATABASE_URL=postgresql://howl:howl_dev@127.0.0.1:5433/howl
REDIS_URL=redis://localhost:6379/0
```

## The four processes

| Process | Command | Breaks if missing |
|---|---|---|
| API | `python -m uvicorn app.main:app --port 8001 --reload` | everything |
| Celery worker | `python -m celery -A app.celery_app worker --loglevel=info --pool=solo -Q celery,bot_response` | avatars stuck `pending`, no notifications, no auto-match, bots never reply |
| Celery **beat** | `python -m celery -A app.celery_app beat --loglevel=info` | bots never reply |
| Web client | `cd frontend && npm run dev` | — |

`--pool=solo` is required on Windows. The worker must list both queues explicitly (`-Q
celery,bot_response`) — since GAPS #55 routed `process_bot_responses` onto a `bot_response` queue, a
worker started without `-Q` only consumes the default `celery` queue and will silently never run bot
replies. In production the two queues are split across separate services instead; see below.

## Environment variables

| Var | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | ✅ | Postgres DSN |
| `REDIS_URL` | ✅ | Celery broker/backend **and** login rate-limit counters |
| `SECRET_KEY` | ✅ | JWT signing |
| `ANTHROPIC_API_KEY` | ✅ | Claude Haiku — animal, traits, image prompt |
| `OPENAI_API_KEY` | — | DALL·E 3. Unset ⇒ every avatar is an emoji placeholder |
| `ALLOWED_ORIGINS` | ✅ in prod | Comma-separated CORS allowlist. **Missing from `.env.example`.** Defaults to `""`, which blocks every browser client. |
| `FRONTEND_URL` | ✅ in prod | Base URL in reset/verification email links |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | — | default 30 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | — | default 30 (`.env.example` says 7; it's wrong). Mobile ignores this and hardcodes 30. |
| `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `R2_PUBLIC_URL` | ✅ in prod | Avatar persistence. All five or none. Without them avatars vanish on redeploy. |
| `SENTRY_DSN` | — | error + perf monitoring, 20% trace sample |
| `ENVIRONMENT` | — | Sentry tag, echoed by `/health`. Default `production`. |
| `DEBUG` | — | Enables `/docs` + `/redoc`, adds localhost CORS, makes cookies insecure. Never true in prod. |
| `SKIP_SEED` | — | Set `true` to skip the 1000-bot seed on deploy |
| `TRUSTED_PROXY_COUNT` | — | Number of trusted reverse proxies in front of the app for `X-Forwarded-For` parsing (default `1`, Railway's own edge). Increment if you put another proxy — e.g. Cloudflare — in front of Railway, or the login rate limiter's IP bucket will key on that proxy's shared egress address and can lock out the whole app. |
| `PORT` | injected | Used by `startup.sh:12` |

## Deploy (Railway)

`railpack.json` pins Python 3.11 and its `deploy.startCommand` runs `bash scripts/startup.sh`, which
now only execs uvicorn. Migrations and the demo-user seed used to run there too, once per replica — with
more than one replica that raced (Alembic takes no advisory lock; the seed can collide on `users.email`)
— so they moved to `scripts/predeploy.sh`, wired up as Railway's **pre-deploy command** in `railway.json`
(`deploy.preDeployCommand`). Railway runs that in its own ephemeral container, once per deploy, between
the build finishing and any replica starting — so it is unaffected by `numReplicas`. `railway.json` also
sets `deploy.healthcheckPath` to `/health` (GAPS #54): Railway won't route traffic to a replica, or will
roll a bad deploy back, based on the dependency-aware status that endpoint now reports. Set
`SKIP_SEED=true` to skip the seed step; a seed failure is logged as a warning but does not fail the
pre-deploy step, since it's an additive, cosmetic dataset (GAPS #39).

**The worker and Beat must be separate Railway services** pointed at the same repo with the celery
commands below. Nothing in the repo creates them. As of GAPS #55, `app/celery_app.py` routes
`process_bot_responses` onto its own `bot_response` queue so it can no longer queue behind
`generate_avatar`/notify tasks — but that only takes effect once a worker actually consumes that queue.
**A third Railway service is now required**: a worker started with `-Q bot_response`, alongside the
existing worker (narrow it to `-Q celery` so it stops competing for bot-response work) and Beat.

```bash
# Worker A — everything except bot replies (avatar generation is the critical path)
celery -A app.celery_app worker --loglevel=info --pool=solo -Q celery

# Worker B — bot replies only, on its own queue so a 15-minute batch can't
# starve avatar generation or push notifications
celery -A app.celery_app worker --loglevel=info --pool=solo -Q bot_response

# Beat — ticks process_bot_responses onto the bot_response queue every 15 minutes
celery -A app.celery_app beat --loglevel=info
```

## Diagnosing the failures this system produces

**Avatars stuck on `pending`**
Check the worker is running first — it's the usual answer. As of GAPS #55, specifically check the
worker consuming the default `celery` queue (`generate_avatar` no longer shares a queue with
`process_bot_responses`) — a deploy that only brought up the `bot_response` worker service will show
this exact symptom. Then check `avatar_status_updated_at`; the clients treat >2 minutes as stale.
`ANTHROPIC_API_KEY` failures retry 3× then mark `failed`; a JSON parse or shape-validation failure
(GAPS #38) does **not** retry and fails immediately.

**Avatars are all emoji placeholders**
Either `OPENAI_API_KEY` is unset (intended degraded mode) or DALL·E failed — the task marks the avatar
`ready` anyway. All 1000 seeded bots are placeholders by design.

**Avatars 404 after a deploy**
The `R2_*` vars aren't set, so images went to ephemeral `static/avatars/`. There is no repair path;
affected users must regenerate.

**Real-time chat works for some users, not others**
Multiple web replicas are no longer a reason this happens — `ChatPubSub` (`app/services/pubsub.py`)
fans events out across replicas over Redis now, so this diagnosis is retired. If it recurs, check Redis
first: pub/sub **fails open to local-only delivery** if Redis is unreachable, which reproduces exactly
this symptom (sender and recipient on different replicas stop seeing each other's events) as a
degraded-but-intentional mode, not a bug. `GET /api/matches/{id}/messages` is still the source of truth
a client can fall back to — the message itself was never lost, only the live push.

**Nobody receives password reset or verification emails**
Almost always: no provider is configured, so `EMAIL_BACKEND=auto` resolved to `console` and
`app/services/email.py` printed the link to stdout instead of sending it. Reset and verification
tokens are then sitting in the Railway log stream — **treat those logs as secrets**. Set
`RESEND_API_KEY` (or the `SMTP_*` block) and delivery starts; nothing else changes.

If a provider *is* configured, the send failed and said so: grep for `email:` at `error` level, or
look in Sentry. A send never raises into the request — the caller's account is already created and
failing the request would not un-send anything — so a broken provider looks like silence at the user
and a log line at you. The likeliest causes are an unverified sending domain (Resend returns 403 with
that in the body, which is logged verbatim) and SMTP credentials.

Note delivery is **synchronous**, not queued, and bounded by `EMAIL_TIMEOUT_SECONDS` (default 5s).
That is deliberate: a Celery worker that isn't running is the most common failure of this deployment,
and a verification email that silently never sends because nobody drained the queue is worse than one
that costs the request a moment.

A user who typo'd their address at signup is **not** stuck: `POST /api/auth/change-email` (current
password required) moves the account and re-sends. Before that endpoint existed, the only remedy was
`ENFORCE_EMAIL_VERIFICATION=false`.

**Bots stopped replying**
Beat isn't running, or the `bot_response` queue has no worker consuming it (GAPS #55 — check this
before assuming a Claude-side failure), or a batch is failing repeatedly: a truncated or malformed
Claude response discards all 10 conversations in the batch and the same batch is retried on the next
tick, forever, at cost. Grep the `bot_response`-queue worker's log for `warning` from `bot_response`.

**Login brute-force protection isn't working**
It fails open on any Redis error by design — check Redis first. `/api/mobile/auth/login` shares
`enforce_rate_limit` with the web login route via `app/services/auth_service.py`, so "mobile has no
rate limiting" is no longer a valid diagnosis. The IP bucket does **not** trust `X-Forwarded-For`
naively either — `client_ip()` reads the Nth entry from the right, where N is `TRUSTED_PROXY_COUNT`
(default 1). If it's locking out real users, the likelier cause now is a proxy-count mismatch: check
how many reverse proxies actually sit in front of Railway against `TRUSTED_PROXY_COUNT` (see above) —
too low and the parsed "client" IP is a proxy's own shared egress address, too high and it's an
attacker-controlled `X-Forwarded-For` entry that never should have been trusted.

**A 500 on `POST /api/auth/refresh` — no longer reproduces**
`rotate_access_token` (`app/services/auth_service.py:133-156`) now explicitly checks for a refresh
row whose user was deleted and raises the same 401 as a missing/revoked/expired token, rather than
letting `AuthOut` validation fail on `None`. Kept here in case it regresses: the fix is that
`user is None` must raise before constructing the response, not after.

## Database operations

```bash
alembic upgrade head
alembic downgrade -1
alembic current
alembic history
```

Two hazards, both documented in [GAPS.md](GAPS.md):

- **Do not trust `alembic revision --autogenerate`** here. Models and migrations have known drifts and
  autogenerate will propose dropping live indexes. Write migrations by hand.
- **`downgrade base` then `upgrade head` fails on Postgres** — the first migration never drops the
  `avatar_status` enum type, so the re-upgrade errors with "type already exists". Migration
  `m4g5h6i7j8k9` is also a no-op downgrade (it's a data migration).
