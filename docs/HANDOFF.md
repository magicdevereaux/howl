# Handoff — GAPS.md fan-out session

**Date:** 2026-08-06/07. **Baseline at session start:** `379e6d4` on `main`, **413 tests passing**,
suite runtime ~3m50s. **Now: 497 passing.**

This file exists so a fresh session can pick up mid-flight. Delete it once the fan-out is merged and
`docs/GAPS.md` reflects reality.

## What happened

Eight parallel agents, each in its own git worktree under `.claude/worktrees/`, each on a branch named
`worktree-agent-<id>`, with **disjoint file ownership** — that constraint is what made the merge
tractable. All eight were then terminated mid-task by `You've hit your session limit`.

**No work was lost.** Each left a complete but *uncommitted* working tree. Recover with:

```bash
git -C .claude/worktrees/agent-<id> status --porcelain   # what it left
git -C .claude/worktrees/agent-<id> diff                 # the actual work
```

Because that work is both uncommitted and unverified — each agent stopped mid-step, several
mid-test-writing — it is being integrated into `main` **one branch at a time, verified before it
lands**. Nothing goes in on trust. Several agents left genuinely broken or incomplete pieces that only
showed up under test.

Lesson recorded: these were all `general-purpose` agents on the default (Opus) model. Most of the work
was mechanical and should have run on Sonnet. See `feedback-fanout-model-choice` in memory.

## Integration status

| # | Agent id | GAPS items | Landed | Commit |
|---|---|---|---|---|
| — | (orchestrator) | #19 bot_response N+1 | ✅ | `5698a72` |
| 1 | `adb0b77b3bc740de0` | #14 swipe races, #19 blocks | ✅ | `a7e7ef3` |
| 2 | `acb8378e9a3ac8ada` | #16 notify retries | ✅ | `9933488` |
| 3 | `af501333c9ead3e7d` | #20/#21/#22/#23/#24 schema | ✅ | `026ef4b` |
| 4 | `a5425f6c66cc50b17` | #17 chat pub/sub, #26 chat | ✅ | `b2a36f8` |
| 5 | `a8507a6340a4f3f28` | #18/#25/#26 auth | | |
| 6 | `ae0e08715fe99fe3c` | #13 mobile, #34 a11y, #35 | | |
| 7 | `a1e0f6a2dee03c0d2` | #28/#31/#32/#36/#37 hygiene | | |
| 8 | `a1c6076c3a028ab73` | #29 client tests + lint | | |

Remaining order: **auth (5)** is the largest refactor and touches `tests/conftest.py`, which the
integration has already modified three times — expect to merge by hand, not by patch. **7 and 8** are
low-risk and mostly independent of the backend. **6** needs `npx tsc --noEmit` from `mobile/`, not
pytest.

## Things learned the hard way (read before touching tests)

- **The pysqlite savepoint trap.** `tests/conftest.py` now disables pysqlite's implicit `BEGIN` and
  emits `BEGIN` itself (SQLAlchemy's documented workaround). Without it, `SAVEPOINT`s are issued
  outside any transaction and effectively autocommit, so work inside `begin_nested()` *survived a
  rollback*. Any `IntegrityError`-recovery code is correct on Postgres but silently untestable without
  this. Same intent as the pre-existing `PRAGMA foreign_keys=ON`.
- **Real Redis leaks state across tests and across runs.** Three autouse fixtures now exist for this:
  the login limiter (`2136073`), the chat send limiter (keyed by `(user_id, match_id)`, both of which
  repeat), and `ChatPubSub` — whose supervised reader task keeps each test's event loop from closing
  and hangs the whole run. `test_chat_pubsub.py` opts out of the last one via a `real_pubsub` marker,
  because there the fan-out *is* the thing under test.
- **Asyncio objects have loop affinity.** `ChatPubSub` cached redis clients, a task and a lock without
  tracking which loop made them, so reuse across loops raised "Event loop is closed". Now loop-aware.
- **Two GAPS claims were wrong,** not merely unfixed:
  - #23's `(user_id, token)` push-token constraint should **not** be added. The global uniqueness is
    deliberate (one device, one signed-in account) and a pair constraint would let two accounts share a
    device's pushes. `app/api/push_tokens.py` already reassigns. Pinned with a test.
  - `test_notify.py` was building a self-match to get a `match_id`, which the new
    `ck_matches_user_order` correctly rejects. That fixture data was always invalid.
- **#21 is verified, not assumed.** `alembic revision --autogenerate` now emits an empty migration and
  `downgrade base` → `upgrade head` completes on PostgreSQL. Checked against a throwaway database
  (`howl_migration_test`, since dropped) — never the dev DB.
- **Write docs with the Write tool, not Python.** `pathlib.write_text` uses cp1252 on this machine and
  truncated this file to zero bytes mid-write when it hit an emoji.

## Deliberately NOT in scope

- **#3 — email provider.** The only remaining P0. Blocked on Nathan choosing one (Resend / Postmark /
  SES). Until then password reset is non-functional and reset tokens print to the Railway log stream.
- **#25 enforcement.** The `require_verified_email` dependency gets built and tested, but attaching it
  broadly would lock out the 1000 seeded bots and every existing account. Product decision, not a fix.
- **#33 — the 1073-line `App.jsx`.** A 45-`useState` rewrite with routing is a session of its own.
- **#35 partial — `extra.eas.projectId`.** Needs a real EAS account.
- Inside the landed schema work: `users.age` stays nullable (NOT NULL breaks existing rows and the 18+
  gate is an API decision), and no CHECK ties `avatar_status='ready'` to `avatar_url`/`animal`.

## If the session dies again

1. `git log main..worktree-agent-<id>` per branch — unmerged work is on the branch or in the worktree.
2. Re-run the full suite after each merge: `pytest -q`. Expect ≥497 passing. It takes ~3 minutes.
3. Docker must be up for the Postgres/Redis-dependent checks: `docker compose up -d` (pg on 5433).
4. Clean up merged worktrees: `git worktree remove <path> && git branch -D worktree-agent-<id>`.
