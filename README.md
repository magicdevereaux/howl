# Howl 🐺

AI-powered dating platform. Write a bio, Claude determines your spirit animal, DALL-E generates your avatar, and you swipe on other members to find your match.

## Screenshots

### Login Page
![Login](screenshots/login.png)

### Profile & Spirit Animal
![Profile](screenshots/profile-wolf.png)

### Browse Other Users
![Browse](screenshots/browse.png)

## Features

- **AI Personality Analysis** — Claude (Anthropic) analyzes your bio to assign a spirit animal, personality traits, and an avatar description
- **AI Avatar Images** — DALL-E 3 generates a custom avatar image; falls back to emoji if the API key is absent or generation fails
- **Tinder-Style Swiping** — single-card discover stack with Like / Pass / Undo; preference filters (gender, sexuality, looking_for, age range) applied server-side from the discover view
- **Matching** — mutual likes create a match; unmatch removes the conversation and restores discoverability; block prevents future matching from either side
- **Real-Time Chat** — WebSocket-based messaging (FastAPI native); read receipts, message soft-delete, cursor-based pagination with load-more, unread badge on nav
- **Abuse Reporting** — report profiles or individual messages via a reason dropdown; stored for manual review; Block & Report combines both actions
- **Demo Auto-Match** — 100 diverse pre-seeded demo users (varied gender, sexuality, age, preferences) automatically like back real users 90% of the time
- **Password Reset** — time-limited token flow (1 hour); link logged to stdout in dev mode, ready to swap for SendGrid/SES
- **Account Deletion** — GDPR-compliant self-service deletion removes all user data, matches, messages, refresh tokens, and avatar files
- **Email Notifications** — Celery task notifies recipients of new messages when inactive for 5+ minutes; per-user opt-out toggle in profile
- **Preference Filtering** — filter discover results by gender, sexuality, looking_for, and age range; opt-in (null = show everyone)
- **Async Task Processing** — Celery + Redis for background AI generation, auto-match, and notification tasks
- **Stale Detection** — detects stuck generation tasks (>2 min) and offers a retry button
- **Production-Ready** — JWT access tokens + database-backed refresh tokens, bcrypt, rate limiting, Sentry error monitoring

## Tech Stack

**Backend:**
- FastAPI (Python web framework)
- PostgreSQL (database)
- Alembic (migrations)
- Celery (async task queue)
- Redis (message broker)
- Anthropic Claude Haiku (spirit animal generation)
- OpenAI DALL-E 3 (avatar image generation, optional)

**Frontend:**
- React 18
- Vite (build tool)
- Inline CSS (no Tailwind)

## How It Works

1. User registers and writes a dating bio
2. A Celery background task calls Claude, which returns the spirit animal, personality traits, and a DALL-E prompt
3. DALL-E 3 generates an avatar image from the prompt and saves it to `static/avatars/`
4. User sees their spirit animal and avatar appear in the profile view
5. User swipes on the Discover stack — mutual likes create a match
6. Demo users automatically like back after a short delay (simulated natural response time)
7. Matched users can open a chat conversation

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- Anthropic API key
- OpenAI API key *(optional — disabling it falls back to emoji avatars)*

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

4. Create `.env` file:
```bash
ANTHROPIC_API_KEY=your_anthropic_key
DATABASE_URL=postgresql://howl:howl@localhost:5432/howl
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your_secret_key_here

# Optional — enables DALL-E avatar image generation
OPENAI_API_KEY=your_openai_key

# Optional — base URL used in password-reset email links
FRONTEND_URL=http://localhost:3000
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
Inserts 100 diverse demo users (varied gender, sexuality, age 18–65, looking_for preferences) with pre-generated spirit animals. Safe to re-run — clears existing `demo*@howl.app` rows first.

### Running the App

**Terminal 1 — FastAPI:**
```bash
python -m uvicorn app.main:app --port 8001 --reload
```

**Terminal 2 — Celery Worker:**
```bash
python -m celery -A app.celery_app worker --loglevel=info --pool=solo
```

**Terminal 3 — Frontend (React/Vite):**
```bash
cd frontend
npm install  # first time only
npm run dev
```

**Then open:** http://localhost:3000 (frontend) or http://localhost:8001/docs (API docs, debug mode only)

## Usage

### Via Frontend

1. Open http://localhost:3000
2. Register an account
3. Fill in your name, age, location, and bio
4. Claude analyzes your bio and assigns your spirit animal; DALL-E generates an avatar
5. Navigate to **Discover** and start swiping
6. Check **Matches ❤️** to see who liked you back
7. Click a match card to open the chat

Password reset: click "Forgot password?" on the login page; the reset link is printed to the server console in dev mode.

### Via API (curl)

#### Register:
```bash
curl -X POST http://localhost:8001/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"wolf@howl.app","password":"test12345"}'
```

#### Update profile (name, age, location, bio):
```bash
curl -X PATCH http://localhost:8001/api/profile/me \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Jordan","age":28,"location":"San Francisco, CA","bio":"A lone wolf who loves midnight runs."}'
```

#### Check avatar status:
```bash
curl http://localhost:8001/api/avatar/status \
  -H "Authorization: Bearer YOUR_TOKEN"
