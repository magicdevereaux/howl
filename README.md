# Howl

AI-powered dating app where users get animal-human hybrid avatars.

## Stack

- **API**: FastAPI + Uvicorn
- **DB**: PostgreSQL + SQLAlchemy 2 + Alembic
- **Cache / Queue broker**: Redis + Celery
- **AI**: Anthropic Claude (avatar generation, matching)
- **Auth**: JWT via python-jose + passlib/bcrypt

## Getting started

```bash
# 1. Start backing services
docker compose up -d

# 2. Create virtualenv and install deps
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 3. Copy env and fill in secrets
cp .env.example .env

# 4. Run migrations
alembic upgrade head

# 5. Start dev server
uvicorn app.main:app --reload
```

API docs available at http://localhost:8000/docs (dev only).

## Project layout

```
app/
  main.py        # FastAPI app factory + CORS
  config.py      # Settings loaded from .env via pydantic-settings
  models/        # SQLAlchemy ORM models
  api/           # Route handlers (add routers here)
  services/      # Business logic
  tasks/         # Celery tasks
alembic/         # DB migrations
```

## Common commands

```bash
# Generate a new migration
alembic revision --autogenerate -m "describe change"

# Apply migrations
alembic upgrade head

# Roll back one step
alembic downgrade -1

# Run Celery worker
celery -A app.tasks worker --loglevel=info
```
