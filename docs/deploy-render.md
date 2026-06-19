# Deploy Render cho Guilua

App deploy bằng FastAPI + Gunicorn/Uvicorn.

## Render Commands

```text
Build Command: bash scripts/build_render.sh
Start Command: bash scripts/start_render.sh
Health Check Path: /healthz/
```

## Env tối thiểu

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
ADMIN_SEED_PASSWORD=<mật khẩu admin mạnh tối thiểu 14 ký tự>
MEMBER_REGISTRATION_ENABLED=false
MEMBER_PORTAL_ENABLED=false
```

Nếu Render báo lỗi `ADMIN_SEED_PASSWORD must be at least 14 characters in production`,
đổi `ADMIN_SEED_PASSWORD` sang mật khẩu mạnh dài tối thiểu 14 ký tự. Không dùng
`pp11223344`.

## Trạng thái public hiện tại

- Trang chủ chỉ hiển thị bảng tham khảo tỷ giá.
- Đăng ký thành viên đang tạm khóa.
- Member portal đang tạm khóa.
- Admin dashboard vẫn dùng để cập nhật `Giá mua` và `Giá bán`.

## Database

SQLite phù hợp để smoke UI nhanh:

```text
USE_SQLITE=true
```

Production lâu dài nên dùng PostgreSQL:

```text
USE_SQLITE=false
DATABASE_URL=<PostgreSQL URL hợp lệ>
RUN_MIGRATIONS_DURING_BUILD=true
```

`scripts/start_render.sh` luôn chạy `alembic upgrade head` khi service start.

## SMTP và webhook email

Các biến này chỉ cần khi bật email thật:

```text
SMTP_HOST=<smtp host>
SMTP_PORT=587
SMTP_USERNAME=<smtp username>
SMTP_PASSWORD=<smtp password>
SMTP_FROM_EMAIL=<email gửi đi>
SMTP_USE_TLS=true
EMAIL_WEBHOOK_API_KEY=<secret riêng cho inbound email webhook>
```

## Provider IP

Module IP vẫn còn trong codebase nhưng member portal đang tạm khóa. Khi pháp lý
cho phép bật lại, cấu hình provider bằng:

```text
IP_SERVICE_PROVIDER_URL=https://provider.example.com/provision
IP_SERVICE_PROVIDER_API_KEY=<provider api key>
IP_SERVICE_PROVIDER_TIMEOUT_SECONDS=5
```

Key provider phải lấy từ dashboard nhà cung cấp VPN/proxy/IP rotation. Không commit
key vào GitHub và không gửi key cho member.