```

```json
{
  "avatar_status": "ready",
  "animal": "wolf",
  "personality_traits": ["loyal", "independent", "nocturnal"],
  "avatar_description": "A silver wolf-human hybrid with piercing amber eyes...",
  "avatar_url": "/avatars/3f2a1b4c.png",
  "avatar_status_updated_at": "2026-04-21T00:00:00Z"
}
```

#### Swipe on a user:
```bash
curl -X POST http://localhost:8001/api/swipes \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_user_id":42,"direction":"like"}'
```

#### Send a message:
```bash
curl -X POST http://localhost:8001/api/matches/7/messages \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"Hey! Love your spirit animal."}'
```

#### Request a password reset:
```bash
curl -X POST http://localhost:8001/api/auth/forgot-password \
  -H "Content-Type: application/json" \
  -d '{"email":"wolf@howl.app"}'
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Register new user |
| POST | `/api/auth/login` | Login |
| GET | `/api/auth/me` | Get current user |
| POST | `/api/auth/refresh` | Exchange refresh token for new access token |
| POST | `/api/auth/logout` | Revoke refresh token |
| POST | `/api/auth/forgot-password` | Request password reset email |
| POST | `/api/auth/reset-password` | Consume reset token, set new password |
| GET | `/api/profile/me` | Get current user profile |
| PATCH | `/api/profile/me` | Update name, age, location, bio, preferences |
| DELETE | `/api/profile/me` | Permanently delete account and all data |
| GET | `/api/profile/{id}` | Get any user's public profile |
| GET | `/api/avatar/status` | Check avatar generation status |
| POST | `/api/avatar/regenerate` | Reset and re-queue avatar generation |
| GET | `/api/users/browse` | List all users with ready avatars |
| GET | `/api/users/discover` | List unswiped users filtered by preferences |
| GET | `/api/users/matches` | List matches with unread count + last message |
| POST | `/api/swipes` | Record a like or pass |
| DELETE | `/api/swipes/last` | Undo the most recent swipe |
| DELETE | `/api/matches/{id}` | Unmatch (removes conversation, restores discoverability) |
| GET | `/api/matches/{id}/messages` | Fetch paginated conversation; marks read |
| POST | `/api/matches/{id}/messages` | Send a message (rate-limited: 10/60s) |
| DELETE | `/api/matches/{id}/messages/{msg_id}` | Soft-delete a sent message |
| GET | `/api/matches/{id}/unread-count` | Count unread messages from the other user |
| WS | `/api/matches/{id}/ws?token=JWT` | WebSocket for real-time message delivery |
| POST | `/api/blocks` | Block a user (removes match, prevents future matching) |
| DELETE | `/api/blocks/{user_id}` | Unblock a user |
| GET | `/api/blocks` | List blocked users |
| POST | `/api/reports` | Submit abuse report for a user or message |

Static files (avatar images) are served at `/avatars/<filename>`.

## Architecture

```
┌─────────────┐
│   FastAPI   │ ← REST API + static file serving
└──────┬──────┘
       │
       ├──→ PostgreSQL
       │     users, swipes, matches, messages, password_reset_tokens
       │
       └──→ Celery Task Queue
             │
             ├──→ Redis (broker)
             │
             ├──→ Claude Haiku     (spirit animal + traits + DALL-E prompt)
             │
             └──→ DALL-E 3         (avatar image → saved to static/avatars/)

React Frontend (Vite)
  ├── polls /api/avatar/status every 3s during generation
  └── maintains a WebSocket connection to /api/matches/{id}/ws while chat is open
```

