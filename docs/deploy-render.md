# Deploy Render cho GuiLua

## Loi trong anh chup

Render dang fail o buoc build vi Django co gang ket noi PostgreSQL/Supabase:

```text
OperationalError: failed to resolve host 'db....supabase.co'
```

Nguyen nhan thuong gap:

- `DATABASE_URL` dang tro toi Supabase host sai, project bi pause, hoac DNS khong resolve duoc.
- Build command dang chay `python manage.py migrate` trong luc database chua san sang.
- Render dang dung Python 3.14 thay vi runtime da duoc test.

## Cau hinh khuyen nghi

Trong Render service, dat:

```text
Build Command: bash scripts/build_render.sh
Start Command: bash scripts/start_render.sh
Health Check Path: /healthz/
```

Environment variables toi thieu:

```text
SECRET_KEY=<tao secret rieng trong Render>
DEBUG=false
USE_SQLITE=true
RUN_MIGRATIONS_DURING_BUILD=false
```

Voi cau hinh tren, app se deploy chay bang SQLite de kiem tra giao dien nhanh. Khi can du lieu ben vung, tao database PostgreSQL hop le roi doi:

```text
USE_SQLITE=false
DATABASE_URL=<postgres URL hop le>
RUN_MIGRATIONS_DURING_BUILD=true
```

`scripts/start_render.sh` se chay migration luc runtime roi moi bat Gunicorn. Nhu vay build khong chet vi database host loi, nhung app van co bang database khi start.

Khong commit secret that vao repo.

## Lenh local

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```
