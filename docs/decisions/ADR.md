# Architecture Decision Records

This document captures the key technical decisions made in Howl and the reasoning behind them. Each record is written for an engineer reading the codebase for the first time who wants to understand *why* it is built the way it is, not just *what* it does.

---

## ADR-001: Celery for background tasks instead of FastAPI's built-in background tasks

**Status:** Accepted

### Context

Avatar generation requires two sequential API calls — Claude (spirit animal analysis, ~2s) followed by DALL-E 3 (image generation, ~10–15s). This work cannot block an HTTP response: the client would time out, and any transient failure would surface directly to the user with no retry opportunity.

FastAPI ships a `BackgroundTasks` mechanism that schedules a coroutine to run after a response is sent. It requires no additional infrastructure and works well for fire-and-forget operations like sending a webhook or writing an audit log.

### Decision

Use Celery with Redis as the broker instead of FastAPI's built-in `BackgroundTasks`.

### Reasoning

FastAPI's background tasks run in the same process and event loop as the web server. This means:

- **No retries.** If the Claude or DALL-E call fails, the exception is lost. There is no built-in mechanism to re-queue the work.
- **No persistence.** If the server restarts mid-generation (deploy, crash, OOM kill), the task is silently dropped. The user's avatar is stuck in `pending` forever.
- **No worker isolation.** A spike in avatar requests blocks request handling in the same process, since the GIL and the event loop compete for the same thread.

Celery solves all three: tasks are persisted in Redis before a worker picks them up, `max_retries=3` with backoff is a one-line decorator, and workers run as a completely separate process so web server throughput is unaffected.

The cost is real: Redis must be running, the Celery worker must be running, and deployments have two moving parts instead of one. For a project this size that is an acceptable tradeoff — the retry and persistence guarantees matter more than operational simplicity.

### Consequences

- The `generate_avatar` task retries up to 3× on Claude API errors before marking the avatar `failed`.
- A stale-detection mechanism (`avatar_status_updated_at` timestamp + 2-minute threshold) handles the edge case where a worker dies after accepting a task but before completing it. The frontend surfaces a "Try Again" button.
- The auto-match feature (`auto_match_demo_user`) uses the same Celery infrastructure to simulate delayed responses from demo users, with configurable countdown via `apply_async(countdown=N)`.

---

## ADR-002: Redis as the Celery broker

**Status:** Accepted

### Context

Celery requires a message broker to pass tasks from the web process to worker processes. The two common choices at this scale are RabbitMQ and Redis.

### Decision

Use Redis as both the broker and the result backend.

### Reasoning

RabbitMQ is the more capable broker — it supports complex routing, dead-letter queues, and message acknowledgement semantics that Celery can exploit. For a project with two task types (avatar generation, auto-match) and no routing requirements, that capability is overhead, not benefit.

Redis is already a reasonable dependency for a project that might add caching or rate limiting later (the chat rate limiter already queries the database — Redis could replace that). Running one stateful service instead of two reduces operational surface area on Railway.

The downside is that Redis is not a durable message queue. In the default configuration, an unacked task can be lost if Redis restarts without persistence enabled. This is acceptable here because tasks are re-triggerable: a user can click "Regenerate" if their avatar generation never completes, and the backfill script handles orphaned demo-user likes.

### Consequences

- `task_acks_late=True` and `worker_prefetch_multiplier=1` are set in `celery_app.py` to reduce (but not eliminate) the window for task loss on worker crash.
- If this project were to add payment processing or any task where exactly-once delivery matters, the broker choice would need revisiting.

---

## ADR-003: JWT for authentication instead of sessions

**Status:** Accepted

### Context

The frontend is a Vite/React SPA deployed on Vercel; the backend API is deployed separately on Railway. Session-based auth (server-side session store, session cookie) requires the API to maintain state and the browser to send cookies cross-origin.

### Decision

Issue stateless JWT access tokens on login/register, store them in `localStorage`, and require `Authorization: Bearer <token>` on all protected endpoints.

### Reasoning

JWTs eliminate the need for a session store entirely. The token encodes the user ID, is signed with `SECRET_KEY`, and is verified on every request by decoding it — no database round-trip. For a read-heavy API (discover users, fetch messages) this matters.

Cross-origin cookies require `SameSite=None; Secure` and careful CORS configuration that can behave differently across browsers. Bearer tokens are straightforward: the frontend sets one header and every endpoint works regardless of origin.

### Tradeoffs acknowledged

`localStorage` is readable by any JavaScript on the page, making these tokens vulnerable to XSS. `httpOnly` cookies are not accessible to JavaScript and are the more secure option. The decision to use `localStorage` was made for development simplicity, and is a known gap documented in the audit.

Token revocation is also not possible without a server-side blocklist. Logging out only clears the token from `localStorage`; the token remains technically valid until its 30-minute expiry. This is acceptable for a dating app but would not be acceptable for a banking or healthcare application.

Password reset tokens are separate single-use database records with a 1-hour expiry, not JWTs, because they require revocability (used flag) that a stateless JWT cannot provide.

### Consequences

- `app/security.py` wraps `python-jose` for signing/verifying and `bcrypt` for password hashing.
- The `get_current_user` dependency decodes the token and loads the user in one place, used by every protected endpoint.
- Account deletion immediately removes the user row; the JWT remains signed but `get_current_user` will 401 on the next request because the user no longer exists in the database.

---

## ADR-004: HTTP polling for chat instead of WebSockets

**Status:** Accepted (v1), expected to change

### Context

Chat messages need to appear on the recipient's screen without them manually refreshing. The two realistic options were WebSockets (persistent bidirectional connection) and short polling (repeated GET requests on a timer).

