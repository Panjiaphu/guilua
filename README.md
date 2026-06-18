# Guilua Finance Webapp

FastAPI webapp cho Guilua: gui tien TWD ve Viet Nam, mua USDT, ban USDT,
member dashboard, admin dashboard, manual fallback rates va email notification
queue. UI ho tro Vietnamese va Traditional Chinese.

Repo truoc day co Django scaffold trong `config/` va `odds/`. Code do duoc giu
lai de khong xoa lich su, nhung entrypoint deploy hien tai la FastAPI:
`app.main:app`.

## Chuc nang hien co

- Dang ky, dang nhap, dang xuat bang session cookie signed va CSRF token.
- Password hashing bang PBKDF2.
- Email verification token va email queue.
- Member dashboard: tao request `send_home`, `buy_usdt`, `sell_usdt`.
- Admin dashboard: cap nhat trang thai request, ghi chu noi bo, cap nhat manual rate.
- Exchange rates: manual fallback cho `TWD_VND` va `USDT_TWD`, san sang gan live provider qua env.
- Alembic migration cho PostgreSQL/SQLite.
- Render deploy scripts va health check `/healthz/`.
- Admin seed qua `ADMIN_SEED_EMAIL` va `ADMIN_SEED_PASSWORD` khi database chua co admin.

## Chay local

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

Khong dua secret that vao repo. Dung `.env.example` lam mau cau hinh.

## Deploy Render

Repo co san `render.yaml`, `runtime.txt`, `.python-version` va scripts trong `scripts/`.

Build command:

```bash
bash scripts/build_render.sh
```

Start command:

```bash
bash scripts/start_render.sh
```

Health check:

```text
/healthz/
```

Xem chi tiet trong `docs/deploy-render.md`.

## Mock / can backend that

- Email da co queue va SMTP sender, nhung can cau hinh SMTP env that tren Render.
- Live exchange provider la optional qua `EXCHANGE_RATE_PROVIDER_URL`; neu chua co provider, app dung manual fallback rate.
- Admin seed da co env password, nhung nen thay bang flow tao admin rieng truoc production.
