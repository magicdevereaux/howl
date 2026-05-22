# Howl 🐺

AI-powered dating platform. Write a bio, Claude assigns you a spirit animal, DALL-E generates your avatar, and you swipe on other members to find your match.

## Screenshots

### Login Page
![Login](screenshots/login.png)

### Profile & Spirit Animal
![Profile](screenshots/profile-deer.png)

### Browse Other Users
![Browse](screenshots/browse.png)

### Matches
![Matches](screenshots/matches.png)

## Features

- **AI Personality Analysis** — Claude (Anthropic) analyzes your bio to assign a spirit animal, personality traits, and an avatar description
- **AI Avatar Images** — DALL-E 3 generates a custom avatar image; falls back gracefully to emoji when the API key is absent or generation fails
- **Tinder-Style Swiping** — single-card discover stack with Like / Pass / Undo; server-side preference filtering by gender, sexuality, looking_for, and age range
- **Matching** — mutual likes create a match; unmatch removes the conversation and restores discoverability; block prevents future matching from either side
- **Real-Time Chat** — WebSocket-based messaging (FastAPI native); read receipts, typing indicators, message soft-delete, cursor-based pagination, unread badge on nav
- **Email Verification** — verification token generated on registration and logged to console in dev mode; verification endpoint marks account as verified; unverified banner shown on profile
- **Abuse Reporting** — report profiles or individual messages with a reason and optional notes; Block & Report combines both actions from the chat header
- **Daily Swipe Limit** — free users get 20 swipes per 24-hour window; premium users are unlimited; counter resets automatically; friendly UI when limit is reached
- **Monthly Regeneration Limit** — free users get 1 manual avatar regeneration per 30-day window; bio-update-triggered regenerations are excluded from the quota; premium unlimited
- **Brute-Force Protection** — Redis-backed rate limiting on login: 10 attempts per 15 minutes per IP, 5 per email; returns 429 with Retry-After header; fails open if Redis is unavailable
- **Demo Auto-Match** — 100 diverse pre-seeded demo users (varied gender, sexuality, age 18–65, preferences) automatically like back real users 90% of the time after a configurable delay
- **Password Reset** — time-limited token (1 hour); link logged to stdout in dev mode, ready to swap for SendGrid/SES
- **Account Deletion** — GDPR-compliant self-service deletion removes all user data, matches, messages, refresh tokens, and avatar image files
- **Email Notifications** — Celery task notifies recipients of new messages when inactive for 5+ minutes; per-user opt-out toggle in profile
- **Preference Filtering** — discover view has dropdowns for gender, sexuality, looking_for, and age range; saved server-side, applied to discover results; opt-in (null = show everyone)
- **Sentry Integration** — error monitoring and performance tracing (optional; omit DSN to disable)
- **Production-Ready** — JWT access tokens + database-backed refresh tokens, bcrypt, rate limiting, Celery background tasks

## Tech Stack

**Backend:**
- FastAPI (Python web framework)
- PostgreSQL (database)
- Alembic (17 migrations, all reversible)
- Celery (async task queue)
- Redis (Celery broker + login rate limiting)
- Anthropic Claude Haiku (spirit animal generation)
- OpenAI DALL-E 3 (avatar image generation, optional)

**Frontend:**
- React 18
- Vite (build tool)
- Inline CSS (no Tailwind)

## How It Works

1. User registers → verification email logged to console → can log in immediately
2. User writes a bio → Celery task calls Claude → returns spirit animal, personality traits, DALL-E prompt
3. DALL-E generates an avatar image saved to `static/avatars/`; emoji fallback if unavailable
4. User navigates to **Discover** and sets preference filters; swipes on the filtered stack
5. Mutual likes create a match; demo users auto-like back 90% of the time after a delay
6. Matched users chat over WebSocket; typing indicators, read receipts, and message deletion all work in real time

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose (for PostgreSQL + Redis)
- Anthropic API key
- OpenAI API key *(optional — enables DALL-E avatar images)*

### Installation

1. Clone the repo:
```bash
git clone https://github.com/magicdevereaux/howl.git
cd howl
```

2. Create virtual environment:
```bash
python -m venv .venv
source .venv/Scripts/activate  # Windows
# source .venv/bin/activate    # Mac/Linux
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create `.env` (see `.env.example` for all options):
```bash
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql://howl:howl@localhost:5432/howl
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key-here

