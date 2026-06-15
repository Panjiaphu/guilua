# GuiLua Odds & Ticket Builder

Django webapp scaffold cho quy trinh ke toan ty le va ve.

## Workflow san pham

1. Paste du lieu ty le tu san app.
2. Preview bang ty le, chi tu dong lay `app_odds`.
3. Nhap `outside_odds` rieng bang tay hoac paste theo thu tu.
4. Chi luu bang ty le khi moi dong co app odds va outside odds hop le.
5. Chi tao ve tu dong ty le `ready`.
6. Ve luu snapshot odds tai thoi diem tao.
7. Tinh tien nhap app, tien con lai, payout va lai/lo.
8. Tong ket ngay co doan copy ke toan.

## Trang thai hien tai

Repo da co scaffold Django cho workflow import ty le, nhap ve va tong ket ngay.

Cac nhom file chinh:

- `config/`: cau hinh Django.
- `odds/models.py`: `OddsImportBatch`, `MarketLine`, `Ticket`.
- `odds/services/`: parse import, tinh tien, tao ve snapshot, tong ket ngay.
- `odds/views.py`: man import, nhap ve, tong ket.
- `odds/templates/odds/`: UI thao tac nhanh.
- `odds/static/odds/app.css`: responsive layout.
- `odds/tests/`: test luat nghiep vu.

## Kiem tra da chay trong workspace

```bash
python -m unittest odds.tests.test_pure_services
python -m compileall config odds
```

Ket qua: pass.

Django runtime check chua chay duoc trong container hien tai vi `pip install` bi proxy 403 khi tai Django tu PyPI.

## Chay local khi dependency san sang

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
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
