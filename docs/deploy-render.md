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
EMAIL_WEBHOOK_API_KEY=<secret riêng cho inbound email webhook>
```

Nếu Render báo lỗi `ADMIN_SEED_PASSWORD must be at least 14 characters in production`,
hãy đổi biến `ADMIN_SEED_PASSWORD` trong Render Environment sang mật khẩu mạnh hơn.
Ví dụ format hợp lệ: chữ hoa, chữ thường, số, ký tự đặc biệt và dài tối thiểu
14 ký tự. Không dùng lại mật khẩu ngắn như `pp11223344`.

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

App có email queue, SMTP sender và inbound webhook để nhận email reply từ member.
Provider email cần forward inbound mail về:

```text
POST /webhooks/email-reply
Header: X-Guilua-Webhook-Key: <EMAIL_WEBHOOK_API_KEY>
Content-Type: application/json
```

Payload tối thiểu:

```json
{
  "from": "member@example.com",
  "to": "support@guilua.example",
  "subject": "Re: GL202606180001",
  "text": "Nội dung phản hồi của member"
}
```

Nếu subject hoặc body có mã yêu cầu `GL...`, app sẽ tự gắn reply vào giao dịch tương ứng.

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

## Dịch vụ chuyển IP

App đã có member service page, bảng `service_requests`, admin review, endpoint cấp
cho member và email notification. Phần tự động cấp VPN/proxy/IP thật chưa được
kết nối; khi có provider, nên thêm worker/service riêng để gọi API provider và
ghi `assigned_endpoint` sau khi admin duyệt.

Provider API có thể cấu hình bằng:

```text
IP_SERVICE_PROVIDER_URL=https://provider.example.com/provision
IP_SERVICE_PROVIDER_API_KEY=<provider api key>
IP_SERVICE_PROVIDER_TIMEOUT_SECONDS=5
```

Khi admin chuyển yêu cầu dịch vụ sang `Đã duyệt` hoặc `Đã hoàn thành` mà chưa
nhập endpoint thủ công, app sẽ gọi provider URL. Provider nên trả JSON có một
trong các field: `endpoint`, `assigned_endpoint`, `proxy_url`, `vpn_profile_url`.
