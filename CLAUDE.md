# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What Howl is

A dating app where your profile picture is an AI-generated **spirit animal avatar**. You write a bio;
Claude reads it, picks your animal, writes your personality traits and an image prompt; DALL·E 3 renders
the portrait. You swipe on other people's spirit animals and chat over WebSockets.

The avatar pipeline is the product differentiator. Treat it as the critical path.

## Repo layout

| Path | What it is |
|---|---|
| `app/` | FastAPI backend — the source of truth for all business rules |
| `frontend/` | React 18 + Vite web client (cookie auth). **The more feature-complete client.** |
| `mobile/` | Expo SDK 53 + expo-router React Native client (bearer-token auth) |
| `alembic/versions/` | 26 hand-written migrations, single linear head `s0m1n2o3p4q5` |
| `tests/` | 539 pytest tests (90% coverage). Client tests live in `frontend/src` and `mobile/src` |
| `docs/` | [ARCHITECTURE.md](docs/ARCHITECTURE.md), [RUNBOOK.md](docs/RUNBOOK.md), [GAPS.md](docs/GAPS.md), [decisions/ADR.md](docs/decisions/ADR.md) |
| `scripts/seed_demo_users.py` | Seeds 1000 bot users; runs on every prod deploy |

## Commands

```bash
# Setup (Git Bash on Windows)
source .venv/Scripts/activate        # .venv is the real venv; env/ is dead, ignore it
pip install -r requirements.txt      # NOT `pip install -e .` — pyproject deps are stale
docker compose up -d                 # postgres on :5433, redis on :6379
alembic upgrade head

# Run — needs FOUR processes, not three
python -m uvicorn app.main:app --port 8001 --reload
python -m celery -A app.celery_app worker --loglevel=info --pool=solo
python -m celery -A app.celery_app beat --loglevel=info   # bot replies; README omits this
cd frontend && npm run dev           # :3000, proxies /api and /avatars to :8001

# Mobile (see mobile/CLAUDE.md)
cd mobile && npx expo start

# Tests / quality
pytest                                        # needs a .env to exist — config has required fields
pytest tests/test_chat.py -v
pytest --cov=app --cov-report=term-missing
ruff check app tests scripts                  # what CI runs
mypy app                                       # strict=true, advisory in CI

# Client tests (both have real suites now; CI runs them)
cd frontend && npm test        # vitest
cd frontend && npm run lint    # eslint 9 flat config
cd mobile   && npm test        # jest-expo
cd mobile   && npm run lint
cd mobile   && npx tsc --noEmit   # regenerate route types first: npx expo start

# Migrations
alembic revision -m "add thing"      # write by hand; see the autogenerate warning below
alembic upgrade head
```

## Architecture in one paragraph

FastAPI serves ten routers under `/api/*` (`app/main.py:60-69`). Auth resolves an `access_token`
cookie first, then an `Authorization: Bearer` header, in a single dependency
(`app/dependencies.py:14-19`) — that unification is deliberate and correct. Long-running work goes to
Celery over Redis: avatar generation, demo auto-match, message/match notifications, and a Beat job that
wakes every 15 minutes to let bot users reply. Postgres holds nine tables with FK `ON DELETE CASCADE`
doing all the relational cleanup — there is **not one `relationship()` in the codebase**, every join is
written by hand in the API layer. Full detail in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Conventions that are load-bearing

- **No ORM relationships.** Don't add one casually; the delete semantics currently depend entirely on
  DB-level cascades, and tests only match production because conftest enables `PRAGMA foreign_keys=ON`
  (`tests/conftest.py:51-55`).
