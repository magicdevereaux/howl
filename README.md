# Howl 🐺

AI-powered dating platform that analyzes your personality and matches you with your spirit animal.

## Screenshots

### Login Page
![Login](screenshots/login.png)

### Profile & Spirit Animal
![Profile](screenshots/profile-wolf.png)

### Browse Other Users
![Browse](screenshots/browse.png)

## Features

- **AI Personality Analysis**: Claude (Anthropic) analyzes dating bios to determine spirit animals
- **Async Task Processing**: Celery + Redis for background AI generation
- **Real-time Updates**: Frontend polls for status changes every 3 seconds
- **Browse Other Users**: Card-based browse view showing spirit animal avatars
- **Stale Detection**: Automatically detects stuck generation tasks and offers a retry
- **Demo Seed Data**: 10 pre-seeded demo users across US cities with real bios and AI-generated spirit animals
- **Production-Ready**: JWT auth, retry logic, error handling, database persistence
- **Fast**: ~2 second response time for AI generation
- **Beautiful UI**: Modern React frontend with responsive design

## Tech Stack

**Backend:**
- FastAPI (Python web framework)
- PostgreSQL (database)
- Celery (async task queue)
- Redis (message broker)
- Anthropic Claude API (AI)

**Frontend:**
- React 18
- Vite (build tool)
- Modern CSS with gradients and inline styles

## How It Works

1. User registers and writes a dating bio
2. Background Celery task picks up the request
3. Claude API analyzes personality traits
4. System returns spirit animal + traits + avatar description
5. User sees their match in real-time
6. User can browse other members' spirit animal profiles

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- Anthropic API key

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
ANTHROPIC_API_KEY=your_api_key_here
DATABASE_URL=postgresql://howl:howl@localhost:5432/howl
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your_secret_key_here
```

5. Start infrastructure:
```bash
docker compose up -d
```

6. Run migrations:
```bash
alembic upgrade head
```

7. (Optional) Seed demo users:
```bash
python -m scripts.seed_demo_users
```
This inserts 10 demo users with pre-generated spirit animals so the Browse page
looks populated from day one. Safe to re-run — it clears existing demo rows first.

### Running the App

**Terminal 1 - FastAPI:**
```bash
python -m uvicorn app.main:app --port 8001 --reload
```

**Terminal 2 - Celery Worker:**
```bash
python -m celery -A app.celery_app worker --loglevel=info --pool=solo
```

**Terminal 3 - Frontend (React/Vite):**
```bash
cd frontend
npm install  # First time only
npm run dev
```

**Then open:** http://localhost:3000 (frontend) or http://localhost:8001/docs (API docs)

## Usage

### Via Frontend (Recommended)

1. Open http://localhost:3000
2. Create an account
3. Add your name and location (optional)
4. Write your bio
5. Watch Claude analyze your personality!
6. See your spirit animal appear
7. Browse other users with the **Browse ✨** button in the nav

### Via API (curl)

#### Register a user:
```bash
curl -X POST http://localhost:8001/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"wolf@howl.app","password":"test12345"}'
```

**Response:**
```json
{
  "access_token": "eyJhbGc...",
  "token_type": "bearer",
  "user": {...}
}
```

#### Update profile (name, location, bio):
```bash
curl -X PATCH http://localhost:8001/api/profile/me \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Jordan","location":"San Francisco, CA","bio":"A lone wolf who loves midnight runs."}'
```

#### Check avatar status:
```bash
curl http://localhost:8001/api/avatar/status \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "avatar_status": "ready",
  "animal": "wolf",
  "personality_traits": ["loyal", "independent", "nocturnal"],
  "avatar_description": "A silver wolf-human hybrid with piercing amber eyes...",
  "avatar_status_updated_at": "2026-04-21T00:00:00Z"
}
```

#### Browse other users:
```bash
curl http://localhost:8001/api/users/browse \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### Regenerate avatar (if stuck):
```bash
curl -X POST http://localhost:8001/api/avatar/regenerate \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Register new user |
| POST | `/api/auth/login` | Login existing user |
| GET | `/api/auth/me` | Get current user (token check) |
| GET | `/api/profile/me` | Get current user profile |
| PATCH | `/api/profile/me` | Update name, location, bio (bio triggers avatar) |
| GET | `/api/profile/{id}` | Get any user's public profile |
| GET | `/api/avatar/status` | Check avatar generation status |
| POST | `/api/avatar/regenerate` | Reset and re-queue avatar generation |
| GET | `/api/users/browse` | List other users with ready avatars |

## Architecture
```
┌─────────────┐
│   FastAPI   │ ← REST API
└──────┬──────┘
       │
       ├──→ PostgreSQL (user data)
       │
       └──→ Celery Task Queue
             │
             ├──→ Redis (broker)
             │
             └──→ Claude API (AI)
                       │
                       └──→ React Frontend (polling)
