# Deploy Render cho Guilua

App hien tai deploy bang FastAPI + Gunicorn/Uvicorn:

```text
Build Command: bash scripts/build_render.sh
Start Command: bash scripts/start_render.sh
Health Check Path: /healthz/
```

## Cau hinh khuyen nghi

Environment variables toi thieu:

```text
APP_ENV=production
DEBUG=false
SECRET_KEY=<tao secret rieng dai hon 32 ky tu>
USE_SQLITE=true
SESSION_COOKIE_SECURE=true
RUN_MIGRATIONS_DURING_BUILD=false
ADMIN_SEED_EMAIL=<admin email>
ADMIN_SEED_PASSWORD=<mat khau tam thoi toi thieu 14 ky tu>
```

Voi cau hinh tren, app chay SQLite de smoke UI nhanh. Khi can du lieu ben vung,
tao PostgreSQL hop le roi doi:

```text
USE_SQLITE=false
DATABASE_URL=<postgres URL hop le>
RUN_MIGRATIONS_DURING_BUILD=true
```

`scripts/start_render.sh` se chay `alembic upgrade head` luc runtime roi moi bat
Gunicorn. Nhu vay build khong chet vi database host loi, nhung app van co bang
database khi start.

Email optional:

```text
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=no-reply@your-domain
ADMIN_NOTIFICATION_EMAIL=admin@your-domain
```

Live rate optional:

```text
EXCHANGE_RATE_PROVIDER_URL=https://example.com/rates.json
```

Provider JSON dang ky vong format:

```json
{
  "TWD_VND": {"buy_rate": 805.5, "sell_rate": 805.5},
  "USDT_TWD": {"buy_rate": 32.1, "sell_rate": 32.45}
}
```

Khong commit secret that vao repo.

## Lenh local

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```
