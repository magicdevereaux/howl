# Handoff — GAPS.md fan-out session

**Date:** 2026-08-06. **Baseline at session start:** `379e6d4` on `main`, **413 tests passing**, suite
runtime ~3m50s.

This file exists so a fresh session can pick up mid-flight. Delete it once the fan-out is merged and
`docs/GAPS.md` reflects reality.

## What is happening

Eight parallel agents, each in its own git worktree under `.claude/worktrees/`, each on a branch named
`worktree-agent-<id>`. File ownership is disjoint by design — that is what makes the merge clean. No
agent may edit `docs/GAPS.md`; the orchestrator owns it and the merge.

| Agent branch suffix | GAPS items | Owns |
|---|---|---|
| `af501333c9ead3e7d` | #20 indexes, #21 alembic drift, #22 server_defaults, #23 constraints, #24 report cascade | `alembic/`, `app/models/`, `app/db.py`, `app/schemas/user.py` |
| `ae0e08715fe99fe3c` | #13 mobile network errors, #34 a11y, #35 shippability | `mobile/` except `src/utils/avatar.ts` + `package.json` |
| `adb0b77b3bc740de0` | #14 swipe races, #19 (blocks half) | `app/api/swipes.py`, `app/api/blocks.py` |
| `acb8378e9a3ac8ada` | #16 notification retries + Expo ticket parsing | `app/tasks/notify.py`, `app/services/push_notifications.py` |
| `a8507a6340a4f3f28` | #18 auth consolidation, #25 verification, #26 auth rate limits | `app/api/auth.py`, `app/api/mobile_auth.py`, `app/services/rate_limit.py`, `app/dependencies.py` |
| `a5425f6c66cc50b17` | #17 Redis pub/sub chat, #26 chat portion | `app/api/chat.py`, new `app/services/pubsub.py`, `ARCHITECTURE.md`, `ADR.md` |
| `a1e0f6a2dee03c0d2` | #28 pyproject, #31 coverage gate, #32 client drift, #36 docs, #37 litter | `pyproject.toml`, `README.md`, `LICENSE`, `frontend/src/utils.js`, `frontend/src/App.jsx`, `mobile/src/utils/avatar.ts` |
| `a1c6076c3a028ab73` | #29 client tests + lint | `frontend/package.json`, `mobile/package.json`, new test/config files, `.github/workflows/ci.yml` |

Orchestrator keeps for itself: **#19 (bot_response half)** in `app/tasks/bot_response.py` — no agent owns
that file.

## Deliberately NOT in scope this session

- **#3 — email provider.** The only remaining P0. Blocked on Nathan choosing a provider (Resend /
  Postmark / SES). Until then password reset is non-functional and reset tokens print to the Railway log
  stream. Nothing in this fan-out touches `app/services/email.py`.
- **#33 — web client is one 1073-line component.** A 45-`useState` rewrite with routing is a session of
  its own, and it would collide with every frontend change above.
- **#35 partial — `extra.eas.projectId`.** Needs a real EAS account; the mobile agent was told to skip it
  and report what Nathan must run manually.
- **#25 enforcement.** The `require_verified_email` dependency gets built and tested, but attaching it
  broadly is a product decision (it would lock out the 1000 seeded bots and every existing account). The
  auth agent reports a recommendation rather than deciding it.

## If the session dies mid-flight

1. `git worktree list` shows every agent worktree; `git log main..worktree-agent-<id>` shows what that
   agent committed. Unmerged work is not lost — it is on the branch.
2. Merge order matters in one place: the schema agent (`af501333…`) is the only one creating alembic
   migrations, so its branch should land before anything that depends on a new index or constraint.
   Notably the swipe-race agent was told it may NOT add migrations and would report any constraint it
   needs — check its report and add that migration after merging.
3. Re-run the full suite after each merge: `pytest -q`. Expect ≥413 passing.
4. Worktrees are auto-cleaned only if unchanged. Clean up merged ones with
   `git worktree remove <path>` then `git branch -d <branch>`.

## What happened: all eight agents died on the session limit

Every agent was terminated mid-task by `You've hit your session limit` (reset 1:40am 2026-08-07).
**No work was lost** — each left a complete, *uncommitted* working tree in its worktree. Recover with:

```bash
git -C .claude/worktrees/agent-<id> status --porcelain   # what it left
git -C .claude/worktrees/agent-<id> diff                 # the actual work
```

Lesson recorded for next time: these were all `general-purpose` agents on the default (Opus) model.
Most of the work was mechanical and should have run on Sonnet. Reserve Opus for agents doing genuine
design work. See [[feedback-fanout-model-choice]] in memory.

Because the work is uncommitted AND unverified — each agent stopped mid-step, some mid-test-writing —
it is being integrated into `main` **one branch at a time, verified before it lands**. Nothing goes in
on trust.

## Integration status

Orchestrator's own work landed first, independently of the fan-out:

| Item | Commit | Status |
|---|---|---|
| #19 (bot_response half) — N+1 storm | `5698a72` | ✅ landed, 38 tests pass. Guard proves old code went 9→47 SELECTs as bots went 2→12. |

Fan-out branches, in integration order (most-complete and lowest-risk first):

| # | Agent id | Items | Left off at | Landed? |
|---|---|---|---|---|
| 1 | `adb0b77b3bc740de0` | #14 swipe races, #19 blocks | "add a query-count test and run everything" | |
| 2 | `acb8378e9a3ac8ada` | #16 notify retries | "now the service tests" | |
| 3 | `a1e0f6a2dee03c0d2` | #28/#31/#32/#36/#37 | "testing the build with requirements-driven pyproject" | |
| 4 | `a1c6076c3a028ab73` | #29 client tests | "now let me write the frontend config" | |
| 5 | `ae0e08715fe99fe3c` | #13 mobile, #34 a11y | "now push.ts and the WebSocket hook" | |
| 6 | `a5425f6c66cc50b17` | #17 chat pub/sub | "now the WS handler + send rate limit" | |
| 7 | `af501333c9ead3e7d` | #20/#21/#22/#23/#24 schema | "now fix the broken downgrades" — 5 migrations written | |
| 8 | `a8507a6340a4f3f28` | #18/#25/#26 auth | mid-writing rate-limit tests | |

The schema branch (#7) is deliberately late despite being nearly done: it writes **five new
migrations** and needs Postgres verification, and the swipe branch (#1) may need a constraint from it.
The auth branch (#8) is last because it is the largest refactor and touches `tests/conftest.py`.

Cleanup once landed: `git worktree remove <path> && git branch -D worktree-agent-<id>`.
