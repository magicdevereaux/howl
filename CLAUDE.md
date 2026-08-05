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
| `alembic/versions/` | 21 hand-written migrations, single linear head `n5h6i7j8k9l0` |
| `tests/` | 372 pytest tests, backend only |
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
ruff check app tests                          # configured in pyproject, nothing runs it automatically
mypy app                                       # strict=true, currently unenforced

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

1. **`alembic revision --autogenerate` produces wrong output here.** Models and migrations have four
   known drifts (a missing `index=True` on `users.is_bot`, and unique-constraint-vs-unique-index
   mismatches on all four token tables). Autogenerate will propose dropping real indexes. Write
   migrations by hand and follow the existing `sa.ForeignKeyConstraint`/`sa.PrimaryKeyConstraint` style.
2. **Migration filenames don't sort in dependency order.** `a2b3c4d5e6f7` is the 8th migration, not the
   2nd. Trust `down_revision`, never `ls`.
3. **`app/api/auth.py` and `app/api/mobile_auth.py` are near-duplicates that have drifted.** Any change
   to registration, login, or token issuance must be made in both — and `mobile_auth.py` currently has
   no rate limiting and a wrong verification-token TTL. Prefer consolidating over copying again.
4. **Emails are `print()` statements.** `app/services/email.py` has no provider wired. Password-reset
   and verification tokens go to stdout, which in production means the Railway log stream.
5. **Celery worker and Beat are not started by `scripts/startup.sh`.** In production they must be
   separate Railway services. If avatars are stuck `pending` in prod, this is why.
6. **Avatars written locally are ephemeral.** Without the `R2_*` env vars, `static/avatars/` is wiped on
   every redeploy.
7. **`generate_avatar` is not idempotent and `task_acks_late=True`.** A worker killed mid-task re-runs
   the whole thing, including a second paid DALL·E call.
8. **`ConnectionManager` is an in-process dict** (`app/api/chat.py:36-38`). Any second web replica
   silently breaks real-time chat delivery.

## Testing

`tests/conftest.py` gives you `client`, `db`, `test_user`, and `auth_headers` (cookie-based, not
bearer). Redis, Anthropic, OpenAI, email and push are **not** faked centrally — each test patches the
call site it needs. Follow the existing per-file patterns rather than inventing a new mocking layer.

Untested surfaces to be careful in: `app/api/mobile_auth.py` (zero tests, and it is the entire auth
surface the shipped mobile app uses), the R2 upload path in `app/services/image_generation.py:53-113`,
`app/services/push_notifications.py`, and both client apps.

## Before you commit

- Run `pytest` and `ruff check app tests`. There is no CI — nothing else will catch you.
- Update `docs/ARCHITECTURE.md` if you change the request/task flow, and `docs/decisions/ADR.md` if you
  make a decision worth defending later.
- Don't commit `.coverage`, `htmlcov/`, or `.env*` (all gitignored, all currently present locally).
