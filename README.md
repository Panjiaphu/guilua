# Guilua Finance Webapp

FastAPI webapp cho Guilua trong giai đoạn rà soát pháp lý.

Trạng thái hiện tại:
- Public UI chỉ hiển thị bảng tham khảo tỷ giá `TWD/VND` và `USDT/TWD`.
- Admin dashboard dùng để cập nhật giá mua, giá bán và thông tin liên hệ.
- Đăng ký thành viên và member portal đang tạm khóa bằng env mặc định.
- UI hỗ trợ tiếng Việt có dấu và tiếng Trung phồn thể.
- Render deploy sẵn qua Gunicorn/Uvicorn, Alembic và health check `/healthz/`.

## Tính năng đang mở

- Public rate board song ngữ.
- Admin login bằng signed session cookie và CSRF token.
- Password hashing bằng PBKDF2.
- Admin rate settings cho `TWD_VND` và `USDT_TWD`.
- Admin contact: `panjiaphu@gmail.com`, LINE `@827sxbki`, phone `0906938893`.
- Alembic migrations cho SQLite/PostgreSQL.

## Tính năng đang khóa

Các module member, service request, email queue và IP connector vẫn còn trong codebase để bật lại sau, nhưng mặc định bị khóa bằng:

```text
MEMBER_REGISTRATION_ENABLED=false
MEMBER_PORTAL_ENABLED=false
```

Khi pháp lý hoàn tất mới bật lại hai biến này.

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
MEMBER_REGISTRATION_ENABLED=false
MEMBER_PORTAL_ENABLED=false
```

Xem thêm trong `docs/deploy-render.md`.
