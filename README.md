# Guilua Finance Webapp

FastAPI webapp cho Guilua: gửi tiền TWD về Việt Nam, mua USDT, bán USDT,
dashboard thành viên, dashboard admin, tỷ giá thủ công dự phòng và hàng đợi
email notification. UI hỗ trợ tiếng Việt có dấu và tiếng Trung phồn thể.

Repo trước đây có Django scaffold trong `config/` và `odds/`. Code đó được giữ
lại để không xóa lịch sử, nhưng entrypoint deploy hiện tại là FastAPI:
`app.main:app`.

## Chức năng hiện có

- Đăng ký, đăng nhập, đăng xuất bằng signed session cookie và CSRF token.
- Password hashing bằng PBKDF2.
- Email verification token và email queue.
- Email reply webhook để nhận phản hồi member và hiển thị trong admin dashboard.
- Member dashboard: tạo request `send_home`, `buy_usdt`, `sell_usdt`.
- Member services: tạo yêu cầu chuyển IP theo khu vực/giao thức/thời lượng.
- Web random IP request và gói tải desktop connector cho member.
- Admin dashboard: cập nhật trạng thái request, ghi chú nội bộ, cập nhật manual rate.
- Admin service review: xử lý yêu cầu chuyển IP, cấp endpoint và gửi email cập nhật.
- Admin contact: `panjiaphu@gmail.com`, LINE `@827sxbki`, phone `0906938893`.
- Exchange rates: manual fallback cho `TWD_VND` và `USDT_TWD`, sẵn sàng gắn live provider qua env.
- Alembic migration cho PostgreSQL/SQLite.
- Render deploy scripts và health check `/healthz/`.
- Admin seed qua `ADMIN_SEED_EMAIL` và `ADMIN_SEED_PASSWORD` khi database chưa có admin.

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
python scripts/create_admin.py --email panjiaphu@gmail.com --password "<mật-khẩu-admin-mạnh>"
```

Không đưa secret thật vào repo. Dùng `.env.example` làm mẫu cấu hình.

## Deploy Render

Build Command:

```bash
bash scripts/build_render.sh
```

Start Command:

```bash
bash scripts/start_render.sh
```

Health check:

```text
/healthz/
```

Xem chi tiết trong `docs/deploy-render.md`.

## Phần còn cần backend thật

- Email đã có queue và SMTP sender, nhưng cần cấu hình SMTP env thật trên Render.
- Live exchange provider là optional qua `EXCHANGE_RATE_PROVIDER_URL`; nếu chưa có provider, app dùng manual fallback rate.
- Two-way email đã có queue outbound, SMTP sender, inbound webhook và màn hình xử lý reply. Vẫn cần cấu hình provider email thật trỏ webhook về app.
- Dịch vụ chuyển IP hiện là request/review/email workflow; cần hạ tầng VPN/proxy/provider thật để tự động cấp và xoay IP.
- IP provider hook đã có qua `IP_SERVICE_PROVIDER_URL` và `IP_SERVICE_PROVIDER_API_KEY`; nếu chưa cấu hình, admin vẫn cấp endpoint thủ công.
- Admin seed đã có env password, nhưng nên thay bằng flow tạo admin riêng trước production.
