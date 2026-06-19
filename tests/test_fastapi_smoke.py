from decimal import Decimal
from io import BytesIO
import os
import subprocess
import sys
import unittest
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.security import serializer
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models import EmailNotification, EmailReply, ServiceRequest, TransactionRequest, TransactionType, User
from app.services.email import record_email_reply
from app.services.ip_provider import provision_ip_service
from app.services.member_services import create_ip_service_request
from app.services.rates import ensure_default_rates
from app.services.transactions import create_transaction


class FastApiSmokeTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_healthz_ok(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_home_renders_bilingual_shell(self):
        response = self.client.get("/?lang=zh-TW")
        self.assertEqual(response.status_code, 200)
        self.assertIn("以安全儀表板處理台幣匯款到越南", response.text)
        self.assertIn("會員中心", response.text)

    def test_home_renders_vietnamese_with_accents(self):
        response = self.client.get("/?lang=vi")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Gửi tiền", response.text)
        self.assertIn("Tỷ giá", response.text)
        self.assertIn("/member/transactions/send-home", response.text)

    def test_email_webhook_requires_configuration(self):
        response = self.client.post(
            "/webhooks/email-reply",
            json={"from": "member@example.com", "text": "Xin chào"},
        )
        self.assertEqual(response.status_code, 503)

    def test_member_services_requires_login(self):
        response = self.client.get("/member/services?lang=vi", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/login?next="))

    def test_transaction_form_requires_login(self):
        response = self.client.get("/member/transactions/send-home?lang=vi", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/login?next="))

    def test_ip_connector_download_returns_zip_for_member(self):
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            user = db.query(User).filter(User.email == "download-member@example.com").first()
            if not user:
                user = User(
                    email="download-member@example.com",
                    password_hash="hash",
                    full_name="Download Member",
                    locale="vi",
                    is_active=True,
                )
                db.add(user)
                db.commit()
                db.refresh(user)
            user_id = user.id

        settings = get_settings()
        self.client.cookies.set(
            settings.session_cookie_name,
            serializer.dumps({"user_id": user_id, "csrf_token": "test-token"}),
        )
        response = self.client.get("/member/services/ip-switch/download")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        self.assertIn("guilua-ip-connector.zip", response.headers["content-disposition"])

        with ZipFile(BytesIO(response.content)) as archive:
            self.assertIn("guilua-ip-connector.ps1", archive.namelist())
            self.assertIn("README.txt", archive.namelist())
            readme = archive.read("README.txt").decode("utf-8")
            self.assertIn("Guilua IP Connector", readme)

    def test_record_email_reply_queues_admin_notification(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        TestingSession = sessionmaker(bind=engine)

        with TestingSession() as db:
            reply = record_email_reply(
                db,
                sender="member@example.com",
                recipient="support@guilua.local",
                subject="Re: GL test",
                body="Tôi đã bổ sung thông tin.",
            )

            self.assertEqual(reply.sender, "member@example.com")
            self.assertEqual(db.query(EmailReply).count(), 1)
            self.assertEqual(db.query(EmailNotification).filter_by(event_type="inbound_email_reply").count(), 1)

    def test_create_ip_service_request_queues_notifications(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        TestingSession = sessionmaker(bind=engine)

        with TestingSession() as db:
            user = User(
                email="service-member@example.com",
                password_hash="hash",
                full_name="Service Member",
                locale="vi",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

            item = create_ip_service_request(
                db,
                user=user,
                target_region="random",
                protocol="vpn",
                duration_hours=48,
                device_label="Laptop",
                current_ip="203.0.113.10",
                member_note="Cần IP ổn định",
            )

            self.assertTrue(item.reference_code.startswith("GS"))
            self.assertEqual(item.target_region, "random")
            self.assertEqual(db.query(ServiceRequest).count(), 1)
            self.assertEqual(db.query(EmailNotification).filter_by(event_type="member_service_created").count(), 1)
            self.assertEqual(db.query(EmailNotification).filter_by(event_type="admin_service_created").count(), 1)

    def test_create_transaction_stores_admin_details(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        TestingSession = sessionmaker(bind=engine)

        with TestingSession() as db:
            ensure_default_rates(db)
            user = User(
                email="trade-member@example.com",
                password_hash="hash",
                full_name="Trade Member",
                locale="vi",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

            item = create_transaction(
                db,
                user=user,
                request_type=TransactionType.BUY_USDT,
                amount_twd=Decimal("10000"),
                amount_usdt=None,
                contact_phone="0900000000",
                contact_line="@member",
                usdt_network="TRC20",
                wallet_address="TXYZ123",
                member_note="Cần xử lý nhanh",
            )

            self.assertTrue(item.reference_code.startswith("GL"))
            self.assertEqual(item.usdt_network, "TRC20")
            self.assertEqual(item.wallet_address, "TXYZ123")
            self.assertEqual(item.contact_phone, "0900000000")
            self.assertEqual(db.query(TransactionRequest).count(), 1)

    def test_ip_provider_returns_not_configured_without_env(self):
        old_url = os.environ.pop("IP_SERVICE_PROVIDER_URL", None)
        old_key = os.environ.pop("IP_SERVICE_PROVIDER_API_KEY", None)
        get_settings.cache_clear()
        item = ServiceRequest(
            reference_code="GSDEMO",
            service_type="ip_switch",
            target_region="taiwan",
            protocol="vpn",
            duration_hours=24,
            device_label="Laptop",
            current_ip="203.0.113.10",
            member_note="",
        )
        try:
            result = provision_ip_service(item)
            self.assertFalse(result.configured)
            self.assertFalse(result.success)
        finally:
            if old_url is not None:
                os.environ["IP_SERVICE_PROVIDER_URL"] = old_url
            if old_key is not None:
                os.environ["IP_SERVICE_PROVIDER_API_KEY"] = old_key
            get_settings.cache_clear()

    def test_runtime_env_check_rejects_weak_admin_seed_password(self):
        env = {
            **os.environ,
            "APP_ENV": "production",
            "DEBUG": "false",
            "SECRET_KEY": "x" * 40,
            "USE_SQLITE": "true",
            "ADMIN_SEED_PASSWORD": "pp11223344",
        }
        result = subprocess.run(
            [sys.executable, "scripts/check_env.py", "--phase", "runtime"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("ADMIN_SEED_PASSWORD must be at least 14 characters", result.stderr)


if __name__ == "__main__":
    unittest.main()
