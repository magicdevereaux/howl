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

- **AI Personality Analysis** — Claude (Anthropic) reads your bio and assigns a spirit animal, personality traits, and an avatar description
- **AI Avatar Images** — DALL-E 3 generates a custom avatar image; falls back gracefully to emoji when unavailable
- **Tinder-Style Swiping** — single-card discover stack with Like / Pass / Undo; server-side preference filtering by gender, sexuality, looking_for, and age range
- **Daily Swipe Limit** — free users get 20 swipes per 24-hour window; premium users unlimited; friendly UI when limit is reached
- **Profile Edit/Save/Cancel** — read-only profile view by default; edit mode with draft state, cancel to discard, save to apply; avatar auto-regenerates on bio change if slot available
- **Monthly Avatar Regeneration Limit** — 1 manual regeneration per 30-day window for free users; bio changes share the same quota; `profile_needs_regen` badge when avatar is out of sync with profile; countdown to next available slot
- **Matching** — mutual likes create a match; unmatch removes conversation and restores discoverability; block prevents future matching from either side
- **Real-Time Chat** — WebSocket-based messaging (FastAPI native); typing indicators, read receipts, message soft-delete, cursor-based pagination, unread badge on nav
- **Chat Profile Modal** — tap the avatar in the chat header to see the matched user's full profile including bio, traits, and spirit animal description
- **Abuse Reporting** — report profiles or individual messages; Block & Report combines both in one action; stored for manual review
- **Email Verification** — token generated on register, logged to console in dev mode; unverified banner on profile until confirmed
- **Password Reset** — time-limited token (1 hour); link logged to console in dev mode
- **Account Deletion** — GDPR-compliant self-service; removes all user data, matches, messages, tokens, and avatar files
- **Refresh Tokens** — database-backed 30-day refresh tokens; revoked on logout and account deletion
- **httpOnly Cookie Auth** — access and refresh tokens stored as httpOnly cookies (`samesite=none; secure` in production); no tokens in localStorage or JS memory; Vite proxy used in dev so the browser sees a single origin
- **Login Rate Limiting** — Redis-backed; 10 attempts per 15 min per IP, 5 per email; 429 with Retry-After header; fails open if Redis is unavailable
- **Demo Auto-Match** — 100 diverse pre-seeded demo users (varied gender, sexuality, age 18–65, preferences) automatically like back real users 90% of the time after a configurable delay
- **Email Notifications** — Celery task notifies matches of new messages when inactive for 5+ minutes; per-user opt-out toggle in profile
- **Preference Filtering** — gender, sexuality, looking_for, age range dropdowns in the discover view; saved to profile, applied server-side; opt-in (null = show everyone)
- **Privacy Policy & Terms of Service** — accessible from login/register pages
- **Sentry Integration** — optional error monitoring and performance tracing

## Tech Stack

**Backend:**
- FastAPI (Python)
- PostgreSQL (database)
- Alembic (18 migrations)
- Celery (async task queue)
- Redis (Celery broker + login rate limiting)
- Anthropic Claude Haiku (spirit animal generation)
- OpenAI DALL-E 3 (avatar image generation, optional)
- Sentry (error monitoring, optional)

**Frontend:**
- React 18
- Vite (build tool + dev proxy)
- Inline CSS (no Tailwind)

## How It Works

1. User registers → verification email logged to console → can log in immediately; httpOnly cookies set on response
2. User writes a bio → Celery task calls Claude → returns spirit animal, personality traits, and a DALL-E prompt
3. DALL-E generates an avatar image saved to `static/avatars/`; emoji fallback if unavailable
4. User navigates to **Discover**, sets preference filters, and swipes on the filtered stack (20 swipes/day free)
5. Mutual likes create a match; demo users auto-like back 90% of the time after a short delay
6. Matched users chat over WebSocket with typing indicators, read receipts, and soft-delete
7. Cookies are sent with every request via a centralized `fetchApi` wrapper; no token management in client code

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose (PostgreSQL + Redis)
- Anthropic API key
- OpenAI API key *(optional — enables DALL-E avatar images)*

### Installation

```bash
git clone https://github.com/magicdevereaux/howl.git
cd howl

python -m venv .venv
source .venv/Scripts/activate  # Windows
# source .venv/bin/activate    # Mac/Linux

pip install -r requirements.txt
```

Create `.env` (see `.env.example` for all options):
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