## Development

### Project Structure

```
howl/
├── app/
│   ├── api/
│   │   ├── auth.py         # register, login, refresh, logout, forgot/reset-password
│   │   ├── profile.py      # GET/PATCH/DELETE /api/profile/me
│   │   ├── avatar.py       # status, regenerate
│   │   ├── swipes.py       # POST swipe, DELETE undo, DELETE unmatch
│   │   ├── chat.py         # messages (paginated), WebSocket, soft-delete, unread-count
│   │   ├── blocks.py       # block, unblock, list blocks
│   │   ├── reports.py      # abuse reports
│   │   └── users.py        # browse, discover (preference-filtered), matches
│   ├── models/
│   │   ├── user.py                  # User (name, age, gender, sexuality, preferences…)
│   │   ├── swipe.py                 # Swipe (like/pass)
│   │   ├── match.py                 # Match (canonical user1_id < user2_id)
│   │   ├── message.py               # Message (with soft-delete deleted_at)
│   │   ├── block.py                 # Block
│   │   ├── report.py                # Report (reason enum, notes)
│   │   ├── refresh_token.py         # RefreshToken
│   │   └── password_reset_token.py  # PasswordResetToken
│   ├── schemas/
│   │   ├── user.py       # UserOut, ProfileUpdate, TokenOut
│   │   ├── avatar.py     # AvatarStatusOut
│   │   ├── browse.py     # BrowseUserOut
│   │   ├── swipe.py      # SwipeIn/Out, MatchOut, DiscoverUserOut, UndoSwipeOut
│   │   ├── chat.py       # MessageIn/Out, MessagePageOut, UnreadCountOut
│   │   └── block.py      # BlockIn, BlockedUserOut
│   ├── services/
│   │   ├── image_generation.py  # DALL-E 3 — generates + saves avatar image
│   │   └── email.py             # Password-reset + message notification emails (console in dev)
│   ├── tasks/
│   │   ├── avatar.py      # generate_avatar — calls Claude then DALL-E
│   │   ├── auto_match.py  # auto_match_demo_user — 90% like-back from demo users
│   │   └── notify.py      # notify_new_message — email when recipient is inactive
│   ├── celery_app.py
│   ├── config.py          # Settings & environment (pydantic-settings)
│   ├── db.py
│   ├── dependencies.py    # get_current_user
│   ├── main.py            # FastAPI app, CORS, routers, static files, Sentry
│   └── security.py        # JWT, bcrypt, refresh token helpers
├── alembic/
│   └── versions/          # 16 migration files
├── scripts/
│   ├── seed_demo_users.py          # Insert 100 diverse demo users (idempotent)
│   ├── backfill_demo_matches.py    # Queue auto-match tasks for existing likes
│   └── startup.sh                  # Railway entrypoint: migrate → seed → serve
├── docs/
│   └── decisions/
│       └── ADR.md         # Architecture decision records
├── tests/                          # 298 tests, all passing
│   ├── conftest.py
│   ├── test_auth.py
│   ├── test_profile.py
│   ├── test_avatar.py
│   ├── test_task.py
│   ├── test_users.py
│   ├── test_swipes.py
│   ├── test_chat.py           # includes WebSocket tests
│   ├── test_auto_match.py
│   ├── test_backfill.py
│   ├── test_image_generation.py
│   ├── test_account_deletion.py
│   ├── test_password_reset.py
│   ├── test_blocks.py
│   ├── test_reports.py
│   ├── test_notify.py
│   └── test_preferences.py
├── frontend/
│   ├── src/
│   │   ├── App.jsx            # State, handlers, routing
│   │   ├── utils.js           # API_URL, WS_URL, animalEmoji, avatarUrl
│   │   └── components/        # One file per view + shared components
│   └── package.json
├── static/
│   └── avatars/           # Generated avatar images (auto-created on startup)
├── railpack.json
├── docker-compose.yml
├── requirements.txt
└── README.md
```

### Scripts