# Optional
OPENAI_API_KEY=sk-proj-...
FRONTEND_URL=http://localhost:3000
SENTRY_DSN=https://...@sentry.io/...
```

5. Start infrastructure:
```bash
docker compose up -d
```

6. Run migrations:
```bash
alembic upgrade head
```

7. *(Optional)* Seed demo users:
```bash
python -m scripts.seed_demo_users
```
Inserts 100 diverse demo users with pre-generated spirit animals. Safe to re-run.

### Running the App

**Terminal 1 — FastAPI:**
```bash
python -m uvicorn app.main:app --port 8001 --reload
```

**Terminal 2 — Celery Worker:**
```bash
python -m celery -A app.celery_app worker --loglevel=info --pool=solo
```

**Terminal 3 — Frontend:**
```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:3000 (frontend) or http://localhost:8001/docs (API docs, debug mode only).

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Register; generates verification token |
| POST | `/api/auth/login` | Login (rate-limited by IP + email) |
| GET | `/api/auth/me` | Get current user |
| POST | `/api/auth/refresh` | Exchange refresh token for new access token |
| POST | `/api/auth/logout` | Revoke refresh token |
| POST | `/api/auth/verify-email` | Consume email verification token |
| POST | `/api/auth/forgot-password` | Request password reset link |
| POST | `/api/auth/reset-password` | Consume reset token, set new password |
| GET | `/api/profile/me` | Get current user profile |
| PATCH | `/api/profile/me` | Update name, age, location, bio, preferences |
| DELETE | `/api/profile/me` | Permanently delete account and all data |
| GET | `/api/profile/{id}` | Get any user's public profile |
| GET | `/api/avatar/status` | Check avatar generation status |
| POST | `/api/avatar/regenerate` | Manual regeneration (limited: 1/month free) |
| GET | `/api/users/browse` | List all users with ready avatars |
| GET | `/api/users/discover` | List unswiped users filtered by preferences |
| GET | `/api/users/matches` | List matches with unread count + last message |
| POST | `/api/swipes` | Record a like or pass (limited: 20/day free) |
| DELETE | `/api/swipes/last` | Undo the most recent swipe |
| DELETE | `/api/matches/{id}` | Unmatch (removes conversation, restores discoverability) |
| GET | `/api/matches/{id}/messages` | Fetch paginated conversation; marks incoming as read |
| POST | `/api/matches/{id}/messages` | Send a message (rate-limited: 10/60s) |
| DELETE | `/api/matches/{id}/messages/{msg_id}` | Soft-delete a sent message |
| GET | `/api/matches/{id}/unread-count` | Count unread messages |
| WS | `/api/matches/{id}/ws?token=JWT` | WebSocket for real-time delivery + typing |
| POST | `/api/blocks` | Block a user (removes match, prevents future matching) |
| DELETE | `/api/blocks/{user_id}` | Unblock a user |
| GET | `/api/blocks` | List blocked users |
| POST | `/api/reports` | Submit abuse report for a user or message |

Static avatar images are served at `/avatars/<filename>`.

## Architecture

```
┌─────────────┐
│   FastAPI   │ ← REST API + WebSocket + static file serving
└──────┬──────┘
       │
       ├──→ PostgreSQL
       │     users, swipes, matches, messages, blocks, reports,
       │     refresh_tokens, password_reset_tokens
       │
       ├──→ Redis
       │     Celery broker + login rate-limit counters
       │
       └──→ Celery Worker
             ├──→ Claude Haiku     (spirit animal + traits + DALL-E prompt)
             ├──→ DALL-E 3         (avatar image → static/avatars/)
             ├──→ auto_match task  (90% demo like-back after delay)
             └──→ notify task      (email on new message when inactive)

React Frontend (Vite)
  ├── polls /api/avatar/status every 3s during generation
  └── WebSocket /api/matches/{id}/ws for real-time chat
```

## Development

### Project Structure

