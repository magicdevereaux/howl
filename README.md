# Howl 🐺

AI-powered dating platform that analyzes your personality and matches you with your spirit animal.

## Features

- **AI Personality Analysis**: Claude (Anthropic) analyzes dating bios to determine spirit animals
- **Async Task Processing**: Celery + Redis for background AI generation
- **Production-Ready**: JWT auth, retry logic, error handling, database persistence
- **Fast**: ~2 second response time for AI generation

## Tech Stack

**Backend:**
- FastAPI (Python web framework)
- PostgreSQL (database)
- Celery (async task queue)
- Redis (message broker)
- Anthropic Claude API (AI)

**Frontend:** (coming soon)
- React

## How It Works

1. User registers and writes a dating bio
2. Background task picks up the request
3. Claude API analyzes personality traits
4. System returns spirit animal + traits + avatar description
5. User gets their match!

## Setup

### Prerequisites

- Python 3.11+
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

6. Run database migrations (if applicable):
```bash
# Add migration commands here
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

## Usage

### Register a user:
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

### Update bio (triggers avatar generation):
```bash
curl -X PATCH http://localhost:8001/api/profile/me \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"bio":"A lone wolf who loves midnight runs and howling at the moon."}'
```

### Check avatar status:
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
```

## Development

### Project Structure
```
howl/
├── app/
│   ├── api/          # API routes
│   ├── models/       # Database models
│   ├── schemas/      # Pydantic schemas
│   ├── tasks/        # Celery tasks
│   └── main.py       # FastAPI app
├── docker-compose.yml
├── requirements.txt
└── README.md
```

### Running Tests
```bash
pytest
```

## Roadmap

- [ ] React frontend
- [ ] Avatar image generation (DALL-E)
- [ ] Matching algorithm
- [ ] Chat system
- [ ] Deployment (Heroku/Railway)

## License

MIT

## Author

Nathan - [GitHub](https://github.com/magicdevereaux)