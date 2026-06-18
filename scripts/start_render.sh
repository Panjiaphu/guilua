#!/usr/bin/env bash
set -o errexit
set -o nounset
set -o pipefail

python scripts/check_env.py --phase runtime

if [[ "${USE_SQLITE:-false}" != "true" ]]; then
  python scripts/wait_for_database.py
fi

alembic upgrade head
gunicorn app.main:app --worker-class uvicorn.workers.UvicornWorker --bind "0.0.0.0:${PORT:-8000}" --log-file -