- **Narrow response schemas per view.** `DiscoverUserOut`, `MatchedProfileOut`, `AvatarStatusOut` each
  expose a deliberate subset. `UserOut` is the wide one and contains `email` — never return it on an
  unauthenticated route. (`GET /api/profile/{user_id}` currently does; see GAPS.md #1.)
- **`SwipeDirection.pass_` maps to the DB value `pass`** via `values_callable` (`app/models/swipe.py:29`).
  `User.avatar_status` does *not* use `values_callable` — if you add an enum member whose name differs
  from its value there, it will write the wrong string.
- **All timestamps are `DateTime(timezone=True)` with Python-side defaults and no `server_default`.**
  On SQLite (all tests) they come back naive. Compare with
  `dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt` — see `app/api/mobile_auth.py:124-126`.
- **Rate limiting fails open.** `app/services/rate_limit.py:41-42` swallows Redis errors by design.
  Don't "fix" it into failing closed without deciding that tradeoff explicitly.
- Errors on the mobile client are values, not exceptions: `api()` returns
  `{ok:true,data} | {ok:false,error,status}` (`mobile/src/api/client.ts:8`). Always check `.ok`.

## Gotchas that will bite you

1. **Write migrations by hand anyway.** The four model/migration drifts that made
   `--autogenerate` propose dropping real indexes are fixed, and autogenerate now emits an empty
   migration against a clean head — but `env.py` still has no naming convention, so generated
   constraint names won't match the existing hand-written ones. Follow the existing
   `sa.ForeignKeyConstraint`/`sa.PrimaryKeyConstraint` style. Use autogenerate as a *diff check*
   ("is my model in sync?"), not as a generator.
2. **Migration filenames don't sort in dependency order.** `a2b3c4d5e6f7` is the 8th migration, not the
   2nd. Trust `down_revision`, never `ls`.
3. **Auth logic lives in `app/services/auth_service.py`, not in the routers.** `app/api/auth.py` and
   `app/api/mobile_auth.py` used to be near-duplicates that had drifted; they are now thin
   credential-delivery shells (web sets a cookie, mobile returns a bearer token) over one shared
   service. Put changes to registration, login, token issuance or TTLs in the service. Don't
   reintroduce logic into either router.
4. **Email only sends if a provider is configured.** `app/services/email.py` has three backends and
   `EMAIL_BACKEND=auto` picks `resend` (needs `RESEND_API_KEY`), else `smtp` (needs `SMTP_HOST`), else
   `console` — which `print()`s the link, so an unconfigured production deployment puts reset and
   verification tokens in the Railway log stream. Sends are **synchronous and bounded**
   (`EMAIL_TIMEOUT_SECONDS`), not queued, because a worker that isn't running is gotcha #5 — and they
   never raise into the request, matching every other outbound dependency here.
5. **Celery worker and Beat are not started by `scripts/startup.sh`.** In production they must be
   separate Railway services, and since queue routing landed the worker needs
   `-Q celery,bot_response` (or a second worker for `bot_response`) or bot replies stop silently.
   If avatars are stuck `pending` in prod, this is why.
6. **Avatars written locally are ephemeral.** Without the `R2_*` env vars, `static/avatars/` is wiped on
   every redeploy.
7. **`task_acks_late=True`, so any killed task re-runs from the top.** `generate_avatar` is guarded by
   a Redis lock so it won't pay twice for an image, but notifications have no dedup key — a push or
   email can be delivered twice. That's a deliberate trade-off (a duplicate banner is cheap, a dropped
   notification is invisible); don't "fix" it without deciding the cost.
8. **Chat fan-out is Redis pub/sub and fails OPEN to local-only delivery.** `ConnectionManager` owns
   local sockets; `app/services/pubsub.py` carries events between replicas. If Redis is down, delivery
   silently degrades to single-replica behaviour by design. Messages commit to Postgres *before* they
   are broadcast, so the socket is the optimistic layer — never make it the source of truth.

## Testing

`tests/conftest.py` gives you `client`, `db`, `test_user`, and `auth_headers` (cookie-based, not
bearer). Anthropic, OpenAI and email are **not** faked centrally — each test patches the call site it
needs. Follow the existing per-file patterns rather than inventing a new mocking layer.

**Two harness details that will waste your time if you don't know them:**

- **conftest disables pysqlite's implicit `BEGIN`** and emits `BEGIN` itself. Without that, SQLite
  issues `SAVEPOINT` outside any transaction and it effectively autocommits — so work inside
  `begin_nested()` *survives a `rollback()`*. Code that recovers from an `IntegrityError` via a
  savepoint (see `app/api/swipes.py`) is correct on Postgres and silently untestable without it.
- **Redis *is* real here and leaks across tests and across runs**, because the keys are built from ids
  that repeat. Autouse fixtures neutralise the login limiter, the chat send limiter and `ChatPubSub` —
  that last one matters because its supervised reader task otherwise holds each test's event loop open
  and **hangs the whole run with no output**. `tests/test_chat_pubsub.py` opts out via a `real_pubsub`
  marker, since there the fan-out is what's under test.

Untested surfaces to be careful in: the **R2 upload path** in
`app/services/image_generation.py:53-113` — the *production* avatar persistence path, still only ever
exercised via its local-filesystem fallback (note `boto3` and `openai` aren't even installed in `.venv`;
both are lazily imported behind `None` guards, which is why nothing fails loudly) — and
`scripts/seed_demo_users.py`, 375 lines that run on every production deploy.

## Before you commit

- Run `pytest` and `ruff check app tests`. There is no CI — nothing else will catch you.
- Update `docs/ARCHITECTURE.md` if you change the request/task flow, and `docs/decisions/ADR.md` if you
  make a decision worth defending later.
- Don't commit `.coverage`, `htmlcov/`, or `.env*` (all gitignored, all currently present locally).
