#!/usr/bin/env bash
set -e

# Migrations and the demo-user seed used to run here, once per replica — see
# GAPS-ROUND-2 #56 for why that's unsafe with more than one replica (a race
# on Alembic's DDL, and on the seed's `users.email` unique constraint). They
# now run exactly once per deploy in scripts/predeploy.sh, wired up as
# Railway's preDeployCommand in railway.json. This script's only job is to
# start the server.

echo "==> Starting server..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
