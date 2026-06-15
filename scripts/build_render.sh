#!/usr/bin/env bash
set -o errexit
set -o nounset
set -o pipefail

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/check_env.py --phase build
python manage.py collectstatic --noinput

if [[ "${RUN_MIGRATIONS_DURING_BUILD:-false}" == "true" ]]; then
  python scripts/wait_for_database.py
  python manage.py migrate --noinput
else
  echo "Skipping database migrations during build. Set RUN_MIGRATIONS_DURING_BUILD=true only after DATABASE_URL is valid."
fi