```bash
docker compose up -d
alembic upgrade head

# Optional: seed 100 diverse demo users
python -m scripts.seed_demo_users
```

### Running the App

```bash
# Terminal 1 — FastAPI backend
python -m uvicorn app.main:app --port 8001 --reload

# Terminal 2 — Celery worker
python -m celery -A app.celery_app worker --loglevel=info --pool=solo

# Terminal 3 — React frontend (Vite dev server with proxy to 8001)
cd frontend && npm install && npm run dev
```

Open http://localhost:3000. The Vite dev server proxies all `/api/*` requests to the FastAPI backend at port 8001, so httpOnly cookies work without any cross-origin complications in development.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Register; generates email verification token; sets auth cookies |
| POST | `/api/auth/login` | Login (rate-limited); sets auth cookies |
| GET | `/api/auth/me` | Get current user |
| POST | `/api/auth/refresh` | Exchange refresh-token cookie for new access-token cookie |
| POST | `/api/auth/logout` | Revoke refresh token, clear both cookies |
| POST | `/api/auth/verify-email` | Consume email verification token |
| POST | `/api/auth/forgot-password` | Request password reset link |
| POST | `/api/auth/reset-password` | Consume reset token, set new password |
| GET | `/api/profile/me` | Get own profile |
| PATCH | `/api/profile/me` | Update name, age, location, bio (bio auto-regenerates avatar if slot available) |
| DELETE | `/api/profile/me` | Permanently delete account and all data |
| GET | `/api/profile/{id}` | Get any user's public profile |
| GET | `/api/avatar/status` | Check avatar generation status |
| POST | `/api/avatar/regenerate` | Manual regeneration (1/month free, unlimited premium) |
| GET | `/api/users/browse` | All users with ready avatars |
| GET | `/api/users/discover` | Unswiped users filtered by preferences |
| GET | `/api/users/matches` | Matches with unread count + last message |
| POST | `/api/swipes` | Like or pass (20/day free, unlimited premium) |
| DELETE | `/api/swipes/last` | Undo the most recent swipe |
| DELETE | `/api/matches/{id}` | Unmatch (removes conversation, restores discoverability) |
| GET | `/api/matches/{id}/messages` | Paginated conversation history; marks incoming as read |
| POST | `/api/matches/{id}/messages` | Send a message (rate-limited: 10/60s) |
| DELETE | `/api/matches/{id}/messages/{msg_id}` | Soft-delete a sent message |
| GET | `/api/matches/{id}/unread-count` | Count unread messages |
| WS | `/api/matches/{id}/ws` | WebSocket for real-time delivery, typing indicators |
| POST | `/api/blocks` | Block a user |
| DELETE | `/api/blocks/{user_id}` | Unblock a user |
| GET | `/api/blocks` | List blocked users |
| POST | `/api/reports` | Submit abuse report for a user or message |

Avatar images are served at `/avatars/<filename>`.

## Architecture

