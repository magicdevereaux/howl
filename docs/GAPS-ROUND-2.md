# Gaps & Improvements — round two

> **Status, 2026-08-09 (round three): every entry in this document is closed.** Both P0s (**#38**,
> **#39**) closed on 2026-08-08; **#40 through #67** closed in this pass. Each entry carries the commit
> that closed it. The findings themselves are kept, not deleted — the reasoning in an entry is usually
> *why* the fix is shaped the way it is, and a fix whose justification has been thrown away is the next
> person's mystery.
>
> Landed alongside these, and worth knowing about because they are not entries in this file:
>
> - **GAPS.md #3** — the last open P0 from round one. `app/services/email.py` now has three backends
>   (`console` / `resend` / `smtp`) chosen by `EMAIL_BACKEND=auto`. Delivery is synchronous and
>   bounded rather than queued: a Celery worker that is not running is *the* documented production
>   failure here, so mail that silently never sends because nobody drained the queue is worse than mail
>   that costs the request a moment.
> - **`POST /api/auth/change-email`** — the repair path #25's enforcement was missing. `email` was
>   editable nowhere, so a typo at signup became a permanent lockout once the 72-hour grace window
>   lapsed. Requires the current password and warns the old address.
>
> **Deliberately not done**, and worth stating so nobody assumes otherwise:
>
> - **#57's takeover half.** Format validation, a per-user cap and audit logging of reassignments all
>   landed. Proving a token belongs to the device presenting it needs signed device attestation, which
>   is a real design decision rather than a fix.
> - **#62's `/health` probe.** R2 is reported as configured-or-not; whether it is actually *reachable*
>   is only discovered on an upload, which now escalates to Sentry instead of silently falling back.
> - **Per-run Redis key prefixes in CI.** CI has a real Redis service now on a non-zero DB, and
>   GitHub's service containers are per-job, so runs cannot collide. Within a run, conftest's autouse
>   fixtures already handle it.
>
> **Three new findings, #68–#70, are appended at the end of this file** — they did not exist or were
> not visible when #38–#67 were written, and all three are open. The one worth reading first is **#70**:
> nothing enforces the WebSocket event contract across the three codebases, and it silently broke today.
>
> `main` is at **896 backend tests**, 151 web, 41 mobile; `ruff` clean, single alembic head
> `u2o3p4q5r6s7`.

A second pass over `main` at `c56f9f1`, aimed at what round one under-covered: the avatar pipeline end to
end, WebSocket concurrency and lifecycle, **authorization** as distinct from authentication, operational
reality, undocumented fail-open (and fail-*closed*) behaviour, data lifecycle, the clients as products,
and test-harness isolation. Numbering continues from GAPS.md. Nothing already in GAPS.md is repeated,
including the five partials' documented leftovers and the "Product-shaped ideas" section; where a
*closed* entry looks incompletely closed I name it (#7, #8, #15, #23 each get one).

Three findings were reproduced by running code rather than by reading it: **#38**, **#43** and the
timing in **#61**. Where I am uncertain I say so and say what would settle it.

**Headline concern: the avatar pipeline persists Claude's output into a JSON column with no shape
validation, and four response schemas declare that column as `list[str]`.** One
plausible-but-wrong Claude response — traits as objects instead of strings — permanently 500s the
affected user's login on *both* clients and 500s `GET /api/users/discover` for **every other user**,
because discover has no `LIMIT` and returns the whole ready population in one response. I reproduced
this end to end. It is the first P0 since #3, there is no server-side repair path (the user cannot log in
to press "Regenerate"), and nothing anywhere in the codebase validates the shape of a model response.

**Second concern, and the one I'd fix first because it is two lines: `scripts/seed_demo_users.py`
deletes all 1000 bot users on every production deploy, and `matches` cascades from `users`.** Every real
user's matches and entire chat history with bot accounts — which, at a 90% auto-like-back rate against a
1000-bot population, is most of what a new user has — is destroyed on each redeploy. The script calls
this "idempotent".

**Third: enqueueing a Celery task is the one Redis dependency in the request path that does not fail
open.** `POST /api/matches/{id}/messages` commits the message and then calls
`notify_new_message.delay()`; with Redis unreachable that call blocks for ~109 seconds (measured) and
raises, so the endpoint returns 500 for a message that is already in the database, and 40 concurrent
sends exhaust Starlette's sync threadpool and take down every other sync route with it.

Severity key as in GAPS.md: **P0** fix before real users, **P1** correctness/cost, **P2**
architecture/scale, **P3** hygiene.

---

## P0 — Fix before any real user touches this

### 38. ~~Unvalidated Claude output in `personality_traits` 500s one user's login and everyone's discover~~ ✅ FIXED (01e1ea4)

Fixed in two halves, because prevention alone leaves already-written rows broken:

- **Prevention** — `_ClaudeAvatarPayload` in `app/tasks/avatar.py` validates the parsed reply before
  anything is persisted. `ValidationError` subclasses `ValueError`, so a bad shape lands in the existing
  `(json.JSONDecodeError, KeyError, ValueError)` handler, marks the avatar `failed` (a state
  `POST /api/avatar/regenerate` already recovers from), and never reaches the paid DALL·E call.
- **Containment** — `app/schemas/ai_fields.py` coerces on read for rows written before that existed:
  `TraitList` and `DescriptionText`, applied to **all five** affected classes including
  `MatchedProfileOut`, which this entry did not list. Coercion drops what cannot be a string rather than
  inventing content or `str()`-ing a dict into a user-facing profile. That is what restores the repair
  path — the owner can log in again and press Regenerate.

Both halves were verified by neutralising them: pass-through coercion breaks the two reproduction tests,
and `model_construct` in place of `model_validate` breaks the seven task tests. `tests/test_ai_payload_validation.py`
records one trap worth knowing — you **cannot** test the schema coercion by re-validating a constructed
schema instance, because pydantic's `revalidate_instances` defaults to `'never'` and silently skips every
validator, so such a test passes whether or not the coercion exists.

<details><summary>Original finding</summary>

`app/tasks/avatar.py:122` persists whatever Claude put in `personality_traits` with no type check:

```python
personality_traits: list[str] = data.get("personality_traits", [])
```

The annotation is decoration — nothing enforces it. The column is `JSON`
(`app/models/user.py:53`, `Mapped[list | None]`), so any JSON value stores cleanly. Four response
schemas then declare the field as `list[str] | None`: `UserOut` (`app/schemas/user.py:50`),
`PublicProfileOut` (`:193`), `DiscoverUserOut` (`app/schemas/swipe.py:17`) and `AvatarStatusOut`
(`app/schemas/avatar.py:12`). Pydantic v2 rejects every near-miss — it does not coerce `str` →
`list[str]`, `int` → `str`, or `dict` → `str`, in lax mode either. I checked all five plausible shapes;
all five raise.

**Reproduced**, against the real app with an in-memory SQLite DB and `get_db` overridden. One user whose
`personality_traits` is `[{"trait": "curious", "why": "asks questions"}]` — a shape LLMs routinely
produce when asked for a list of traits:

```
victim  POST /api/auth/login         -> 500
victim  POST /api/mobile/auth/login  -> 500
viewer  GET  /api/users/discover     -> 500   # a different, entirely healthy user
viewer  POST /api/auth/login         -> 200
```

The blast radius comes from `app/api/users.py:80` — `return q.order_by(User.created_at.desc()).all()`,
with **no `LIMIT`** (see #58). Discover returns every ready user in one response, so one poisoned row
takes out discover for the whole user base, not only the users who would have been shown that profile.
`AuthOut` embeds `UserOut` (`app/schemas/user.py:199-201`), so the affected user cannot log in on either
client, which means they cannot reach the "Regenerate" button that would clear the field
(`app/api/avatar.py:104` sets `personality_traits = None`). There is no admin route and no repair
script: recovery is a manual `UPDATE users SET personality_traits = NULL WHERE id = …`.

Same exposure, lower likelihood, on `avatar_description` (`app/tasks/avatar.py:123`; `str | None` in all
four schemas) — a dict or list there breaks identically. `animal` is accidentally safe because
`data["animal"].strip()` raises `AttributeError` on a non-string first (`:118`), which the broad handler
turns into `avatar_status = failed`. That is the *correct* outcome, and it shows exactly what the other
two fields are missing.

Fix, small: validate Claude's parsed payload before persisting. A pydantic model
(`animal: str`, `personality_traits: list[str]`, `avatar_description: str`, `image_prompt: str`) parsed
inside the existing `except (json.JSONDecodeError, KeyError, ValueError)` block gets the right behaviour
for free — `ValidationError` subclasses `ValueError`, so a bad shape marks the avatar `failed` and never
reaches the database. Then, to defuse rows that already exist, add a `mode="before"` field validator on
the four schemas that drops non-string elements. Pin all five bad shapes with a test.

</details>

### 39. ~~Every production deploy deletes all 1000 bots, cascading away real users' matches and chat history~~ ✅ FIXED (7d8bbce)

The seed is now **additive**: it inserts only the addresses that are missing and deletes nothing. Bots
hold no state worth refreshing, so a deploy has no reason to recreate them. A destructive refresh still
exists behind an explicit `RESEED_BOTS=true` that a deploy must never set, and the docstring no longer
claims "idempotent" without qualification.

Also narrowed the match from `LIKE 'demo%@howl.app'` to the exact address set the script owns, built from
`DEMO_USERS`. The old pattern matched any address merely *starting* with "demo", so a real
`demolition@howl.app` was deleted on every deploy too — the smaller sibling of this bug.

The regression test pins the harm itself rather than a proxy: it builds a real user, a match with a bot
and two messages, reseeds, and asserts all three survive with the bot's row id intact. That required
adding `PRAGMA foreign_keys=ON` to `tests/test_seed_demo_users.py`'s fixture, which builds its own engine
and so never inherited it from `conftest.py` — without it SQLite ignores the cascade and the test would
have passed against the destructive code. Confirmed it fails when forced down the destructive path.

<details><summary>Original finding</summary>

`scripts/seed_demo_users.py:321-325`, the first thing `seed()` does:

```python
deleted = (
    db.query(User)
    .filter(User.email.like("demo%@howl.app"))
    .delete(synchronize_session=False)
)
```

`scripts/startup.sh:11-12` runs `python -m scripts.seed_demo_users` on **every boot** unless
`SKIP_SEED=true`, and `railpack.json` makes `startup.sh` the Railway start command. `matches.user1_id`
and `matches.user2_id` are both `ON DELETE CASCADE` (`app/models/match.py:29-33`) and
`messages.match_id` cascades from `matches` (`app/models/message.py:25-27`). So the bulk delete of 1000
`users` rows takes every match those bots were in, and every message in those matches, with it.

Concrete: a user signs up, swipes on twelve profiles, and `auto_match_demo_user` likes back at 90%
(`app/tasks/auto_match.py:79`), so they have ~10 matches — all bots, because bots are 1000 of the
population. They exchange messages for a week. You ship a one-line copy change. On boot the seed runs,
their ten matches and every message in them are gone, the matches list is empty, and the bots are
reinserted with **new ids**, so even the same personas are different rows. No notification, no
tombstone, nothing in the logs beyond `Removed 1000 existing demo user(s).` Reports filed against those
bots survive but have `reported_user_id` nulled by #24's `SET NULL`, so moderation evidence is
anonymised on every deploy too.

The script's own docstring calls this "Idempotent: deletes any existing demo*@howl.app rows before
inserting" (`:6`). It is idempotent with respect to the `users` table and destructive with respect to
everything that references it. GAPS #30 flags the script as untested; this is not a testing gap, it is a
behavioural one, and it is the kind of thing an untested 375-line deploy script is *for* hiding.

Fix, small and worth doing today: make the seed additive. Skip insertion for any `demo%@howl.app` email
that already exists (`ON CONFLICT DO NOTHING`, or select the existing set first), and delete nothing.
Bots have no state worth refreshing — their avatars, bios and archetypes are all static — so there is no
reason to recreate them. If a refresh is ever genuinely wanted, gate it behind an explicit
`RESEED_BOTS=true` that a deploy never sets. Also see #56: with more than one API replica this same
delete/insert runs concurrently from each of them.

</details>

---

## P1 — Correctness and cost

### 40. ~~A failed avatar generation burns the free tier's only monthly regeneration~~ ✅ FIXED (9bfa58c)

`app/api/avatar.py:111` increments `avatar_regenerations_this_month` at *enqueue* time and never refunds
it. `_MONTHLY_REGEN_LIMIT = 1` (`:15`), so a free user gets exactly one regeneration per 30 days,
whether or not it produced an avatar.

Sequence, all of it ordinary:

1. The avatar is stuck `pending` because the Celery worker is not running. CLAUDE.md gotcha #5 and
   RUNBOOK's first diagnosis entry both say this is *the* expected production failure — the worker and
   Beat are not started by `startup.sh` and must be separate Railway services.
2. The client detects the stale `pending` (>2 min on `avatar_status_updated_at`;
   `frontend/src/App.jsx:107-112`) and renders "⚠️ Try Again"
   (`frontend/src/components/ProfileView.jsx:168-174`).
3. The user presses it. `handleRegenerate` → `POST /api/avatar/regenerate` → counter 0 → 1,
   `regenerations_reset_at = now`, task enqueued into a queue nobody is draining.
4. They press it again. `_enforce_regen_limit` → `1 >= 1` → **429 for the next 30 days**, with a
   `detail.message` that tells them to *upgrade to premium*.

Same outcome for a permanent Claude parse failure (`avatar_status = failed`, deliberately no retry —
`avatar.py:150-154`) and for any generic exception. The bio-save path shares the counter
(`app/api/profile.py:38-55`), so a user whose *first* avatar fails has no free retry either.

The product effect is exactly inverted: the users most likely to hit this are new users whose first
impression of the differentiating feature is a broken image and a paywall.

Fix: refund on terminal failure. `_mark_failed` (`app/tasks/avatar.py:29-38`) is the single choke point
for every permanent failure — decrement the counter there, floored at 0, in the same transaction that
writes `failed`. That covers parse errors, generic errors and retry exhaustion. It does not cover
"worker never ran", so also treat a stale `pending` as refundable in `_enforce_regen_limit`: if
`avatar_status == pending` and `avatar_status_updated_at` is older than the client's staleness
threshold, the previous attempt demonstrably produced nothing and should not be charged. About an hour
with tests.

### 41. ~~`avatar_status_updated_at` is never written after the enqueue, so stale-detection fires mid-generation~~ ✅ FIXED (96f553c)

`avatar_status_updated_at` has exactly two writers, both at enqueue time: `app/api/avatar.py:108` and
`app/api/profile.py:101` (plus the seed at `seed_demo_users.py:351`). `app/tasks/avatar.py` sets
`avatar_status` on success (`:142`) and on failure (`_mark_failed`, `:34`) and touches `updated_at` —
but never `avatar_status_updated_at`. A `grep` over `app/` confirms there is no third writer.

This is the timestamp ADR-001 names as the mechanism that handles "a worker dies after accepting a task
but before completing it", and `AvatarStatusOut` exposes it (`app/schemas/avatar.py:15`) purely so the
clients can implement the 2-minute rule.

Concrete wrong outcome. A generation legitimately slower than 2 minutes — three `anthropic.APIError`
retries are 60s apart by construction (`avatar.py:41`), so that path alone is 3+ minutes, and a DALL·E
call plus a 30s image download plus an R2 upload can get there too — has a stale
`avatar_status_updated_at` *while it is still running*. Worse, the web client **stops polling** once
`isStale` is true: `shouldPoll` requires `!isStale` (`frontend/src/App.jsx:126-129`). So the client
gives up watching, shows "Try Again", and the user presses it. `regenerate_avatar` resets the row and
enqueues a second generation. The Redis single-flight lock from #7 makes that second task a no-op — good,
it does not double-pay — but the *first* task then commits `avatar_status = ready` over a row the user
just asked to be regenerated, so they get back the avatar they were trying to replace, having spent
their only monthly slot (#40) to do it.

Fix: write `avatar_status_updated_at` everywhere `avatar_status` is assigned — the success path and
`_mark_failed`. Better, make them inseparable via a single `set_avatar_status(user, status)` helper so
they cannot drift again; that also creates the transactional single-step transition that #23's deferred
`avatar_status='ready' ⇒ avatar_url` CHECK was waiting on. Small.

### 42. ~~The #7 idempotency lock converts a worker crash from duplicate work into *silently dropped* work~~ ✅ FIXED (27e2d67)

`app/tasks/avatar.py:83-88`:

```python
lock_held = task_lock.acquire(lock_key)
if not lock_held:
    logger.info("generate_avatar: user %d already being generated elsewhere — skipping", user_id)
    return
```

`return` completes the task successfully, so Celery **acks the message**. The lock TTL is 600s
(`app/services/task_lock.py:29`) and it is only released in the task's `finally`
(`avatar.py:170-171`) — which does not run if the worker is `SIGKILL`ed.

Sequence: worker is killed mid-`generate_avatar` (OOM, Railway redeploy, `SIGKILL`) while holding
`avatar:generate:42`. `task_acks_late=True` so the broker redelivers immediately. A new worker picks it
up. `avatar_status` is still `pending`, so the already-ready guard at `:77` doesn't fire.
`task_lock.acquire` finds the dead worker's key still present with ~9 minutes of TTL left, returns
`False`, and the task returns and acks. **Nothing will ever retry it.** The lock expires ten minutes
later with no one watching. User 42 is stuck `pending` forever, then goes down the #40 path.

This is precisely the failure ADR-001 claims Celery exists to prevent: *"If the server restarts
mid-generation the task is silently dropped. The user's avatar is stuck in pending forever."* #7 closed
the double-payment hole and opened this one; the entry is worth reopening rather than filing fresh.

Fix: on a failed acquire, defer instead of dropping —
`raise self.retry(countdown=task_lock.DEFAULT_TTL_SECONDS // 4)`. The retry budget bounds it, and the
common case (a genuine concurrent duplicate) still costs nothing because the winner will have set
`ready` before the retry lands, so the `:77` guard short-circuits it. Alternatively store the Celery task
id as the lock value and let the *same* task id re-acquire, which distinguishes "my own redelivery" from
"someone else is working". Small either way; the retry version is two lines.

### 43. ~~Enqueueing a Celery task is the one Redis dependency in the request path that fails *closed*~~ ✅ FIXED (98ab3d4)

Rate limiting fails open by design (`app/services/rate_limit.py:103-105`), chat fan-out fails open to
local delivery by design (`app/services/pubsub.py:35-42`), and task locks fail open by design
(`app/services/task_lock.py:44-56`). All three are documented. `.delay()` and `.apply_async()` are not,
and they do not.

**Measured**, with nothing listening on the Redis port: `notify_new_message.delay(1, 2, 3)` **blocked for
108.8 seconds** and then raised `RuntimeError: Retry limit exceeded while trying to reconnect to the
Celery result store backend. The Celery application must be restarted.`

The call sites are all inside request handlers, after the commit:

| Call | Site | Effect of a Redis outage |
|---|---|---|
| `notify_new_message.delay` | `app/api/chat.py:478` | message is committed, then the request hangs ~109s and 500s |
| `generate_avatar.delay` | `app/api/avatar.py:116`, `app/api/profile.py:109` | avatar row reset to `pending` and committed, then 500 |
| `auto_match_demo_user.apply_async` | `app/api/swipes.py:264` | swipe and match committed, then 500 |
| `notify_new_match.delay` | `app/api/swipes.py:259` | same |

Three things make this worse than a plain 500:

- **The write already happened.** The client sees a failure for a message that is in the database. The
  web client's `handleSend` restores the input text and shows an error; the user sends again and now
  there are two copies.
- **Threadpool exhaustion.** These are `def`, not `async def`, so FastAPI runs them in Starlette's
  threadpool, default 40 workers. Forty concurrent sends parked for 109 seconds each means **no sync
  route in the application can be served** — including `/health`, which is `async def` and so keeps
  reporting `ok` (see #54). A Redis blip becomes a full API outage that the healthcheck calls healthy.
- **"The Celery application must be restarted."** That is the result-backend's own words: after the
  first exhaustion the process's backend is poisoned, so it does not self-heal when Redis returns.

Fix, in order of value: (1) set `broker_transport_options={"max_retries": 1, "socket_timeout": 2,
"socket_connect_timeout": 2}` and `result_backend_transport_options` likewise, plus
`task_publish_retry_policy={"max_retries": 1, "interval_start": 0, "interval_step": 0.2}`, so a dead
broker fails in ~2s rather than ~109s; (2) mark all four tasks `ignore_result=True` (nothing reads their
results) so the enqueue stops touching the result backend at all, which is where the 109s actually went;
(3) wrap each enqueue in `try/except Exception: logger.exception(...)` so a broker outage degrades to
"no notification / no avatar yet" — the same fail-open posture as everything else in the request path —
instead of losing the user's write. Then document it in RUNBOOK alongside the other fail-open entries.
Half a day, and it removes a single-point-of-failure the docs currently claim doesn't exist.

### 44. ~~Wiring an email provider (#3) will immediately hard-bounce ~1000 addresses at your own domain~~ ✅ FIXED (3708c0c)

`app/tasks/notify.py:238` gates the message-notification email on `recipient.email_notifications` and
nothing else. Bots are ordinary `users` rows, `email_notifications` defaults to `True`
(`app/models/user.py:79-84`), and `scripts/seed_demo_users.py:334-357` does not set it — I checked the
full `User(...)` construction. Their addresses are `demo1@howl.app` … `demo1000@howl.app` and no mailbox
exists behind any of them.

Today this is invisible because `app/services/email.py` `print()`s. The moment #3 closes — the top item
on GAPS.md's remaining-work list — every message a real user sends to a bot becomes a real send to a
nonexistent address at your own domain. Bots are 1000 of the population and auto-match likes back 90% of
the time, so bot conversations are the *majority* of conversations in the app. A new sending domain that
opens with a hard-bounce rate in the tens of percent gets throttled or suspended by every provider worth
using; SES pauses sending above 5%.

`notify_new_match` is unaffected: push only, and bots hold no push tokens, so `_deliver_push` returns
`None` (`notify.py:136-138`).

Fix, two lines: `if recipient.is_bot: return` early in `notify_new_message`, and
`email_notifications=False` on seeded bots. Do both — the first protects rows that already exist, the
second protects any future notification path. Worth landing *before* #3, and worth a test, because it is
the class of bug that only ever fails in production.

### 45. ~~Bot replies are never broadcast and never notified, so the bot population is silent~~ ✅ FIXED (529e534)

`app/tasks/bot_response.py:267` constructs `Message` rows and `_save_replies` commits them. That is the
end of it. Cross-checking the two delivery mechanisms:

- `manager.broadcast` is called from exactly two places, both in the REST handlers
  (`app/api/chat.py:389`, `:474`).
- `notify_new_message.delay` is called from exactly one place (`app/api/chat.py:478`).

So when a bot replies: no WebSocket event, no push notification, no email. A user sitting in the chat
sees nothing until they navigate away and back (`loadMessages` runs on mount only — see #47). A user with
the app closed is never told. The unread badge does eventually update, because it is derived from
`read_at`, but only when they open the matches list.

The whole re-engagement loop — the reason `notify_new_message`, Expo push, `_deliver_push`, retry
budgets and ticket parsing (#16) exist at all — is dead for the conversations that make up most of the
app. A new user gets a "New match! 🎉" push (that path works, via `auto_match_demo_user` →
`notify_new_match`) and then never hears about that conversation again.

Fix: from the worker, publish to the match's pub/sub channel and enqueue the notification —
`ChatPubSub.publish(match_id, {"kind": "message", "event": _msg_event("new_message", msg)})` plus
`notify_new_message.delay(match_id, real_user_id, bot_id)`, per saved reply. The channel shape and the
origin-stamping already handle a non-web publisher correctly, since the worker is just another origin
that no replica shares. Note `ChatPubSub.publish` is `async` and the task is sync, so this needs an
`asyncio.run` around a small helper or a plain sync `redis.publish` of the same envelope — the envelope
format is a two-key dict (`app/services/pubsub.py:226`), so the sync version is trivial. Half a day
including the #44 bot-email guard.

### 46. ~~A single 5-second send timeout unregisters a live WebSocket without closing it~~ ✅ FIXED (bf5f089)

`ConnectionManager._send` returns `False` on a `_SEND_TIMEOUT_S = 5.0` timeout or any exception
(`app/api/chat.py:205-214`), and both delivery paths then drop the socket from the registry:
`_deliver_message:189-190` and `_deliver_typing:202-203` each do `conns.pop(ws, None)`. **Neither calls
`ws.close()`.**

The socket stays open at the transport layer. The client's `onclose`/`onerror` never fires, so its
reconnect logic never runs. It is no longer in `self._conns[match_id]`, so it receives neither local
deliveries nor pub/sub deliveries. The user sits in a chat that looks connected and silently receives
nothing for the rest of the session. Both clients funnel every recovery path through `onclose`
(`frontend/src/App.jsx:178-187`, `mobile/src/hooks/useMatchWebSocket.ts:130-171`), so neither has any
way to notice.

Five seconds is well inside normal for a phone: a backgrounded app, a tunnel, a wifi-to-cellular
handover. The comment at `chat.py:45-48` explains the policy ("a single slow socket must not stall
delivery for everyone else… treat the socket as dead and drop it") and the policy is right — the
implementation just leaves the client believing otherwise.

There is a second-order effect worth fixing at the same time. The WS handler is still parked in
`await ws.receive_text()` (`:313`), so its `finally: await manager.disconnect(...)` has not run, and
`self._conns[match_id]` can be an empty-but-present dict. `connect()` then computes
`first_for_match = match_id not in self._conns` (`:111`) → `False` → it skips
`await self._pubsub.subscribe(match_id)`. I traced the orderings and could not construct a case where
this actually loses delivery, because the earlier subscription is never released either — but the
invariant "`match_id` present ⇒ subscribed" is now maintained by two functions that can disagree, and
the pruning path bypasses the one that owns it.

Fix: when dropping a socket, close it —
`asyncio.create_task(ws.close(code=1011))` alongside the `pop` — so the client's existing reconnect path
fires. Then route pruning through `disconnect()` rather than mutating `conns` directly, keeping
subscribe/unsubscribe bookkeeping in one place. Pin with a test that a timed-out socket receives a close
frame. Note the fix is only *useful* once #47 lands, since reconnecting without refetching recovers
nothing.

### 47. ~~Neither client refetches on reconnect, so pub/sub's documented recovery path does not exist~~ ✅ FIXED (bc1d58e + 13e9f5f)

`app/services/pubsub.py:44-51` states the delivery contract explicitly:

> Redis pub/sub is fire-and-forget. An event published while a replica is momentarily disconnected is
> dropped, with no replay. That is acceptable because a message row is committed to Postgres *before* it
> is broadcast … the socket is the optimistic layer and `GET /api/matches/{id}/messages` is the source of
> truth. **A dropped socket event costs latency until the client refetches, never the message itself.**

Neither client refetches.

- **Web** (`frontend/src/App.jsx:141-200`): `ws.onclose` schedules `connect` after
  `WS_RECONNECT_DELAY_MS`. `connect()` opens a socket and nothing else. `loadMessages` is called only
  from `handleSelectMatch` (`:619`) and a manual retry button (`ChatView.jsx:195`).
- **Mobile** (`mobile/app/(app)/chat/[matchId].tsx:131-136`): `loadMessages()` runs in a `useEffect`
  keyed on `[loadMessages]`, which is stable per `mid` — so **once per mount**. The hook's `ws.onopen`
  (`useMatchWebSocket.ts:116-120`) resets backoff and sets status; it does not notify the screen.

Mobile is the worse case because the hook *deliberately manufactures* the gap: it closes the socket on
`AppState` `background` and reopens on `active` (`:184-197`). So every single app switch produces a
window in which messages are dropped with no replay and no refetch. The user foregrounds the app, the
socket reconnects, the status pill says connected, and the conversation is silently missing everything
that arrived while they were away — until they back out to the matches list and re-enter.

Combined with #45 (bot replies never reach the socket at all) the practical result is that a mobile
user's chat view is stale after every context switch, for the majority of their conversations.

Fix: refetch the first page whenever the socket transitions to open. Web: call `loadMessages(currentMatch.id)`
from a new `ws.onopen`. Mobile: return `status` from the hook (it already does) and add an effect that
calls `loadMessages()` on each `connecting`/`reconnecting` → `open` edge.

**One trap in the mobile fix**, which is why this is worth writing down: `loadMessages()` with no
`beforeId` does `setMessages(fresh)` where `fresh` is filtered against `seenIdsRef`
(`chat/[matchId].tsx:117-127`). On a second call every message is already in `seenIdsRef`, so
`fresh === []` and `setMessages([])` **wipes the conversation**. The refetch has to merge into `prev` by
id rather than replace, or clear `seenIdsRef` first. Half a day for both clients.

### 48. ~~`GET /api/matches/{id}/messages` marks only the returned page read, so a badge above 50 never clears~~ ✅ FIXED (3378b1b)

`app/api/chat.py:415` fetches `_PAGE_SIZE + 1 = 51` rows newest-first and truncates to 50; `:423-426`
marks `read_at` only on the messages in that page. Both unread counters — `unread_count` (`:492-500`)
and the correlated subquery in `list_matches` (`app/api/users.py:127-136`) — count **all** unread rows in
the match, unbounded.

So a match with 60 unread messages: the user opens the chat, reads everything the UI shows them, and the
badge still says 10. Nothing in the app will ever clear it. The only code that writes `read_at` is this
endpoint, and it only ever touches the newest 50 or a page selected by `before_id`, which requires the
user to deliberately scroll back through history they have already decided not to read. The matches list
then shows a permanent phantom unread count.

Reachable by ordinary operation, not adversarial input: the `desperate` archetype chases after 2h of
silence and there are 50 of them in the seed (`seed_demo_users.py:199-206`), so a conversation a user
ignores for a couple of weeks crosses 50 on its own.

Fix: when `before_id is None`, mark the whole conversation read with one statement —
`UPDATE messages SET read_at = :now WHERE match_id = :m AND sender_id != :u AND read_at IS NULL` —
instead of looping over the page. That is cheaper than the current per-row loop, and it makes "opened the
chat" mean "read the conversation", which is what the badge already claims. Small.

### 49. ~~Read receipts are never broadcast~~ ✅ FIXED (31b71cc + d4b2c23)

Outbound WS events are `new_message`, `message_deleted` and `typing`. `_msg_event`
(`app/api/chat.py:220-232`) is the only event builder and it is called from exactly two places (`:389`,
`:474`). `get_messages` writes `read_at`, commits (`:427-428`), and broadcasts nothing.

So the sender's ✓ never becomes ✓✓ until their client happens to refetch the conversation — which, per
#47, it does only on mount. Both clients render the distinction and are waiting for data that never
arrives: `frontend/src/components/ChatView.jsx:255-256` and
`mobile/app/(app)/chat/[matchId].tsx:439-440` both switch on `msg.read_at`. The plumbing is complete in
every other respect: `MessageOut.read_at` exists, `_to_out` populates it (`:252`), and `_msg_event` even
carries `read_at` (`:229`). Only the trigger is missing.

It also degrades the push-suppression heuristic. `notify_new_message` defines "recently active" as *read
an incoming message or sent one within 5 minutes* (`app/tasks/notify.py:210-228`). Since nothing marks
messages read except a REST refetch, a recipient sitting in the chat with a healthy WebSocket — receiving
and reading messages in real time — becomes invisible to that check five minutes after their last
refetch, and gets pushed and emailed about a message they are looking at.

Fix: broadcast a `messages_read` event (match id, reader's user id, high-water-mark message id) after the
commit in `get_messages`, through the same `background_tasks` + `manager.broadcast` path the other two
use, and have both clients patch `read_at` from it. Half a day across three codebases. Cheaper interim
fix for the notification half only: a Redis presence key per `(match_id, user_id)` refreshed by the WS
handler, which `notify_new_message` also consults — needed anyway because the connection registry is
per-replica and the Celery worker cannot see it.

### 50. ~~A failed swipe pops the card *and* arms Undo, so the next Undo destroys the previous match~~ ✅ FIXED (0682ad9 + e957a08)

`frontend/src/App.jsx:834-875`. Two problems in the same handler.

**Undo targets the wrong swipe.** `setDiscoverUsers(prev => prev.slice(1))` and `setCanUndo(true)` run
at `:857-858`, *before* `res.ok` is consulted, and again in the `catch` at `:869`. So on a 500, or a
409, or a dropped connection, the card is discarded and Undo is armed even though no swipe row was
written. `DELETE /api/swipes/last` then deletes the user's *most recent actual* swipe
(`app/api/swipes.py:299-304`, ordered by `id desc`) — which is the previous one, the successful one. If
that swipe created a match, `undo_last_swipe:319-334` deletes the match, cascades away its messages, and
deletes the other party's swipe too.

Concrete: user likes A, mutual, match created, popup shown. They swipe on B and the request 500s. UI
shows "Swipe failed — tap to try again" (`:862`) with B's card already gone. User presses Undo expecting
to get B back. The server deletes the *A* swipe and the A match and its conversation; the UI prepends A's
profile to the deck (`:887`) and says "↩️ Undid swipe on A". The user has silently lost a match and its
messages because a different request failed.

**The wrong card is popped.** `handleSwipe(targetUserId, direction)` receives the id and then discards
it, popping index 0 by position. The nav bar calls `fetchDiscoverUsers()` on every visit to discover
(`:775`, `:921`) and it replaces the array wholesale (`:798`), so if a refetch resolves between render
and the swipe response, `slice(1)` removes a profile the user never saw while the one they swiped on
comes back.

Fix: only mutate on success, and address by id rather than position —
`setDiscoverUsers(prev => prev.filter(u => u.id !== targetUserId))` and `setCanUndo(true)` both inside
`if (res.ok)`. On failure, leave the card in place, which is also what the "tap to try again" copy
already promises. Then have `undo_last_swipe` take the swipe id the client is undoing and 409 on a
mismatch, so a stale client can never delete a swipe it didn't mean to. Small on the client, small on
the server, and the server half is what makes it safe rather than merely less likely. Related to #33
only in that it lives in `App.jsx`; the bug is independent of the decomposition.

---

## P2 — Architecture and scale

### 51. ~~`process_bot_responses` has no single-flight lock, so overlapping ticks double-reply and double-pay~~ ✅ FIXED (4843b78)

`app/celery_app.py:33-38` schedules the task every 900s. `#8` capped spend *per run*
(`_MAX_PENDING_PER_RUN = 200`, `_MAX_CONSECUTIVE_FAILURES = 3`) but nothing prevents two runs existing at
once. A full run makes up to 20 sequential Claude Haiku calls at 2048 output tokens each
(`bot_response.py:65`, `:490-504`); at 20–40s per call under load that is 400–800s, close enough to 900s
that overlap is a matter of when, not if.

Two runs overlapping both call `_collect_pending`, which selects conversations where the *real user*
spoke last (`:224-228`). Run 1 has not committed the replies for its later batches yet, so run 2 sees the
same rows, generates a second set of replies, and `_save_replies` writes them. **The user gets two
replies from the same bot** and you pay for both.

Honest caveat on likelihood: with `--pool=solo` (what RUNBOOK prescribes for local Windows dev) the
second task queues behind the first, so they serialise and the queue simply grows. In production a
prefork worker with default concurrency ≥ 2 runs them genuinely in parallel. Two Beat instances — a
Railway restart overlapping the old container, or the beat service scaled past 1 — produce the same
overlap regardless of pool. `generate_avatar` got a Redis lock for exactly this reason (#7); the task
that spends far more got a cap but no lock.

Fix: wrap the task body in `task_lock.acquire("bot_response:tick", ttl=1800)` with a `finally` release —
the machinery already exists and is already tested. Half an hour. Note that the fail-open behaviour is
correct here for the same reason it is for #7: a Redis outage should degrade to today's behaviour, not
stop bots replying.

A smaller fairness point in the same function: the per-run cap truncates a list ordered by
`(bot.id, Match.id)` (`:210`, `:478`), which is deterministic. Conversations do drain — a served
conversation leaves `pending` because the bot then spoke last — but with a persistent backlog above 200,
high-`bot_id` conversations are always served last while low-`bot_id` users who reply promptly keep
re-entering ahead of them. Ordering by `last_created_at ASC` (longest-waiting first) is a one-line change
and is what a user would consider fair.

### 52. ~~Blocks are enforced only in the discover query; every other endpoint that takes a user id ignores them~~ ✅ FIXED (13a7069)

`Block` is consulted in exactly one place: the two `notin_` subqueries in `discover_users`
(`app/api/users.py:41-58`). `block_user` additionally deletes the match and both swipe rows
(`app/api/blocks.py:20-31`), which is what makes messaging fail — the match is gone, so
`_require_match_member` 404s. Blocking is therefore *effective* for chat, by side effect rather than by
check. Nothing else looks at the table:

- **`GET /api/profile/{user_id}`** (`app/api/profile.py:142-156`) — no block check. Someone you blocked
  can still read your name, age, location, bio, animal, traits and avatar, indefinitely, by user id. #1
  correctly narrowed this schema and added auth; it did not make it respect the one relationship whose
  entire purpose is "this person should not be able to see me".
- **`POST /api/swipes`** (`app/api/swipes.py:196-273`) — no block check. A blocked user can `like` the
  person who blocked them and the row persists. No match forms while the block stands (the blocker
  cannot see them in discover), but on unblock the blocker's discover shows them again with the blocked
  party's like already banked, so a single tap produces an instant match. The blocker's model is "we
  start fresh"; what actually happened is that the block period was a free pass to pre-place a like.
- **`POST /api/reports`** — a blocked user can still file reports against the blocker. Arguably correct,
  and I'd leave it.

Fix: a shared `blocked_between(db, a_id, b_id) -> bool` helper, called by `get_profile` (404, not 403 —
do not confirm the block exists) and by `record_swipe` (404 for the same reason). An hour including
tests. The deeper version — a `blocks`-aware guard dependency applied to every route that accepts another
user's id — is the right architecture but a bigger change; the two-call-site version closes the observable
holes.

### 53. ~~`POST /api/reports` is an oracle for message authorship, and is unthrottled and undeduped~~ ✅ FIXED (668c727)

`app/api/reports.py:39-47` validates a submitted `message_id` by loading the message and checking
`msg.sender_id != body.reported_user_id`. It never checks that the *reporter* is a participant in that
message's match. The three outcomes are distinguishable:

| Probe | Response |
|---|---|
| `message_id` does not exist | 404 "Message not found." |
| exists, different author | 400 "Message does not belong to the reported user." |
| exists, authored by `reported_user_id` | 200, and a `Report` row is created |

So any authenticated user can walk `message_id = 1..N` against a chosen victim id and learn exactly
which messages that person wrote — the private social graph (who is talking, how much, and when, via the
report's `created_at` correlation) without ever reading content. Sequential integer ids make the sweep
trivial.

Two multipliers, both independent gaps: `/api/reports` has **no rate limit** — `enforce_rate_limit` and
`check_rate_limit` appear in `app/api/auth.py`, `app/api/mobile_auth.py` and `app/api/chat.py` only
(#26's scope) — and there is **no dedup**, so nothing stops one account filing unbounded reports against
one target. Every successful probe also writes a row, so the sweep fills the moderation queue with
garbage that #24 deliberately made survive account deletion.

Fix: require that the reporter is a member of the message's match before accepting a `message_id`, and
return the same 404 for "not found" and "not yours" so the endpoint stops distinguishing them. Add
`enforce_rate_limit(request, "report")` with a modest bucket, and a unique constraint or an upsert on
`(reporter_id, reported_user_id, message_id)` so a duplicate report updates rather than inserts. Two to
three hours.

### 54. ~~`/health` never touches Postgres or Redis, so a broken replica reports healthy~~ ✅ FIXED (5301b32)

`app/main.py:76-78` returns `{"status": "ok", "environment": …}` unconditionally. It is `async def`, so
it does not even need the sync threadpool that #43 can exhaust. Railway uses it as the deploy healthcheck
and the liveness signal.

Consequences: a replica whose connection pool cannot reach Postgres passes the healthcheck and serves
500s; a bad `DATABASE_URL` in a new deploy goes green and takes traffic; the Redis outage in #43 —
which parks every sync route for 109 seconds — is reported as healthy throughout, so nothing sheds the
replica or rolls the deploy back. There is no other liveness surface: no `/metrics`, no readiness
endpoint, and no queue-depth or worker-heartbeat signal anywhere, which is also why "avatars stuck
pending because the worker isn't running" (CLAUDE.md gotcha #5) is diagnosed by a human reading RUNBOOK
rather than by an alert.

Fix: `SELECT 1` and a Redis `PING`, both with ~1s timeouts, reported per-dependency with an overall
status, and returning 503 when a dependency is down. Keep a separate always-200 liveness path if Railway
needs one, so a Redis blip restarts nothing. An hour. The higher-value follow-on is a Beat-scheduled
heartbeat key that `/health` reports the age of, which would turn "avatars stuck pending" into a visible
signal — Sentry is wired (`app/main.py:24-35`) and would carry the alert.

### 55. ~~No Celery queue routing and no task time limits, so bot batches starve the avatar critical path~~ ✅ FIXED (5ad95f5)

`app/celery_app.py:16-29` sets no `task_routes`, no `task_time_limit`, and no `task_soft_time_limit`.
All four task types share the default queue, and `worker_prefetch_multiplier=1` with `task_acks_late`
means a worker holds one task at a time.

CLAUDE.md calls the avatar pipeline "the product differentiator" and "the critical path". It shares a
FIFO queue with `process_bot_responses`, which is the longest-running task in the system by an order of
magnitude (up to 20 sequential Claude calls, minutes of wall clock — #51). A new user saves their bio at
the wrong moment and `generate_avatar` sits behind a bot tick, so the thing they are staring at waits
minutes — long enough to cross the 2-minute staleness threshold and trigger the #41/#40 cascade.
`notify_new_message` queues behind it too, so push notifications arrive minutes late.

No time limit means a hung provider call parks a worker indefinitely. The `anthropic` client's default
timeout is generous (ten minutes) and `httpx.Client(timeout=30.0)` only covers the image download
(`app/services/image_generation.py:178`), so the DALL·E `images.generate` call has whatever the OpenAI
SDK defaults to and nothing bounds the task as a whole. With `--pool=solo` on Windows that is the entire
worker.

Fix: `task_routes` splitting `bot_response` onto its own queue and running a second worker for it —
one line of config plus one Railway service. Add `task_soft_time_limit`/`task_time_limit` per task
(generous for `generate_avatar`, tight for the notify tasks), so a hung call raises rather than parks.
Also worth setting `result_expires` explicitly rather than relying on Celery's one-day default, and
`ignore_result=True` per #43. A couple of hours plus the deploy change.

### 56. ~~`startup.sh` runs migrations *and* the destructive seed on every replica~~ ✅ FIXED (db06169)

`scripts/startup.sh` is the Railway start command for the API service, and it runs
`alembic upgrade head` (`:5`) then the seed (`:12`) before `exec uvicorn` (`:16`). Every replica runs
both.

With one replica this is fine. With two:

- **Migrations race.** Alembic takes no advisory lock by default. Two replicas booting together both run
  `upgrade head`; Postgres DDL is transactional so one wins and the other fails on a duplicate object.
  `set -e` at `:2` means the loser's container exits, Railway restarts it, and it either succeeds on the
  retry or crash-loops. Scaling replicas is therefore a coin flip on whether the deploy comes up.
- **The seed races destructively.** Two replicas concurrently run the delete-all-bots-then-insert-1000
  from #39. Interleaved, one replica's `INSERT` collides with the other's on `users.email` unique, the
  seed raises, and `|| echo "WARNING: seed script failed — continuing anyway."` (`:12`) swallows it — so
  the app starts with a **partially deleted bot population** and a warning in the log stream. Combined
  with #39, a deploy can leave 400 bots and 600 destroyed conversations.

Fix: move migrations and seeding out of the app start command into a Railway pre-deploy command (or a
one-shot release service), so they run exactly once per deploy. If they must stay in `startup.sh`, wrap
both in a `pg_advisory_lock` so the second replica waits instead of racing. Making the seed additive
(#39) removes the destructive half of this independently, which is why #39 is the cheaper fix to do
first.

### 57. ~~Push-token registration reassigns a token with no proof of device, no per-user cap, and no format check~~ ✅ FIXED (de3724a)

`app/api/push_tokens.py:29-33`:

```python
record = db.query(PushToken).filter(PushToken.token == body.token).first()
if record is None:
    db.add(PushToken(user_id=current_user.id, token=body.token))
elif record.user_id != current_user.id:
    record.user_id = current_user.id
```

GAPS #23 withdrew the `(user_id, token)` pair-constraint suggestion, and that withdrawal is correct —
global uniqueness *is* the right model, and `test_shared_device_reassigns_its_push_token` pins it. What
the entry did not consider is that the reassignment itself is an authenticated write with no
authenticity check on the token. Three consequences, in descending order of severity:

- **Reassignment is a notification-takeover primitive.** Any authenticated account that learns another
  user's Expo token can POST it and silently claim it. The victim then receives *the attacker's*
  notifications on their phone and none of their own, with nothing in either UI to indicate it. Expo
  tokens are 22 random characters so they are not guessable — this needs an out-of-band leak (a shared
  log, a support ticket, a crash report) and is therefore not urgent. But it is unauthenticated-by-value
  where everything else in the app is authenticated-by-session.
- **No per-user cap.** `PushTokenIn` validates only non-blank (`app/schemas/push_token.py:5-12`), and
  nothing bounds rows per user. One account can register 100k distinct 255-char strings; every
  subsequent `_deliver_push` for that user then builds a 100k-token Expo request
  (`app/tasks/notify.py:70-73` selects them all with no limit).
- **No format validation.** `ExponentPushToken[…]` shape is never checked, so garbage accumulates and is
  sent on every notification. Only `DeviceNotRegistered` tickets get pruned (`_prune_expired_tokens`),
  and malformed tokens come back as a different verdict.

Fix, cheap and worthwhile: a `field_validator` requiring the `ExponentPushToken[...]`/`ExpoPushToken[...]`
shape, and a cap (say 10 rows per user, evicting oldest) at registration. The takeover half wants
something more like a signed device attestation, which is a real design decision — at minimum log
reassignments so it is auditable, and consider requiring a fresh login rather than any valid session.

### 58. ~~`GET /api/users/discover` has no `LIMIT` and a fixed ordering~~ ✅ FIXED (b8501c7 + 2f322e5)

`app/api/users.py:80` — `return q.order_by(User.created_at.desc()).all()`. Every eligible user, in one
response, on every call.

With the 1000 seeded bots plus real users that is ~1000 `DiscoverUserOut` objects, each carrying `bio`
(up to 500 chars) and `avatar_description`, so a few hundred KB per call. The web client fetches it on
every visit to the discover view (`frontend/src/App.jsx:775`, `:921`) and swipes locally through the
array, so the payload is re-downloaded on every navigation. It grows linearly with the user table
forever. It is also what turns #38 from one broken profile into a global outage.

The fixed `created_at DESC` ordering has two more consequences. Everyone sees the same profiles in the
same order, so with a 1000-bot seed spread over 30 days (`seed_demo_users.py:333`) the newest bots
dominate every user's first impressions and the rest are effectively unreachable. And it makes the
`slice(1)` positional bug in #50 reachable, since a refetch reorders nothing but can change membership.

Fix: cursor or offset pagination with a sane page size (25–50), and randomise within the page — for
Postgres, `ORDER BY random()` on a filtered set this size is acceptable, or add a stable per-user shuffle
seed. The clients need a "load more when the deck runs low" path, which the web client's array-slicing
model makes straightforward. Half a day across the backend and both clients.

### 59. ~~No per-user WebSocket connection cap, which also makes the #26 typing limit bypassable~~ ✅ FIXED (06b0dc0)

`ConnectionManager._conns[match_id]` is a dict keyed by `WebSocket` (`app/api/chat.py:101`) and
`connect()` (`:109-116`) adds unconditionally. Nothing limits how many sockets one user may open to one
match, or in total.

`_TypingBudget` is per-connection and its docstring makes the claim that this is fine: *"a WebSocket is
pinned to the process that accepted it, so a local counter is **exact** for that connection and needs no
coordination"* (`:57-66`). Exact per connection, yes — but the limit that #26 was closing is per *user*.
Open 50 sockets to the same match and the typing budget is 50×, and each frame fans out to every socket
in the match on every replica. The limiter's own comment names the risk it is guarding
("an unbounded typing stream now fans out to every replica serving the match, so spam amplifies") and
the guard is placed one level below where the abuse lives.

Separately, unbounded sockets per user is a plain resource issue: each is a live connection, a registry
entry, and a recipient of every `_deliver_message` fan-out.

Fix: cap sockets per `(user_id, match_id)` — one or two — and close the oldest when a new one connects,
which also gives correct behaviour for the ordinary case of a user opening the same chat in two tabs.
Then key `_TypingBudget` on `user_id` within the match rather than on the socket. An hour or two.

### 60. ~~There is no server-side revocation of an open WebSocket~~ ✅ FIXED (bd0d961 + d4b2c23)

The WS handler authenticates once, at connect (`app/api/chat.py:278-305`), and then loops on
`receive_text` indefinitely (`:311-331`). The token's `exp` is never re-checked and nothing can evict a
live socket. Access tokens are 30 minutes; a socket lives for hours.

Three cases where the server believes access has been revoked and it has not:

- **Password reset.** #6 correctly revokes every `RefreshToken` row so a compromised account cannot be
  re-entered. An attacker with a live chat socket keeps reading the victim's incoming messages in real
  time until they disconnect. ADR-003 accepts un-revocable access tokens for their 30-minute window; the
  socket silently extends that window without bound.
- **Unmatch.** `unmatch` (`:336-360`) deletes the match and cascades its messages, broadcasting nothing
  and closing nothing. The other party's client keeps a socket open on a match that no longer exists,
  shows the conversation as normal, and gets a bare 404 on their next send.
- **Block.** `block_user` does the same via `_remove_relationship`. Both clients are *written* for a
  4003 close (`mobile/src/hooks/useMatchWebSocket.ts:140-144` treats it as terminal: "Blocked,
  unmatched, or never a participant — retrying cannot help") — a code the server only ever sends at
  connect time.

Fix, in increasing order of cost: (1) have `unmatch` and `block_user` publish a `match_closed` event on
the match channel and have `ConnectionManager` close the local sockets for it — that lights up client
handling that already exists; (2) re-validate the token's `exp` on a timer in the WS loop and close 4001
when it lapses, which the mobile hook already knows how to recover from via `refreshAccessToken`;
(3) check a Redis revocation epoch per user, bumped on password reset, at the same checkpoint. (1) is
half a day and closes the two user-visible cases.

### 61. ~~Test isolation: Celery enqueues are not centrally neutralised, and CI runs with no Redis at all~~ ✅ FIXED (98ab3d4 + 0bd9ab4)

GAPS.md's closing note describes three autouse fixtures for Redis leakage. There are five
(`tests/conftest.py`): `notify_new_match.delay`, `rate_limit.check_rate_limit`,
`task_lock._get_client`, `chat.check_rate_limit`, and `ChatPubSub.subscribe/unsubscribe/publish`. The
gap is not in those five, it is in what they imply — the pattern is per-symptom, and the symptom they
missed is the *other* Celery enqueues.

`notify_new_message.delay` is patched only in `tests/test_chat.py:11`. `generate_avatar.delay` is patched
per-file in `test_avatar.py`, `test_profile.py`, `test_profile_regen.py` and `test_regen_limit.py`.
`auto_match_demo_user.apply_async` only in `test_auto_match.py`. Each of those is a module-local patch of
an importer, so a new test file that posts a message, saves a bio, or swipes on a bot reaches the real
`.delay()`.

Two different failures follow, which is what makes this worth fixing rather than remembering:

- **Locally**, Redis is up (docker compose), so the enqueue *succeeds*: a real task lands in the shared
  broker on DB 0, keyed off ids from the SQLite test database. RUNBOOK tells developers to keep a Celery
  worker running. That worker consumes the test's task and executes it **against the dev Postgres** —
  `notify_new_message(match_id=1, recipient_id=1, sender_id=2)` resolves ids that mean something else
  entirely there. This is also the concurrency problem you hit today with four agents: the broker list is
  shared, so runs feed each other tasks.
- **In CI** there is no Redis at all. `.github/workflows/ci.yml` sets
  `REDIS_URL: redis://localhost:6379/0` and defines **no `services:` block**, so nothing is listening. I
  measured what an unpatched enqueue costs in that situation: `.delay()` blocks for **108.8 seconds** and
  then raises `RuntimeError: … The Celery application must be restarted.` One forgotten patch is a
  two-minute stall, a failure, and — per that error text — a poisoned result backend for every remaining
  Celery-touching test in the process.

The fail-open fixtures hide how load-bearing this is: `check_rate_limit` and `task_lock` genuinely do not
care whether Redis exists, so CI's missing Redis is invisible until someone touches an enqueue.

Fix, one fixture: autouse, patching `celery.app.task.Task.apply_async` to a no-op recorder unless a test
opts in via a marker (the `real_pubsub` precedent). That nets every call site at once — `.delay()` routes
through `apply_async` — and lets the per-file patches be deleted. Do **not** use
`task_always_eager`: that runs the task bodies, which is a different and much larger behaviour change.
Separately, add a `redis:7` service to the CI backend job with `REDIS_URL` on a non-zero DB, so CI stops
being a configuration that no developer runs, and derive test Redis keys from a per-run prefix
(`uuid4()` in a session fixture) so two concurrent runs cannot collide even where a test does use real
Redis. An hour, and it retires a whole class of future flake.

### 62. ~~An R2 upload failure silently falls back to ephemeral local storage, indistinguishable from R2 being unconfigured~~ ✅ FIXED (d77e7f8)

`app/services/image_generation.py:184`:

```python
url = _upload_to_r2(img_bytes, filename) or _save_locally(img_bytes, filename)
```

`_upload_to_r2` returns `None` both when R2 is *not configured* (`_get_r2_client()` → `None`, `:99-101`)
and when a configured upload *fails* (`:112-114`, one `logger.warning`). Either way the image lands in
`static/avatars/`, `avatar_url` becomes `/avatars/<uuid>.png`, and the row is committed `ready`.

So a wrong `R2_SECRET_ACCESS_KEY`, a deleted bucket, or an R2 outage produces avatars that look
completely healthy — 200s from the `StaticFiles` mount, images render, users are happy — until the next
Railway redeploy wipes the ephemeral disk and every avatar generated since the misconfiguration 404s at
once. RUNBOOK's "Avatars 404 after a deploy" entry gives exactly one cause ("The `R2_*` vars aren't
set") and one remedy ("affected users must regenerate"), which per #40 free users cannot do more than
once a month. There is no signal that distinguishes the two cases at any observable layer: no metric, no
Sentry event (it is a `warning`, not an exception), and nothing in `/health`.

Note this is the same code path GAPS #30 lists as still untested — the *production* avatar persistence
path — so a credential typo has no test that would catch it either.

Fix: make the two cases distinguishable. If the `R2_*` vars are set, an upload failure is an error, not a
fallback: log at `error`, report it to Sentry explicitly, and either fail the task (so `avatar_status`
goes `failed` and the user is told) or store locally but set a flag so a repair job can re-upload. Add
the R2 configured-vs-reachable distinction to `/health` per #54. Small, and it makes the #30 test worth
writing because there is then a behaviour to assert.

---

## P3 — Engineering hygiene

### 63. ~~ADR-003 and ADR-004 describe an architecture that no longer exists~~ ✅ FIXED (4bcd3b0)

`docs/decisions/ADR.md` is presented as the place "an engineer reading the codebase for the first time"
learns why things are the way they are. Two of its seven records are now false, and neither is marked
superseded:

- **ADR-003** ("JWT for authentication instead of sessions") says tokens are stored in `localStorage`
  and sent as `Authorization: Bearer` on all protected endpoints, and spends a "Tradeoffs acknowledged"
  section on XSS exposure from `localStorage`. The web client uses **httpOnly cookies**
  (`app/dependencies.py:14-19` resolves the cookie *first*; `app/api/auth.py` sets it), which is the
  mitigation the ADR describes as not taken. A reader trusting this document would conclude the web
  client has an XSS token-theft problem it fixed some time ago.
- **ADR-004** ("HTTP polling for chat instead of WebSockets") documents a 3-second poll, states that
  WebSockets would need "a pub/sub layer (Redis Pub/Sub…)" as the reason not to, and derives a load
  estimate from it. Chat is WebSockets with Redis pub/sub (#17). Its status line says
  "Accepted (v1), expected to change", which is the only reason this is P3 rather than P2 — but the
  change happened and the record was not updated. Its consequence about the read-receipt mechanism
  ("the 3-second poll also doubles as the read-receipt mechanism") is exactly the assumption #49 shows
  the app is now missing.

#36 fixed the counting errors in this file ("five related tables", "9 migration files"). It did not
revisit whether the *decisions* still hold.

Fix: mark both **Superseded**, with a one-line pointer to what replaced them and why, and add ADR-008
(cookie-or-bearer unified auth — CLAUDE.md calls that unification "deliberate and correct", which is
exactly what an ADR is for) and ADR-009 (WebSockets + Redis pub/sub, including the fail-open-to-local
policy and the "committed before broadcast" contract that #47 shows the clients don't yet honour). An
hour, and it is the highest-value hour in this section because these two documents actively mislead.

### 64. ~~`ARCHITECTURE.md` and `RUNBOOK.md` still describe pre-fan-out behaviour as current~~ ✅ FIXED (9b66e35)

Both were updated by #36 *before* the eight-branch pass landed, and several statements are now wrong in
the direction that matters — they describe closed vulnerabilities as open:

- `ARCHITECTURE.md:89` — the routers table marks `GET {user_id}` "⚠ unauthenticated". #1 fixed it.
- `ARCHITECTURE.md:78-79` — "`is_email_verified` … **read nowhere**". `require_verified_email` exists
  (#25); still attached to no route, but the claim as written is no longer accurate.
- `ARCHITECTURE.md:108-109` and `RUNBOOK.md:81-84` — "The connection registry is an **in-process dict**
  … single-replica-only by construction… Scale to one replica until Redis pub/sub fan-out exists." #17
  built it. `RUNBOOK` is giving an operator active instructions based on a resolved limitation.
- `ARCHITECTURE.md:110-111` and `RUNBOOK.md:96-97` — the chat send limit "counted with a DB `COUNT` per
  request" (it is Redis now, `chat.py:450`), "`/api/mobile/auth/login` has no rate limiting at all" (#2),
  and "the IP bucket trusts a client-supplied `X-Forwarded-For`" — that last one is emphatically fixed,
  and well: `client_ip` reads the Nth entry from the *right* with a documented trust model
  (`app/services/rate_limit.py:108-132`).
- `ARCHITECTURE.md:163` — matches' canonical ordering is "a **comment, not a CHECK constraint**".
  `ck_matches_user_order` exists (#23, `app/models/match.py:23`).
- `ARCHITECTURE.md:166-167` and `:59-61` — reports' `reported_user_id` "is `CASCADE`" (it is `SET NULL`,
  #24) and premium users have "**no cap at all**" (`_PREMIUM_REGEN_LIMIT = 100`, #9).

GAPS.md is scrupulous about marking what changed; these two are not, and they are the documents someone
reaches for at 2am. Fix: a pass over both against `main`. An hour or two, mechanical.

### 65. ~~The seed still identifies bots by email prefix rather than `is_bot`~~ ✅ FIXED (c01ce96)

`scripts/seed_demo_users.py:323` selects rows to delete with `User.email.like("demo%@howl.app")`. #15
closed exactly this class of bug in `app/api/swipes.py` — "Demo detection by email prefix … Any real
user who registers `demo.something@…` gets bot auto-match behavior. The `is_bot` column already exists —
use it." The last email-prefix identification in the codebase is in the script with the most destructive
effect: a real person who signs up as `demo42@howl.app` has their account, matches and messages deleted
on the next deploy.

Whether that address is registrable depends on whether `howl.app` is yours and accepts signups at
arbitrary local parts, which I could not determine from the repo — so the exposure is conditional, but
the fix is unconditional and it is one line: filter on `User.is_bot.is_(True)`. Best done together with
#39, which removes the delete entirely.

### 66. ~~`TRUSTED_PROXY_HOPS` cannot actually be configured~~ ✅ FIXED (8063246)

`app/services/rate_limit.py:36`:

```python
TRUSTED_PROXY_HOPS: int = int(getattr(settings, "trusted_proxy_count", 1))
```

The comment is honest that `app/config.py` "does not declare the field yet, so the getattr fallback is
what actually applies today" — so this is a documented rough edge rather than a bug. The reason to close
it is that the value being wrong is not a small failure. Put a second proxy in front (Cloudflare in front
of Railway is the obvious one) and `parts[-1]` becomes the CDN's egress address, which every user shares:
the IP bucket then locks the **entire application** out of login after 10 attempts in 15 minutes. The
operator's natural response — set `TRUSTED_PROXY_COUNT=2` — silently does nothing, and depending on
pydantic-settings' `extra` behaviour for `.env` keys may instead fail at import. I did not verify which,
and that is itself the argument for declaring the field: `trusted_proxy_count: int = 1` in `Settings`,
read directly. Two lines.

### 67. ~~The mobile client appends WebSocket messages without ordering; the web client sorts by id~~ ✅ FIXED (13e9f5f)

`frontend/src/App.jsx:160-164` rebuilds the message list through a `Map` keyed by id and sorts by id, so
it is idempotent and order-independent. `mobile/app/(app)/chat/[matchId].tsx:150-156` dedupes on
`seenIdsRef` and then does `setMessages((prev) => [...prev, msg])` — arrival order, never sorted.

I could not construct a case where this misorders today, and I want to be clear about that: Redis pub/sub
preserves order per publisher, the reader task is single, and consecutive sends from one client are
serialised by the client. The exposure is the two `background_tasks.add_task(manager.broadcast, …)`
callbacks from two concurrent `POST /messages` requests, which are independent coroutines with no
ordering guarantee between them, and #45's fix would add a second publisher (the Celery worker) whose
ordering relative to the web replicas is genuinely unconstrained. So this is latent, not live — and it
is another instance of the #32 pattern where the same logic exists twice and one copy is better.

Fix: sort by id in the mobile reducer, matching the web client. One line, and it should land with #45.

---

## Areas I checked thoroughly and found clean

- **`app/services/pubsub.py`** — the best-engineered file in the repo. Origin stamping genuinely prevents
  double delivery; the reconcile-every-iteration loop genuinely repairs a subscribe issued while Redis
  was down; the event-loop-affinity reset is a real problem correctly solved; the send lock covers the
  right thing and correctly does not hold the read. The fail-open policy is documented, deliberate, and
  matches the precedent it cites. My only criticisms of the chat layer land in `chat.py` (#46, #59, #60),
  not here.
- **`app/api/swipes.py` concurrency.** I went through this looking for a hole after #14 and did not find
  one. The conditional-UPDATE quota (`_consume_swipe_quota`) is genuinely atomic, the SAVEPOINT recovery
  in `_insert_swipe` and `_get_or_create_match` is correct, `undo_last_swipe` ordering by `id` and
  deciding on `rowcount` is right, and the comments explaining *why* each is shaped that way are accurate.
  The client-side bug in #50 is not this file's fault.
- **`client_ip` / `X-Forwarded-For`** — reads the Nth entry from the right with a correct trust model
  (#26 is properly closed here, whatever RUNBOOK still says). My #66 is about configurability, not the
  algorithm.
- **`app/services/rate_limit.py` bucket design** — per-action buckets so filling login does not block
  password reset, IP checked before email so a limited request cannot probe account existence, the
  no-TTL edge case handled. Nothing to add beyond the missing `/api/reports` caller in #53.
- **`app/tasks/bot_response.py` prompt-injection mitigations** (#5) — the three claimed defences are all
  actually present and the index validation is genuinely bounded at both ends. `_response_text` correctly
  filters block types and the `stop_reason == "max_tokens"` check exists. My #51 is about scheduling, not
  the prompt.
- **Report retention after #24** — all three FKs really are `SET NULL`, and account deletion really does
  remove the deleting user's own personal data (users row, swipes, matches, messages, blocks, push
  tokens, refresh tokens all cascade) while retaining only `reason`/`notes`/`created_at`. I looked
  specifically for something that now survives deletion and shouldn't and found nothing: `notes` is
  reporter-authored free text about someone else, which is the point of keeping it. There is no
  data-export path, but there is also no jurisdictional claim in the repo that requires one, so I am not
  filing it as a gap.
- **`_to_out` / soft-deleted message content** — `content` is nulled for both parties on every read path
  (`chat.py:249`, `:227`), including in the broadcast event. Consistent.
- **`get_db`'s rollback** (#23) — correct, and the reason it matters is correctly stated.
- **`test_shared_device_reassigns_its_push_token`** — pins the behaviour #23 defended. My #57 is a
  different objection to the same code and does not require regressing it.
- **`frontend` and `mobile` error boundaries and the `api()` result type** — #13 and #34 are properly
  closed. `mobile/src/api/client.ts` returns `{ok}` values, call sites check them, and the timeout and
  refresh paths are real.
- **CI coverage of the client suites** — `frontend/package.json` uses `vitest run`, not watch, so the web
  job cannot hang CI. Checked because it is a common way for a new CI to be quietly broken.

---

## Round three — new findings (2026-08-09)

Three gaps that did not exist or were not visible when #38–#67 were written. Numbering continues.

### 68. `POST /api/auth/change-email` has no UI on either client

The endpoint landed today (`4a624ba`) as the repair path email-verification enforcement was missing:
`email` was editable nowhere, so a typo at signup became a permanent lockout once the 72-hour grace
window closed. It is authenticated, requires the current password, re-issues verification to the new
address and warns the old one.

**No client calls it.** `ProfileUpdate` still has no `email` field, the web profile screen has no
control for it, and neither does mobile — which does now have `forgot-password` and `reset-password`
screens, so the omission is specifically this one. The practical position is that the recovery path
exists and is reachable only with `curl`, which means for an actual user it does not exist.

Severity is P1 rather than P2 because it is the *recovery* path for a hard failure. The operator kill
switch (`ENFORCE_EMAIL_VERIFICATION=false`) is still the only remedy a support request can apply, and it
is global — turning verification off for everyone to unstick one typo.

Fix: an "Change email" control on the profile screen of both clients, taking the new address and the
current password, and surfacing the 403 (wrong password), 409 (already registered) and 200 states. Half
a day across both clients. Worth pairing with a `PATCH /api/profile/me` rejection message that points at
it, since that is where a user will look first.

### 69. The web client's accessibility was never audited the way mobile's was

GAPS #34 closed mobile accessibility — `mobile/app/(app)/discover.tsx` alone carries five
`accessibilityLabel`s. Nothing equivalent was ever done for the web client, and it is the more
feature-complete of the two.

`aria-label` appears in exactly four web components (`EmailVerificationBanner`, `MessageComposer`,
`PreferenceFilters`, `ProfileView`). It appears in none of `DiscoverView`, `ChatView`, `MatchesView`,
`MessageList`, `Nav`, `LoginView` or `RegisterView`. The swipe buttons — the app's primary interaction —
are `<button>❌</button>` and `<button>❤️</button>` with a `title` attribute and nothing else, so a
screen reader announces the emoji. `title` is a tooltip, not an accessible name substitute, and it is
not exposed on touch at all.

I noticed this while writing a test that needed `getByRole('button', { name: /like/i })` and could not
find one; the test uses `getByTitle` instead, which is the sort of workaround that quietly encodes the
defect. Fix: an `aria-label` pass over the interactive elements in those seven components, then switch
the tests to role-and-name queries so the labels stay honest. A few hours.

### 70. Nothing enforces the WebSocket event contract between the server and the two clients

Not hypothetical — it failed today, and the failure mode is the reason this is worth an entry.

The server (#49) settled on
`{"type":"messages_read","match_id":…,"reader_id":…,"last_read_message_id":…,"read_at":…}`. The mobile
client, written in parallel against a description rather than the code, assumed `user_id` and
`up_to_message_id`. Nothing anywhere detects that: the frame arrives, `JSON.parse` succeeds, the branch
matches on `type`, no field matches, no error is raised, and the ✓✓ that both clients already render
simply never appears. It is indistinguishable from the server not sending the event — which is exactly
the bug #49 was fixing. It was caught by hand, by diffing one agent's report against another's code.

The exposure is structural. Three codebases share this wire format; the shapes live in
`app/api/chat.py`'s `_msg_event` / `broadcast_read_receipt`, in `frontend/src/App.jsx`'s `onmessage`,
and in `mobile/src/hooks/useMatchWebSocket.ts`'s `WsEvent` union. There is no shared schema, no
generated types, and no test that asserts a server-produced frame is accepted by either client. Note
`tests/test_packaging.py` already enforces byte-identity on the two clients' shared *constants* — the
precedent for mechanically enforcing a cross-codebase contract exists, and this is the same class of
drift, applied to the more dangerous surface.

Fix, cheapest useful version: a fixtures file of real server-emitted frames — generated by a backend
test from `_msg_event` and friends, committed as JSON — that both client suites load and assert their
reducers handle. That catches a renamed field on the next run in whichever codebase changed. The fuller
version is generating client types from the FastAPI schema, which is a bigger commitment than the
problem currently justifies.
