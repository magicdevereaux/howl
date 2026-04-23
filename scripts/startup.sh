#!/usr/bin/env bash
set -e  # exit immediately if migrations fail

echo "==> Running database migrations..."
alembic upgrade head

if [ "${SKIP_SEED}" = "true" ]; then
    echo "==> SKIP_SEED=true — skipping demo user seeding."
else
    echo "==> Seeding demo users..."
    # Soft failure: seed errors must not prevent the server from starting.
    python -m scripts.seed_demo_users || echo "WARNING: seed script failed — continuing anyway."
fi

echo "==> Starting server..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