```
┌─────────────┐
│   FastAPI   │ ← REST API + WebSocket + static files
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
             └──→ notify task      (email alert on new message when inactive)

React Frontend (Vite)
  ├── Vite proxy: /api/* → FastAPI:8001 (dev only; no CORS needed)
  ├── fetchApi() wrapper: credentials:include on every request
  ├── httpOnly cookies: access_token + refresh_token (no localStorage)
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
│   │   ├── profile.py      # GET/PATCH/DELETE /api/profile/me; auto-regen logic
│   │   ├── avatar.py       # status, regenerate (monthly limit + profile_needs_regen flag)
│   │   ├── swipes.py       # POST swipe (daily limit), DELETE undo, DELETE unmatch
│   │   ├── chat.py         # messages (paginated), WebSocket + typing, soft-delete, unread-count
│   │   ├── blocks.py       # block, unblock, list
│   │   ├── reports.py      # abuse reports
│   │   └── users.py        # browse, discover (preference-filtered), matches
│   ├── models/
│   │   ├── user.py         # User — profile, preferences, limits, verification, regen flag
│   │   ├── swipe.py        # Swipe (like/pass)
│   │   ├── match.py        # Match (canonical user1_id < user2_id)
│   │   ├── message.py      # Message (soft-delete via deleted_at)
│   │   ├── block.py        # Block
│   │   ├── report.py       # Report (reason enum, notes)
│   │   ├── refresh_token.py
│   │   └── password_reset_token.py
│   ├── schemas/
│   │   ├── user.py         # UserOut, ProfileUpdate, AuthOut (cookie auth — no tokens in body)
│   │   ├── avatar.py       # AvatarStatusOut
│   │   ├── browse.py       # BrowseUserOut
│   │   ├── swipe.py        # SwipeIn/Out, MatchOut, DiscoverUserOut, UndoSwipeOut
│   │   ├── chat.py         # MessageIn/Out, MessagePageOut, UnreadCountOut
│   │   └── block.py        # BlockIn, BlockedUserOut
│   ├── services/
│   │   ├── image_generation.py  # DALL-E 3 — generates + saves avatar image
│   │   ├── email.py             # Verification, password-reset, and message notification emails
│   │   └── rate_limit.py        # Redis-backed login rate limiter (fail-open on Redis errors)
│   ├── tasks/
│   │   ├── avatar.py       # generate_avatar — Claude then DALL-E
│   │   ├── auto_match.py   # 90% like-back from demo users after delay
│   │   └── notify.py       # email alert when recipient inactive 5+ min
│   ├── celery_app.py
│   ├── config.py           # pydantic-settings; all env vars
│   ├── db.py
│   ├── dependencies.py     # get_current_user — reads access_token from httpOnly cookie
│   ├── main.py             # FastAPI app, CORS (allow_credentials=True), routers, Sentry
│   └── security.py         # JWT, bcrypt, refresh token helpers
├── alembic/
│   └── versions/           # 18 migrations, all reversible
├── scripts/
│   ├── seed_demo_users.py          # 100 diverse demo users (idempotent)
│   ├── backfill_demo_matches.py    # Queue auto-match tasks for existing likes
│   └── startup.sh                  # Railway: migrate → seed → uvicorn
├── docs/
│   └── decisions/ADR.md    # Architecture decision records
├── tests/                  # 355 tests, all passing
│   ├── conftest.py         # SQLite StaticPool + FK enforcement + cookie-based auth_headers
│   ├── test_auth.py        # Cookie auth flow: register, login, refresh, logout
│   ├── test_profile.py
│   ├── test_profile_regen.py  # Auto-regen on save, profile_needs_regen flag
│   ├── test_avatar.py
│   ├── test_task.py
│   ├── test_users.py
│   ├── test_swipes.py
│   ├── test_swipe_limit.py    # 20/day limit, reset, premium bypass
│   ├── test_chat.py           # WebSocket broadcast, pagination, soft-delete
│   ├── test_auto_match.py
│   ├── test_backfill.py
│   ├── test_image_generation.py
│   ├── test_account_deletion.py
│   ├── test_password_reset.py
│   ├── test_email_verification.py
│   ├── test_blocks.py
│   ├── test_reports.py
│   ├── test_notify.py
│   ├── test_rate_limit.py     # IP + email rate limiting, Redis fail-open
│   ├── test_regen_limit.py    # 1/month limit, 30-day reset, premium bypass
│   └── test_preferences.py
├── frontend/
│   ├── src/
│   │   ├── App.jsx         # All state, handlers, routing
│   │   ├── utils.js        # API_URL, WS_URL, fetchApi (credentials:include wrapper), helpers
│   │   └── components/
│   │       ├── Nav.jsx           # Navigation + unread badge
│   │       ├── LoginView.jsx
│   │       ├── RegisterView.jsx
│   │       ├── ProfileView.jsx   # Read-only + edit mode, regen badge + countdown
│   │       ├── DiscoverView.jsx  # Swipe stack, preference filters, daily limit UI
│   │       ├── MatchesView.jsx   # Match cards with last message preview
│   │       ├── ChatView.jsx      # WebSocket chat, typing indicators, profile modal
│   │       ├── PasswordReset.jsx # Forgot + reset password flows
│   │       ├── LegalPage.jsx     # Privacy policy + terms of service
│   │       └── ReportModal.jsx   # Abuse report form
│   ├── vite.config.js      # Dev proxy /api/* → :8001 (enables cookies without CORS)
│   └── package.json
├── static/avatars/         # Generated avatar images (auto-created)
├── .env.example
├── railpack.json
├── docker-compose.yml
├── requirements.txt
└── README.md
```

### Running Tests

Tests use SQLite in-memory with FK enforcement — no Docker, Postgres, Redis, or API keys required. Auth is injected via `Cookie` header in the `auth_headers` fixture.