### Decision

Poll `GET /api/matches/{id}/messages` every 3 seconds while the chat view is open.

### Reasoning

FastAPI has first-class WebSocket support. WebSockets would give lower latency and eliminate unnecessary requests. The reason polling was chosen is operational simplicity at this stage:

- WebSockets require handling connection lifecycle (connect, disconnect, reconnect on network change), broadcasting to the correct recipients, and managing connection state. On a stateless Railway deployment with potential horizontal scaling, this requires a pub/sub layer (Redis Pub/Sub or a dedicated WebSocket server).
- Polling requires none of this. The messages endpoint is a standard authenticated GET that already exists for loading chat history. The 3-second interval is imperceptible to users and the load is negligible at this scale.

The 3-second poll also doubles as the read-receipt mechanism: fetching messages marks incoming ones as read, which is the correct behavior when the user has the chat open.

### Consequences

- Every open chat tab fires ~20 requests per minute. At 100 concurrent chat sessions this is 2,000 req/min against a single Railway instance — still well within FastAPI's throughput, but it scales linearly with active users in a way WebSockets do not.
- The polling interval is hardcoded at 3 seconds in `App.jsx`. It is a single constant that would need to become dynamic or be replaced entirely when WebSockets are adopted.
- This is listed as a known gap in the README roadmap.

---

## ADR-005: PostgreSQL as the primary database

**Status:** Accepted

### Context

The data model has five related tables (users, swipes, matches, messages, password_reset_tokens) with foreign key constraints, cascade deletes, and a canonical ordering invariant on matches (`user1_id < user2_id`). The query patterns include subqueries (filtering swiped users from discover), multi-table joins (matches with last message), and range comparisons (token expiry).

### Decision

Use PostgreSQL as the production database.

### Reasoning

The relational structure and the constraint requirements (unique constraints on swipe pairs, canonical match ordering, cascade deletes) are a natural fit for a relational database. PostgreSQL enforces these at the storage layer, which means application bugs cannot create orphaned records or duplicate matches.

PostgreSQL's `ON DELETE CASCADE` is relied on directly: deleting a user row cascades through swipes → matches → messages in a single statement, which is both simpler and more reliable than orchestrating deletes in application code.

SQLite was evaluated and rejected for production because it does not enforce foreign keys by default (requiring `PRAGMA foreign_keys = ON` on every connection), has limited support for concurrent writes, and lacks native `RETURNING` support in older versions. These limitations are acceptable in tests but not in production.

### Consequences

- Alembic manages migrations. The current chain has 9 migration files, each reversible.
- The ORM layer uses SQLAlchemy 2.0's `Mapped[]` / `mapped_column` typed API throughout. Column types map to PostgreSQL native types (`Enum`, `DateTime(timezone=True)`, `JSON`).
- Enum columns (`avatar_status`, `swipe_direction`) are created as PostgreSQL native enum types. The downgrade path for the swipes migration explicitly drops the type: `op.execute("DROP TYPE IF EXISTS swipe_direction")`.

---

## ADR-006: SQLite in-memory for the test suite

**Status:** Accepted

### Context

The test suite needs a database. The options were: use a real PostgreSQL instance (via Docker or a test container), or use a compatible in-memory database.

### Decision

Use SQLite with `StaticPool` (a single shared in-memory connection) via SQLAlchemy. Foreign key enforcement is enabled explicitly via `PRAGMA foreign_keys = ON` on every connection.

### Reasoning

The primary goal was that `pytest` should run on any machine without Docker, Postgres, or any external service. A contributor should be able to clone the repo and run `pytest` immediately. This is achieved with SQLite.

`StaticPool` is required because SQLite's `:memory:` databases are connection-scoped: each new connection gets an empty database. Without `StaticPool`, `Base.metadata.create_all()` would write the schema to one connection while every `Session` opened a different, empty connection. `StaticPool` forces all connections to reuse the same underlying DBAPI connection, so the schema and test data persist across the session.

The `PRAGMA foreign_keys = ON` event listener was added after discovering that SQLite silently ignores FK constraints (including `ON DELETE CASCADE`) by default. Without it, cascade-delete tests pass against SQLite while testing nothing — the cascades only fired in PostgreSQL. The pragma is set once via `@event.listens_for(engine, "connect")`.

### Tradeoffs acknowledged

SQLite is not PostgreSQL. Specific divergences that affect this codebase:

- `DateTime(timezone=True)` columns are stored as naive strings in SQLite; comparisons with timezone-aware Python datetimes raise `TypeError`. The password reset endpoint normalizes this: `if expires_at.tzinfo is None: expires_at = expires_at.replace(tzinfo=timezone.utc)`.
- SQLite does not support `DROP TYPE` or native enum types. The Alembic migration that drops `swipe_direction` guards this with `IF EXISTS`.
- Concurrent write behavior differs entirely. Tests that would expose write contention (two workers racing to create a match) cannot be validated in SQLite.

These are known and accepted. The test suite covers application logic and HTTP contract; the database-specific behavior (connection pooling, concurrent writes, enum type handling) is deferred to staging/production validation.

### Consequences

- 200 tests run in under 90 seconds with no external dependencies.
- The `conftest.py` engine fixture is session-scoped (schema created once) while the `db` fixture is function-scoped (rows deleted after each test). This gives per-test isolation without paying the cost of recreating the schema for every test.
- Any future test that requires PostgreSQL-specific behavior (e.g., `RETURNING`, advisory locks, full-text search) should use `pytest-docker` or a test container and be marked with a `@pytest.mark.postgres` skip condition for local runs.
