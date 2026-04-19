# Howl 🐺

AI-powered dating platform that analyzes your personality and matches you with your spirit animal.

## Screenshots

### Login Page
![Login](screenshots/login.png)

### Profile & Spirit Animal
![Profile](screenshots/profile-wolf.png)

### Dynamic Regeneration
![Snake](screenshots/profile-snake.png)

## Features

- **AI Personality Analysis**: Claude (Anthropic) analyzes dating bios to determine spirit animals
- **Async Task Processing**: Celery + Redis for background AI generation
- **Real-time Updates**: Frontend polls for status changes every 3 seconds
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
- Modern CSS with gradients

## How It Works

1. User registers and writes a dating bio
2. Background task picks up the request
3. Claude API analyzes personality traits
4. System returns spirit animal + traits + avatar description
5. User sees their match in real-time!
6. User can regenerate by updating their bio

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
3. Write your bio
4. Watch Claude analyze your personality!
5. See your spirit animal appear
6. Update bio to regenerate

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

#### Update bio (triggers avatar generation):
```bash
curl -X PATCH http://localhost:8001/api/profile/me \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"bio":"A lone wolf who loves midnight runs and howling at the moon."}'
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
  "animal": "wolf"
}
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Register new user |
| POST | `/api/auth/login` | Login existing user |
| GET | `/api/profile/me` | Get current user profile |
| PATCH | `/api/profile/me` | Update bio (triggers avatar) |
| GET | `/api/avatar/status` | Check avatar generation status |

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
│   ├── api/          # API routes (auth, profile, avatar)
│   ├── models/       # Database models (User)
│   ├── schemas/      # Pydantic schemas (validation)
│   ├── tasks/        # Celery tasks (avatar generation)
│   ├── config.py     # Settings & environment
│   └── main.py       # FastAPI app
├── frontend/
│   ├── src/
│   │   └── App.jsx   # React app
│   └── package.json  # Frontend dependencies
├── screenshots/      # UI screenshots
├── docker-compose.yml
├── requirements.txt
└── README.md
```
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
pytest tests/test_auth.py -v
```

**Run a single test by name:**
```bash
pytest tests/test_task.py::test_successful_generation -v
```

**Test layout:**

| File | What it covers |
|------|----------------|
| `tests/test_auth.py` | `/api/auth/register`, `/api/auth/login`, `/api/auth/me` |
| `tests/test_profile.py` | `/api/profile/me` (GET & PATCH), `/api/profile/{id}` |
| `tests/test_avatar.py` | `/api/avatar/status` — all avatar states |
| `tests/test_task.py` | `generate_avatar` Celery task — Claude parsing, retries, failures |

## Roadmap

- [x] React frontend with beautiful UI
- [x] Real-time status updates
- [ ] Avatar image generation (DALL-E/Midjourney)
- [ ] Matching algorithm (compatible spirit animals)
- [ ] Chat system
- [ ] Deployment (Heroku/Railway)
- [ ] Mobile responsive improvements

## License

MIT

## Author

Nathan - [GitHub](https://github.com/magicdevereaux)