```
howl/
├── app/
│   ├── api/
│   │   ├── auth.py         # register, login, refresh, logout, verify-email, forgot/reset-password
│   │   ├── profile.py      # GET/PATCH/DELETE /api/profile/me
│   │   ├── avatar.py       # status, regenerate (with monthly limit)
│   │   ├── swipes.py       # POST swipe (daily limit), DELETE undo, DELETE unmatch
│   │   ├── chat.py         # messages (paginated), WebSocket + typing, soft-delete, unread-count
│   │   ├── blocks.py       # block, unblock, list
│   │   ├── reports.py      # abuse reports
│   │   └── users.py        # browse, discover (preference-filtered), matches
│   ├── models/
│   │   ├── user.py         # User — all profile, preference, limit, and verification fields
│   │   ├── swipe.py        # Swipe (like/pass)
│   │   ├── match.py        # Match (canonical user1_id < user2_id)
│   │   ├── message.py      # Message (soft-delete via deleted_at)
│   │   ├── block.py        # Block
│   │   ├── report.py       # Report (reason enum, notes)
│   │   ├── refresh_token.py
│   │   └── password_reset_token.py
│   ├── schemas/
│   │   ├── user.py         # UserOut, ProfileUpdate, TokenOut
│   │   ├── avatar.py       # AvatarStatusOut
│   │   ├── browse.py       # BrowseUserOut
│   │   ├── swipe.py        # SwipeIn/Out, MatchOut, DiscoverUserOut, UndoSwipeOut
│   │   ├── chat.py         # MessageIn/Out, MessagePageOut, UnreadCountOut
│   │   └── block.py        # BlockIn, BlockedUserOut
│   ├── services/
│   │   ├── image_generation.py  # DALL-E 3 — generates + saves avatar image
│   │   ├── email.py             # Verification, password-reset, and message notification emails
│   │   └── rate_limit.py        # Redis-backed login rate limiter
│   ├── tasks/
│   │   ├── avatar.py       # generate_avatar — Claude then DALL-E
│   │   ├── auto_match.py   # auto_match_demo_user — 90% like-back
│   │   └── notify.py       # notify_new_message — email when recipient inactive
│   ├── celery_app.py
│   ├── config.py           # pydantic-settings; all env vars
│   ├── db.py
│   ├── dependencies.py     # get_current_user
│   ├── main.py             # FastAPI app, CORS, routers, static files, Sentry
│   └── security.py         # JWT, bcrypt, refresh token helpers
├── alembic/
│   └── versions/           # 17 migration files, all reversible
├── scripts/
│   ├── seed_demo_users.py          # 100 diverse demo users (idempotent)
│   ├── backfill_demo_matches.py    # Queue auto-match tasks for existing likes
│   └── startup.sh                  # Railway: migrate → seed → uvicorn
├── docs/
│   └── decisions/ADR.md    # Architecture decision records
├── tests/                  # 342 tests, all passing
│   ├── conftest.py         # SQLite StaticPool + FK enforcement
│   ├── test_auth.py
│   ├── test_profile.py
│   ├── test_avatar.py
│   ├── test_task.py
│   ├── test_users.py
│   ├── test_swipes.py
│   ├── test_chat.py              # includes WebSocket broadcast tests
│   ├── test_auto_match.py
│   ├── test_backfill.py
│   ├── test_image_generation.py
│   ├── test_account_deletion.py
│   ├── test_password_reset.py
│   ├── test_blocks.py
│   ├── test_reports.py
│   ├── test_notify.py
│   ├── test_preferences.py
│   ├── test_rate_limit.py
│   ├── test_swipe_limit.py
│   ├── test_regen_limit.py
│   └── test_email_verification.py
├── frontend/
│   ├── src/
│   │   ├── App.jsx         # All state, handlers, routing
│   │   ├── utils.js        # API_URL, WS_URL, animalEmoji, avatarUrl
│   │   └── components/
│   │       ├── Nav.jsx
│   │       ├── LoginView.jsx
│   │       ├── RegisterView.jsx
│   │       ├── ProfileView.jsx
│   │       ├── DiscoverView.jsx
│   │       ├── MatchesView.jsx
│   │       ├── ChatView.jsx
│   │       ├── PasswordReset.jsx
│   │       ├── LegalPage.jsx
│   │       └── ReportModal.jsx
│   └── package.json
├── static/avatars/         # Generated avatar images (auto-created)
├── .env.example
├── railpack.json
├── docker-compose.yml
├── requirements.txt
└── README.md
```

### Scripts

**Seed 100 demo users (idempotent):**
```bash
python -m scripts.seed_demo_users
# Output: gender/looking_for/age distribution summary
```

**Backfill auto-match tasks for likes that predated the feature:**
```bash
python -m scripts.backfill_demo_matches            # queue tasks
python -m scripts.backfill_demo_matches --dry-run  # preview only
```

### Running Tests

Tests use SQLite in-memory with FK enforcement — no Docker, Postgres, Redis, or API keys required.

