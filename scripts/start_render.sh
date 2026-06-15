#!/usr/bin/env bash
set -o errexit
set -o nounset
set -o pipefail

python scripts/check_env.py --phase runtime

if [[ "${USE_SQLITE:-false}" != "true" ]]; then
  python scripts/wait_for_database.py
fi

python manage.py migrate --noinput
gunicorn config.wsgi:application --log-file -
