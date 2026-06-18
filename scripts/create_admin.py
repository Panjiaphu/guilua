import argparse
import os
import secrets
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.security import hash_password
from app.db.session import Base, SessionLocal, engine
from app.models import User


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update a Guilua admin account.")
    parser.add_argument("--email", default=os.getenv("ADMIN_SEED_EMAIL", "panjiaphu@gmail.com"))
    parser.add_argument("--password", default=os.getenv("ADMIN_SEED_PASSWORD"))
    parser.add_argument("--full-name", default="Guilua Admin")
    args = parser.parse_args()

    email = args.email.strip().lower()
    password = args.password or secrets.token_urlsafe(18)
    if len(password) < 14:
        raise SystemExit("Admin password must be at least 14 characters.")

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(email=email, password_hash=hash_password(password))
            db.add(user)
        else:
            user.password_hash = hash_password(password)
        user.full_name = args.full_name
        user.locale = "vi"
        user.is_admin = True
        user.is_email_verified = True
        user.is_active = True
        db.commit()

    print(f"Admin account ready: {email}")
    if not args.password:
        print(f"Temporary password: {password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