```bash
pytest                                        # run everything
pytest --cov=app --cov-report=term-missing   # with coverage
pytest tests/test_chat.py -v                 # single file
pytest tests/test_swipe_limit.py::test_premium_user_can_swipe_beyond_limit -v
```

**Test layout:**

| File | What it covers |
|------|----------------|
| `test_auth.py` | Register, login, refresh/logout, rate limiting wired up |
| `test_profile.py` | Profile GET/PATCH, name/age/location/bio validation, avatar side-effects |
| `test_avatar.py` | Avatar status, manual regenerate — all states and stale handling |
| `test_task.py` | `generate_avatar` Celery task — Claude parsing, retries, DALL-E integration |
| `test_users.py` | Browse endpoint |
| `test_swipes.py` | POST swipe, undo, discover, matches list, unmatch cascade |
| `test_chat.py` | Messages CRUD, pagination, soft-delete, read receipts, WebSocket auth + broadcast |
| `test_auto_match.py` | `auto_match_demo_user` task and dispatch |
| `test_backfill.py` | Backfill script eligibility and dry-run |
| `test_image_generation.py` | DALL-E service — success, all failure modes |
| `test_account_deletion.py` | DELETE /api/profile/me, cascade, avatar file cleanup |
| `test_password_reset.py` | Token generation, expiry, one-time-use |
| `test_blocks.py` | Block/unblock, discover filtering both directions, unmatch |
| `test_reports.py` | Profile and message-level reporting, validation |
| `test_notify.py` | Activity check, opt-out, dispatch from send_message |
| `test_preferences.py` | Field validation, discover age + gender filtering |
| `test_rate_limit.py` | IP limit, email limit, ordering, fail-open on Redis error |
| `test_swipe_limit.py` | 20/day limit, reset after 24h, premium bypass |
| `test_regen_limit.py` | 1/month limit, reset after 30 days, bio updates excluded |
| `test_email_verification.py` | Token generation, expiry, verify endpoint, reuse blocked |

**Total: 342 tests, all passing.**

## Deployment (Railway)

`scripts/startup.sh` runs on every deploy:
1. `alembic upgrade head` — applies pending migrations
2. Seeds demo users (skip with `SKIP_SEED=true`)
3. Starts uvicorn

**Required environment variables:**
```
DATABASE_URL
REDIS_URL
SECRET_KEY
ANTHROPIC_API_KEY
ALLOWED_ORIGINS          # comma-separated frontend origins
```

**Optional:**
```
OPENAI_API_KEY           # enables DALL-E avatar images
FRONTEND_URL             # base URL for email links (default: http://localhost:3000)
SENTRY_DSN               # enables Sentry error monitoring
ENVIRONMENT              # reported to Sentry (default: production)
SKIP_SEED=true           # skip demo user seeding on deploy
```

> **Note on avatar persistence:** Avatar images are saved to `static/avatars/` on the server filesystem, which is ephemeral on Railway and cleared on every redeploy. For production persistence, configure an object storage bucket (S3, Cloudflare R2) and update `app/services/image_generation.py`.

## Freemium Model

| Feature | Free | Premium |
|---------|------|---------|
| Swipes per day | 20 | Unlimited |
| Avatar regenerations | 1 / month | Unlimited |
| Chat | ✅ | ✅ |
| Matches | ✅ | ✅ |

Premium (`is_premium` flag on the user) is set directly in the database for now — payment processing is not yet implemented.

## Roadmap

- [x] React frontend with component-based architecture
- [x] Real-time avatar status updates
- [x] Browse and discover users
- [x] Preference-based filtering in discover
- [x] 100 diverse demo users with auto-match
- [x] DALL-E 3 avatar image generation
- [x] Tinder-style swiping, matching, unmatch, block
- [x] WebSocket chat with typing indicators, read receipts, message deletion
- [x] Abuse reporting system
- [x] Password reset
- [x] Email verification
- [x] Account deletion (GDPR)
- [x] JWT refresh tokens
- [x] Login rate limiting (Redis)
- [x] Daily swipe limit + monthly regeneration limit
- [x] Email notifications with opt-out
- [x] Sentry error monitoring
- [x] Privacy policy and terms of service
- [ ] Payment processing (Stripe) to unlock premium
- [ ] Persistent avatar image storage (S3/R2)
- [ ] Geographic filtering (requires geocoding)
- [ ] Push notifications
- [ ] Mobile responsive improvements

## License

MIT

## Author

Nathan — [GitHub](https://github.com/magicdevereaux)
