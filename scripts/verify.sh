#!/usr/bin/env sh
set -eu

if [ -x .venv/bin/ruff ]; then
  RUFF=.venv/bin/ruff
  MYPY=.venv/bin/mypy
  PYTEST=.venv/bin/pytest
else
  RUFF=ruff
  MYPY=mypy
  PYTEST=pytest
fi

"$RUFF" check backend
"$MYPY" backend
"$PYTEST"

if [ -d frontend/node_modules ]; then
  npm --prefix frontend run check
  npm --prefix frontend run build
  npm --prefix frontend audit --audit-level=high
fi

if [ -d auth-service/node_modules ]; then
  npm --prefix auth-service run check
  npm --prefix auth-service run build
  npm --prefix auth-service audit --audit-level=high
fi

if [ -d docs/node_modules ]; then
  npm --prefix docs run build
  npm --prefix docs audit --audit-level=high
fi

KYRON_ENV_FILE=.env.example \
    docker compose -f deploy/docker-compose.yml --env-file .env.example config --quiet