**Seed demo users:**
```bash
python -m scripts.seed_demo_users
```
- Inserts `demo1@howl.app` … `demo10@howl.app` with pre-generated spirit animals
- `avatar_status = ready` so they appear immediately in Discover
- Safe to re-run (clears existing demo rows first)
- No Celery worker or API keys needed

**Backfill auto-match tasks:**
```bash
python -m scripts.backfill_demo_matches            # queue tasks
python -m scripts.backfill_demo_matches --dry-run  # preview only
```
Queues `auto_match_demo_user` tasks for any existing likes on demo users that pre-date the auto-match feature. Delays are spread randomly over 0–60 minutes.

### Running Tests

Tests use SQLite in-memory with FK enforcement enabled — no Docker, Postgres, Redis, or API keys required.

```bash
pytest
```

```bash
pytest --cov=app --cov-report=term-missing   # with coverage
```

```bash
pytest tests/test_swipes.py -v               # single file
pytest tests/test_task.py::test_successful_generation -v  # single test
```

**Test layout:**

| File | What it covers |
|------|----------------|
| `test_auth.py` | Register, login, `/me` |
| `test_profile.py` | Profile GET/PATCH, name/age/location/bio validation, avatar reset side-effects |
| `test_avatar.py` | Avatar status, regenerate — all states and stale handling |
| `test_task.py` | `generate_avatar` Celery task — Claude parsing, retries, DALL-E integration |
| `test_users.py` | Browse endpoint |
| `test_swipes.py` | POST swipe, undo, discover, matches list |
| `test_chat.py` | Messages CRUD, pagination, soft-delete, read receipts, rate limiting, WebSocket auth + broadcast |
| `test_auto_match.py` | `auto_match_demo_user` task and dispatch from swipe endpoint |
| `test_backfill.py` | Backfill script eligibility logic and dry-run |
| `test_image_generation.py` | DALL-E service — success path, all failure modes, task integration |
| `test_account_deletion.py` | DELETE /api/profile/me, cascade verification, avatar file cleanup |
| `test_password_reset.py` | forgot-password, reset-password, token expiry, one-time-use |
| `test_blocks.py` | Block, unblock, list; discover filtering; unmatch cascade |
| `test_reports.py` | Abuse report submission, validation, message-level reporting |
| `test_notify.py` | notify_new_message task — activity checks, opt-out, dispatch |
| `test_preferences.py` | Preference field validation; discover age + gender filtering |

**Total: 298 tests, all passing.**

## Deployment (Railway)

`scripts/startup.sh` runs automatically on every deploy:

1. `alembic upgrade head` — applies pending migrations
2. Seeds demo users (skipped if `SKIP_SEED=true`)
3. Starts uvicorn

Required Railway environment variables:

```
DATABASE_URL
REDIS_URL
SECRET_KEY
ANTHROPIC_API_KEY
OPENAI_API_KEY          # optional — enables DALL-E avatar images
ALLOWED_ORIGINS         # comma-separated list of frontend domains
FRONTEND_URL            # base URL for password-reset links
SENTRY_DSN              # optional — enables error monitoring
```

> **Note:** Avatar images are saved to `static/avatars/` on the Railway filesystem, which is ephemeral and cleared on redeploy. For persistent avatars, configure an object storage bucket (S3, Cloudflare R2) and update `app/services/image_generation.py`.

## Roadmap

- [x] React frontend with component-based architecture
- [x] Real-time avatar status updates
- [x] Browse and discover other users
- [x] Name, age, location, gender, sexuality, and preference fields
- [x] Preference-based filtering in discover
- [x] Demo seed data with 100 diverse users and auto-match
- [x] DALL-E 3 avatar image generation
- [x] Tinder-style swiping, matching, unmatch, block
- [x] WebSocket-based real-time chat
- [x] Message pagination, soft-delete, read receipts
- [x] Abuse reporting system
- [x] Password reset flow
- [x] Account deletion (GDPR)
- [x] JWT refresh tokens
- [x] Email notifications with opt-out
- [x] Sentry error monitoring
- [ ] Persistent avatar image storage (S3/R2)
- [ ] Push notifications
- [ ] Geographic filtering (requires geocoding)
- [ ] Mobile responsive improvements

## License

MIT

## Author

Nathan — [GitHub](https://github.com/magicdevereaux)
