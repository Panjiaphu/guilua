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
CRYPTO_MARKET_LIVE_ENABLED=true
CRYPTO_MARKET_CACHE_SECONDS=180
CRYPTO_MARKET_TIMEOUT_SECONDS=2.5
COINGECKO_API_URL=https://api.coingecko.com/api/v3/simple/price
BINANCE_API_URL=https://api.binance.com/api/v3/ticker/24hr
AI_AGENT_API_ENABLED=true
AI_AGENT_DEFAULT_POST_STATUS=draft
AI_AGENT_ALLOW_AUTOPUBLISH=false
UPLOAD_MAX_MB=5
UPLOAD_STORAGE_BACKEND=local
PUBLIC_BASE_URL=https://fumap-line-webhook.onrender.com
SHOPEE_AFFILIATE_DISCLOSURE_ENABLED=true
```

Nếu Render báo lỗi `ADMIN_SEED_PASSWORD must be at least 14 characters in production`,
đổi `ADMIN_SEED_PASSWORD` sang mật khẩu mạnh dài tối thiểu 14 ký tự. Không dùng
`pp11223344`.

## Trạng thái public hiện tại

- Trang chủ chỉ hiển thị bảng tham khảo tỷ giá.
- Đăng ký thành viên đang tạm khóa.
- Member portal đang tạm khóa.
- Admin dashboard vẫn dùng để cập nhật `Giá mua` và `Giá bán`.
- Trang `/crypto` hiển thị TradingView, macro filter và bảng coin realtime.

## Crypto API

Coin data lấy từ CoinGecko và Binance public endpoints. Nếu một API lỗi, trang
vẫn render bằng nguồn còn lại hoặc fallback.

Optional CoinGecko demo key:

```text
COINGECKO_API_KEY=<demo api key nếu có>
```

## Google AdSense

Tạo hoặc đăng nhập tài khoản tại `https://adsense.google.com/`, thêm site Render
của bạn và lấy publisher ID/slot ID. Sau đó set:

```text
GOOGLE_ADSENSE_CLIENT=ca-pub-xxxxxxxxxxxxxxxx
GOOGLE_ADSENSE_SLOT=<ad slot id>
GOOGLE_ADSENSE_PUBLISHER_ID=pub-xxxxxxxxxxxxxxxx
GOOGLE_SITE_VERIFICATION=<token nếu Google yêu cầu meta verification>
```

App sẽ:
- chèn AdSense script khi có `GOOGLE_ADSENSE_CLIENT`
- render ad slot trên `/crypto` khi có `GOOGLE_ADSENSE_SLOT`
- render `/ads.txt` từ `GOOGLE_ADSENSE_PUBLISHER_ID`
- chèn meta `google-site-verification` khi có `GOOGLE_SITE_VERIFICATION`

## AI Agent / content / utilities

Không set raw AI Agent key trong Render. Tạo key tại:

```text
/admin/ai-agents
```

API endpoints:

```text
GET /api/agent/health
POST /api/agent/posts/job
POST /api/agent/posts/shop
POST /api/agent/media
```

Auth:

```text
Authorization: Bearer <AI_AGENT_API_KEY>
X-AI-Agent-Key: <AI_AGENT_API_KEY>
```

Local upload trên Render chỉ phù hợp MVP. Nếu cần giữ file sau deploy/rebuild,
cần Render Disk hoặc storage ngoài như S3/Cloudinary.

VPN page chỉ hiện download/guide link nếu set:

```text
VPN_DOWNLOAD_URL=
VPN_SETUP_GUIDE_URL=
```

Google vẫn cần duyệt site trước khi quảng cáo thật hiển thị.

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
