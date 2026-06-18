# Deploy Render cho Guilua

App hiện tại deploy bằng FastAPI + Gunicorn/Uvicorn.

## Render Commands

```text
Build Command: bash scripts/build_render.sh
Start Command: bash scripts/start_render.sh
Health Check Path: /healthz/
```

## Biến môi trường tối thiểu

Set các biến sau trong Render service:

```text
APP_ENV=production
DEBUG=false
SECRET_KEY=<secret riêng dài hơn 32 ký tự>
USE_SQLITE=true
SESSION_COOKIE_SECURE=true
RUN_MIGRATIONS_DURING_BUILD=false
ADMIN_NOTIFICATION_EMAIL=panjiaphu@gmail.com
ADMIN_LINE_ID=@827sxbki
ADMIN_PHONE=0906938893
ADMIN_SEED_EMAIL=panjiaphu@gmail.com
ADMIN_SEED_PASSWORD=<mật khẩu admin tạm thời tối thiểu 14 ký tự>
```

Với cấu hình trên, app chạy SQLite để smoke UI nhanh. Với production thật nên
dùng PostgreSQL để dữ liệu không phụ thuộc vào filesystem của web service:

```text
USE_SQLITE=false
DATABASE_URL=<PostgreSQL URL hợp lệ>
RUN_MIGRATIONS_DURING_BUILD=true
```

`scripts/start_render.sh` sẽ chạy `alembic upgrade head` lúc runtime rồi mới bật
Gunicorn. Như vậy build không chết vì database host lỗi, nhưng app vẫn có bảng
database khi start.

## Email notification

Set SMTP khi muốn gửi email thật:

```text
SMTP_HOST=<smtp host>
SMTP_PORT=587
SMTP_USERNAME=<smtp username>
SMTP_PASSWORD=<smtp password>
SMTP_FROM_EMAIL=<email gửi đi>
SMTP_USE_TLS=true
```

Hiện app có email queue và SMTP sender. Email hai chiều đầy đủ vẫn cần thêm
mailbox inbound hoặc webhook để nhận email reply từ member.

## Live exchange rate

Optional:

```text
EXCHANGE_RATE_PROVIDER_URL=https://example.com/rates.json
```

Provider JSON kỳ vọng format:

```json
{
  "TWD_VND": {"buy_rate": 805.5, "sell_rate": 805.5},
  "USDT_TWD": {"buy_rate": 32.1, "sell_rate": 32.45}
}
```

Không commit secret thật vào repo.
