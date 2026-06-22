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
MEMBER_REGISTRATION_ENABLED=true
MEMBER_PORTAL_ENABLED=true
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
UPLOAD_IMAGE_MAX_WIDTH=1600
UPLOAD_IMAGE_QUALITY=82
PUBLIC_BASE_URL=https://fumap-line-webhook.onrender.com
SHOPEE_AFFILIATE_DISCLOSURE_ENABLED=true
```

Nếu Render báo lỗi `ADMIN_SEED_PASSWORD must be at least 14 characters in production`,
đổi `ADMIN_SEED_PASSWORD` sang mật khẩu mạnh dài tối thiểu 14 ký tự. Không dùng
`pp11223344`.

## Trạng thái public hiện tại

- Trang chủ hiển thị bảng tham khảo tỷ giá, crypto, jobs, shop và tiện ích.
- Đăng ký thành viên đang mở.
- Member portal đang mở cho tiện ích miễn phí.
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
- render ad slot trên home, jobs, shop, utilities, tool pages và `/crypto` khi có `GOOGLE_ADSENSE_SLOT`
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

Admin và AI Agent upload ảnh sẽ nén ảnh thành WebP và trả về URL public dưới
`/static/uploads/...`. Local upload trên Render chỉ phù hợp MVP vì filesystem
có thể mất file sau deploy/rebuild. Nếu cần giữ file bền cho sản phẩm thật,
cần Render Disk hoặc storage ngoài như S3/Cloudinary/R2.

VPN page chỉ hiện download/guide link nếu set:

```text
VPN_DOWNLOAD_URL=
VPN_SETUP_GUIDE_URL=
```

Shortlink hỗ trợ tự tạo mã hoặc nhập custom alias, ví dụ `guilua.com`
sẽ tạo đường dẫn `/s/guilua.com` trên domain đang deploy.

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

Module IP/VPN page hiện là MVP download/config link. Khi có provider thật, cấu hình bằng:

```text
IP_SERVICE_PROVIDER_URL=https://provider.example.com/provision
IP_SERVICE_PROVIDER_API_KEY=<provider api key>
IP_SERVICE_PROVIDER_TIMEOUT_SECONDS=5
```

Key provider phải lấy từ dashboard nhà cung cấp VPN/proxy/IP rotation. Không commit
key vào GitHub và không gửi key cho member.

## Env mới cho login, crypto analysis và firewall

Thêm các biến sau trong Render Environment:

```text
SESSION_REMEMBER_MAX_AGE_SECONDS=2592000
PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS=3600
SECURITY_DASHBOARD_ENABLED=true
SECURITY_LOGGING_ENABLED=true
SECURITY_FIREWALL_ENABLED=true
SECURITY_AUTO_BLOCK_ENABLED=false
SECURITY_LOG_RETENTION_DAYS=30
SECURITY_RATE_LIMIT_ENABLED=true
SECURITY_RATE_LIMIT_WINDOW_SECONDS=60
SECURITY_RATE_LIMIT_MAX_REQUESTS=120
SECURITY_LOGIN_RATE_LIMIT_WINDOW_SECONDS=300
SECURITY_LOGIN_RATE_LIMIT_MAX_ATTEMPTS=10
SECURITY_ADMIN_RATE_LIMIT_MAX_REQUESTS=80
SECURITY_AGENT_API_RATE_LIMIT_MAX_REQUESTS=60
SECURITY_AUTO_BLOCK_THRESHOLD=50
SECURITY_AUTO_BLOCK_MINUTES=60
SECURITY_GEOIP_ENABLED=true
SECURITY_GEOIP_PROVIDER=none
SECURITY_GEOIP_API_URL=
SECURITY_GEOIP_API_KEY=
SECURITY_GEOIP_CACHE_HOURS=24
SECURITY_IP_ALLOWLIST=
SECURITY_IP_BLOCKLIST=
SECURITY_COUNTRY_ALLOWLIST=
SECURITY_COUNTRY_BLOCKLIST=
SECURITY_TRUSTED_PROXY_HEADERS=true
SECURITY_NOTIFY_ON_HIGH_RISK=true
SECURITY_ALERT_EMAIL=
SECURITY_BLOCK_SUSPICIOUS_PAYLOADS=false
SECURITY_LOG_SUSPICIOUS_PAYLOADS=true
SECURITY_HONEYPOT_ENABLED=true
SECURITY_ADMIN_IP_RESTRICTION_ENABLED=false
SECURITY_ADMIN_IP_ALLOWLIST=
```

`SECURITY_GEOIP_PROVIDER=none` là cấu hình mặc định. Nếu muốn IP intelligence thật, dùng provider như IPinfo, ipapi, MaxMind web service hoặc IP2Location web service rồi set `SECURITY_GEOIP_API_URL` và `SECURITY_GEOIP_API_KEY` theo tài khoản provider. Không commit API key vào GitHub.

Ví dụ URL provider:

```text
# IPinfo
SECURITY_GEOIP_PROVIDER=ipinfo
SECURITY_GEOIP_API_URL=https://ipinfo.io/{ip}/json?token={key}
SECURITY_GEOIP_API_KEY=<ipinfo-token>

# ipapi, gói free thường không cần key
SECURITY_GEOIP_PROVIDER=ipapi
SECURITY_GEOIP_API_URL=https://ipapi.co/{ip}/json/
SECURITY_GEOIP_API_KEY=

# IPGeolocation
SECURITY_GEOIP_PROVIDER=ipgeolocation
SECURITY_GEOIP_API_URL=https://api.ipgeolocation.io/ipgeo?apiKey={key}&ip={ip}
SECURITY_GEOIP_API_KEY=<ipgeolocation-key>
```

AI Agent hỗ trợ thêm:

```text
POST /api/agent/posts/crypto_analysis
```

Allowed post types nên đặt:

```text
job,shop,crypto_analysis
```
