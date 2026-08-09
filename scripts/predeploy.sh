#!/usr/bin/env bash
set -e  # exit immediately if migrations fail

# Railway pre-deploy command (see railway.json: deploy.preDeployCommand).
#
# Pre-deploy commands run exactly once per deploy, in their own ephemeral
# container, between the build finishing and any replica of the app
# container starting or scaling up (docs.railway.com/deployments/pre-deploy-command).
# That is what makes this safe to run migrations and the demo-user seed from:
# with N replicas of the API service, none of them race each other or the
# migration, because none of them run this script at all any more —
# scripts/startup.sh now only execs uvicorn. See GAPS-ROUND-2 #56.

echo "==> Running database migrations..."
alembic upgrade head

if [ "${SKIP_SEED}" = "true" ]; then
    echo "==> SKIP_SEED=true — skipping demo user seeding."
else
    echo "==> Seeding demo users..."
    # Soft failure: the seed is cosmetic (bots to swipe on) and additive by
    # default (GAPS #39) — a seed failure must not block a deploy that is
    # otherwise fine.
    python -m scripts.seed_demo_users || echo "WARNING: seed script failed — continuing anyway."
fi

echo "==> Pre-deploy steps complete."
