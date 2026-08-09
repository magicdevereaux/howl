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
Check the worker is running first — it's the usual answer. Then check `avatar_status_updated_at`; the
clients treat >2 minutes as stale. `ANTHROPIC_API_KEY` failures retry 3× then mark `failed`; a JSON
parse failure does **not** retry and fails immediately.

**Avatars are all emoji placeholders**
Either `OPENAI_API_KEY` is unset (intended degraded mode) or DALL·E failed — the task marks the avatar
`ready` anyway. All 1000 seeded bots are placeholders by design.

**Avatars 404 after a deploy**
The `R2_*` vars aren't set, so images went to ephemeral `static/avatars/`. There is no repair path;
affected users must regenerate.

**Real-time chat works for some users, not others**
More than one web replica is running. `ConnectionManager` is an in-process dict — a sender and
recipient on different processes never see each other's events. Scale to one replica until Redis
pub/sub fan-out exists.

**Nobody receives password reset or verification emails**
There is no email provider. `app/services/email.py` prints to stdout. Reset tokens are in the log
stream — treat those logs as secrets.

**Bots stopped replying**
Beat isn't running, or a batch is failing repeatedly: a truncated or malformed Claude response discards
all 10 conversations in the batch and the same batch is retried on the next tick, forever, at cost.
Grep the worker log for `warning` from `bot_response`.

**Login brute-force protection isn't working**
It fails open on any Redis error by design. Also: `/api/mobile/auth/login` has no rate limiting at all,
and the IP bucket trusts a client-supplied `X-Forwarded-For`.

**A 500 on `POST /api/auth/refresh`**
The user was deleted but the refresh row survived; `AuthOut` validation fails on `None`. Should be a
401.

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
