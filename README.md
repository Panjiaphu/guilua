# Guilua Finance Webapp

FastAPI webapp cho Guilua trong giai đoạn rà soát pháp lý.

Trạng thái hiện tại:
- Public UI hiển thị bảng tham khảo tỷ giá `TWD/VND`, `USDT/TWD`, crypto, tìm việc, shop và tiện ích.
- Public `/crypto` hiển thị TradingView, macro filter, bảng giá coin và 12 nhóm coin.
- Public `/jobs`, `/shop`, `/utilities`, `/advertising`, `/build-idea` cho webapp thương mại tham khảo.
- AI Agent API có API key hash để tạo bài job/shop vào trạng thái draft cho admin duyệt.
- Admin dashboard dùng để cập nhật giá, quản lý member, bài viết, tiện ích và AI Agent API.
- Đăng ký thành viên và member portal đang mở bằng env mặc định.
- UI hỗ trợ tiếng Việt có dấu và tiếng Trung phồn thể.
- Render deploy sẵn qua Gunicorn/Uvicorn, Alembic và health check `/healthz/`.

## Tính năng đang mở

- Public rate board song ngữ.
- Crypto dashboard tham khảo giá với TradingView widgets.
- Coin price merge song song từ CoinGecko và Binance, có cache/fallback để một nguồn lỗi vẫn còn dữ liệu.
- AdSense hook qua env, kèm `/ads.txt`, ad slot trên các trang public chính.
- Jobs/shop content posts: `draft`, `published`, `archived`; source `admin` hoặc `ai_agent`.
- Utilities MVP: QR generator, shortlink tự động hoặc custom alias, ping website, free VPN/download page.
- Admin login bằng signed session cookie và CSRF token.
- Password hashing bằng PBKDF2.
- Admin rate settings cho `TWD_VND` và `USDT_TWD`.
- Admin contact: `panjiaphu@gmail.com`, LINE `@827sxbki`, phone `0906938893`.
- Alembic migrations cho SQLite/PostgreSQL.

## Env chức năng chính

Member registration và portal đang mở bằng:

```text
MEMBER_REGISTRATION_ENABLED=true
MEMBER_PORTAL_ENABLED=true
CRYPTO_MARKET_LIVE_ENABLED=true
CRYPTO_MARKET_CACHE_SECONDS=180
CRYPTO_MARKET_TIMEOUT_SECONDS=2.5
COINGECKO_API_URL=https://api.coingecko.com/api/v3/simple/price
BINANCE_API_URL=https://api.binance.com/api/v3/ticker/24hr
GOOGLE_ADSENSE_CLIENT=<ca-pub-...>
GOOGLE_ADSENSE_SLOT=<slot id>
GOOGLE_ADSENSE_PUBLISHER_ID=<pub-...>
GOOGLE_SITE_VERIFICATION=<meta verification token>
AI_AGENT_API_ENABLED=true
AI_AGENT_DEFAULT_POST_STATUS=draft
AI_AGENT_ALLOW_AUTOPUBLISH=false
UPLOAD_MAX_MB=5
UPLOAD_STORAGE_BACKEND=local
PUBLIC_BASE_URL=https://fumap-line-webhook.onrender.com
VPN_DOWNLOAD_URL=
VPN_SETUP_GUIDE_URL=
SHOPEE_AFFILIATE_DISCLOSURE_ENABLED=true
```

## Chạy local

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Tạo hoặc cập nhật tài khoản admin local:

```bash
python scripts/create_admin.py --email panjiaphu@gmail.com --password "<mat-khau-admin-manh>"
```

## Deploy Render

```text
Build Command: bash scripts/build_render.sh
Start Command: bash scripts/start_render.sh
Health Check Path: /healthz/
```

Env tối thiểu:

```text
APP_ENV=production
DEBUG=false
SECRET_KEY=<secret rieng dai hon 32 ky tu>
USE_SQLITE=true
SESSION_COOKIE_SECURE=true
RUN_MIGRATIONS_DURING_BUILD=false
ADMIN_NOTIFICATION_EMAIL=panjiaphu@gmail.com
ADMIN_LINE_ID=@827sxbki
ADMIN_PHONE=0906938893
ADMIN_SEED_EMAIL=panjiaphu@gmail.com
ADMIN_SEED_PASSWORD=<mat khau admin manh toi thieu 14 ky tu>
MEMBER_REGISTRATION_ENABLED=true
MEMBER_PORTAL_ENABLED=true
AI_AGENT_API_ENABLED=true
AI_AGENT_DEFAULT_POST_STATUS=draft
AI_AGENT_ALLOW_AUTOPUBLISH=false
UPLOAD_MAX_MB=5
UPLOAD_STORAGE_BACKEND=local
PUBLIC_BASE_URL=https://fumap-line-webhook.onrender.com
SHOPEE_AFFILIATE_DISCLOSURE_ENABLED=true
```

Xem thêm trong `docs/deploy-render.md`.

## Lấy API / cấu hình dịch vụ

- CoinGecko: tạo Demo API key tại trang CoinGecko API, sau đó set `COINGECKO_API_KEY`. Không bắt buộc, nhưng giúp ổn định quota.
- Binance: app đang dùng public Spot market endpoint, không cần API key cho giá public.
- Google AdSense: tạo site trong AdSense, lấy `ca-pub-...` cho `GOOGLE_ADSENSE_CLIENT`, tạo ad unit lấy `GOOGLE_ADSENSE_SLOT`, lấy publisher id `pub-...` cho `GOOGLE_ADSENSE_PUBLISHER_ID`, và nếu Google yêu cầu meta verification thì set `GOOGLE_SITE_VERIFICATION`.
- AI Agent: tạo key trong `/admin/ai-agents`. Raw key chỉ hiển thị một lần, không lưu raw key trong database.
- VPN download: set `VPN_DOWNLOAD_URL` và `VPN_SETUP_GUIDE_URL` khi có phần mềm/hướng dẫn thật.