```

## Development

### Project Structure
```
howl/
├── app/
│   ├── api/
│   │   ├── auth.py       # Register, login, /me
│   │   ├── profile.py    # GET/PATCH profile, name/location/bio
│   │   ├── avatar.py     # Status, regenerate
│   │   └── users.py      # Browse endpoint
│   ├── models/
│   │   └── user.py       # User model (name, location, bio, animal, traits...)
│   ├── schemas/
│   │   ├── user.py       # UserOut, ProfileUpdate, TokenOut
│   │   ├── avatar.py     # AvatarStatusOut
│   │   └── browse.py     # BrowseUserOut (public fields only)
│   ├── tasks/
│   │   └── avatar.py     # Celery task — calls Claude, parses JSON, persists
│   ├── config.py         # Settings & environment
│   └── main.py           # FastAPI app, CORS, router registration
├── alembic/
│   └── versions/         # DB migrations
├── scripts/
│   └── seed_demo_users.py  # Seeds 10 demo users (idempotent)
├── tests/
│   ├── conftest.py       # SQLite in-memory fixtures
│   ├── test_auth.py      # Auth endpoint tests
│   ├── test_profile.py   # Profile GET/PATCH tests incl. name/location
│   ├── test_avatar.py    # Avatar status and regenerate tests
│   ├── test_users.py     # Browse endpoint tests
│   └── test_task.py      # Celery task unit tests
├── frontend/
│   ├── src/
│   │   └── App.jsx       # Single-file React app (login, profile, browse views)
│   └── package.json
├── docker-compose.yml
├── requirements.txt
└── README.md
```

### Seed Script

```bash
python -m scripts.seed_demo_users
```

- Inserts 10 demo users (`demo1@howl.app` … `demo10@howl.app`)
- All have pre-generated animal data, personality traits, and avatar descriptions
- `avatar_status = ready` so they appear immediately in Browse
- `avatar_url = null` — browse cards show large emoji placeholders until real image generation is added
- Safe to re-run: clears existing `demo*@howl.app` rows before inserting
- No Celery worker or API key needed — data is pre-written

### Running Tests

Tests use SQLite in-memory so they run without Docker, Postgres, Redis,
or a real Anthropic API key.

**Install test dependencies first (one-time):**
```bash
pip install -e ".[dev]"
```

**Run all tests:**
```bash
pytest
```

**Run with coverage (terminal output):**
```bash
pytest --cov=app --cov-report=term-missing
```

**Run with coverage + HTML report:**
```bash
pytest --cov=app --cov-report=term-missing --cov-report=html
```
Then open `htmlcov/index.html` in your browser to see a line-by-line
breakdown of which code is covered.

**Run a specific test file:**
```bash
pytest tests/test_users.py -v
```

**Run a single test by name:**
```bash
pytest tests/test_task.py::test_successful_generation -v
```

**Test layout:**

| File | What it covers |
|------|----------------|
| `tests/test_auth.py` | `/api/auth/register`, `/api/auth/login`, `/api/auth/me` |
| `tests/test_profile.py` | `/api/profile/me` (GET & PATCH), name/location/bio updates, avatar reset side-effects |
| `tests/test_avatar.py` | `/api/avatar/status`, `/api/avatar/regenerate` — all states, stale handling |
| `tests/test_users.py` | `/api/users/browse` — auth, filtering, field shape |
| `tests/test_task.py` | `generate_avatar` Celery task — Claude parsing, retries, failures |

Total: **75 tests**, all passing.

## Roadmap

- [x] React frontend with beautiful UI
- [x] Real-time status updates
- [x] Browse other users
- [x] Name and location on profiles
- [x] Demo seed data
- [ ] Avatar image generation (DALL-E/Midjourney)
- [ ] Matching algorithm (compatible spirit animals)
- [ ] Chat system
- [ ] Mobile responsive improvements

## License

MIT

## Author

Nathan - [GitHub](https://github.com/magicdevereaux)