```bash
pytest                                        # run everything
pytest --cov=app --cov-report=term-missing   # with coverage
pytest tests/test_chat.py -v                 # single file
pytest tests/test_auth.py::test_login_success -v
```

**Test layout:**

| File | What it covers |
|------|----------------|
| `test_auth.py` | Cookie-based register, login, refresh, logout; rate limiting wired up |
| `test_profile.py` | GET/PATCH, field validation, avatar side-effects |
| `test_profile_regen.py` | Auto-regen on bio save, `profile_needs_regen` flag, quota sharing |
| `test_avatar.py` | Status, regenerate endpoint — all states, stale handling |
| `test_task.py` | `generate_avatar` Celery task — Claude parsing, retries, DALL-E |
| `test_users.py` | Browse endpoint |
| `test_swipes.py` | POST swipe, undo, discover, matches list, unmatch cascade |
| `test_swipe_limit.py` | 20/day limit, 24h reset, premium bypass |
| `test_chat.py` | Messages CRUD, pagination, soft-delete, WebSocket auth + broadcast |
| `test_auto_match.py` | `auto_match_demo_user` task and dispatch |
| `test_backfill.py` | Backfill script eligibility and dry-run |
| `test_image_generation.py` | DALL-E service — success, all failure modes |
| `test_account_deletion.py` | DELETE /api/profile/me, cascade, avatar file cleanup |
| `test_password_reset.py` | Token generation, expiry, one-time-use |
| `test_email_verification.py` | Token generation, expiry, verify endpoint, reuse blocked |
| `test_blocks.py` | Block/unblock, discover filtering both directions |
| `test_reports.py` | Profile and message-level reporting |
| `test_notify.py` | Activity check, opt-out, dispatch from send_message |
| `test_rate_limit.py` | IP + email limits, Retry-After header, Redis fail-open |
| `test_regen_limit.py` | 1/month limit, 30-day reset, bio-change quota sharing |
| `test_preferences.py` | Field validation, discover age + gender filtering |

**Total: 355 tests, all passing.**

## Deployment (Railway)

`scripts/startup.sh` runs on every deploy:
1. `alembic upgrade head`
2. Seeds demo users (skip with `SKIP_SEED=true`)
3. Starts uvicorn

**Required environment variables:**
```
DATABASE_URL
REDIS_URL
SECRET_KEY
ANTHROPIC_API_KEY
ALLOWED_ORIGINS          # comma-separated Vercel origins
```

**Optional:**
```
OPENAI_API_KEY           # enables DALL-E avatar images
FRONTEND_URL             # base URL for email links
SENTRY_DSN
ENVIRONMENT              # reported to Sentry (default: production)
SKIP_SEED=true           # skip demo seeding on deploy
```

### Auth in Production

Access and refresh tokens are stored as httpOnly cookies with `samesite=none; secure=true`. The Vercel frontend must be listed in `ALLOWED_ORIGINS` and the CORS middleware is configured with `allow_credentials=True`. Every fetch call in the frontend goes through the `fetchApi()` wrapper which sets `credentials: 'include'`.

> **Note on avatar persistence:** Avatar images are saved to `static/avatars/` which is ephemeral on Railway (cleared on redeploy). For production persistence, configure S3 or Cloudflare R2 and update `app/services/image_generation.py`.

## Freemium Model

| Feature | Free | Premium (`is_premium=true`) |
|---------|------|---------|
| Swipes per day | 20 | Unlimited |
| Avatar regenerations | 1 / 30 days | Unlimited |
| Chat | ✅ | ✅ |
| Matches | ✅ | ✅ |

Premium is set directly in the database — payment processing is not yet implemented.

## Roadmap

- [x] React frontend with component-based architecture
- [x] Spirit animal generation (Claude + DALL-E 3)
- [x] Tinder-style swiping, matching, unmatch, block
- [x] WebSocket chat with typing indicators, read receipts, message deletion
- [x] Profile edit/save/cancel with draft state
- [x] httpOnly cookie authentication (no tokens in JS)
- [x] Preference-based filtering in discover
- [x] Daily swipe limit + monthly regeneration limit
- [x] Profile-out-of-sync badge with regen countdown
- [x] Chat profile modal
- [x] Abuse reporting system
- [x] Email verification + password reset
- [x] Account deletion (GDPR)
- [x] Refresh tokens (database-backed, revocable)
- [x] Login rate limiting (Redis)
- [x] Email notifications with opt-out
- [x] 100 diverse demo users with auto-match
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
