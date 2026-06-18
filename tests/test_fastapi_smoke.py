import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.main import app
from app.models import EmailNotification, EmailReply
from app.services.email import record_email_reply


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

    def test_email_webhook_requires_configuration(self):
        response = self.client.post(
            "/webhooks/email-reply",
            json={"from": "member@example.com", "text": "Xin chào"},
        )
        self.assertEqual(response.status_code, 503)

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


if __name__ == "__main__":
    unittest.main()
