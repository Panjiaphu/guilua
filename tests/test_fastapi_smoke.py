from decimal import Decimal
from io import BytesIO
import os
import subprocess
import sys
import unittest

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import BASE_DIR, get_settings
from app.core.security import hash_password
from app.db.session import Base
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    ContentPost,
    ContentPostType,
    EmailNotification,
    EmailReply,
    SecurityEvent,
    ServiceRequest,
    TransactionRequest,
    TransactionType,
    User,
)
from app.services.commercial import create_agent_key
from app.services.email import record_email_reply
from app.services import crypto_market
from app.services.crypto_market import clear_crypto_market_cache
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
        self.assertIn("企業客戶 TWD/VND", response.text)
        self.assertIn("會員免費工具", response.text)
        self.assertNotIn("/member/transactions", response.text)
        self.assertNotIn("手動", response.text)
        self.assertNotIn("交易", response.text)

    def test_home_renders_rate_reference_mode(self):
        response = self.client.get("/?lang=vi")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Bảng tham khảo tỷ giá", response.text)
        self.assertIn("Giá mua", response.text)
        self.assertIn("Giá bán", response.text)
        self.assertIn("Đăng ký thành viên", response.text)
        self.assertNotIn("/member/transactions", response.text)
        self.assertNotIn("Quản trị", response.text)
        self.assertNotIn("Gửi tiền", response.text)
        self.assertNotIn("giao dịch", response.text)
        self.assertNotIn("thủ công", response.text)

    def test_register_is_open(self):
        response = self.client.get("/register?lang=vi")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Đăng ký", response.text)
        self.assertIn('action="/register"', response.text)

    def test_forgot_password_form_and_generic_response(self):
        response = self.client.get("/forgot-password?lang=vi")
        self.assertEqual(response.status_code, 200)
        self.assertIn('action="/forgot-password"', response.text)
        token_marker = 'name="csrf_token" value="'
        token = response.text.split(token_marker, 1)[1].split('"', 1)[0]
        submit = self.client.post(
            "/forgot-password?lang=vi",
            data={"csrf_token": token, "email": "nobody@example.com"},
        )
        self.assertEqual(submit.status_code, 200)
        self.assertIn("Nếu email tồn tại", submit.text)

    def test_crypto_dashboard_renders_with_fallback_data(self):
        old_live = os.environ.get("CRYPTO_MARKET_LIVE_ENABLED")
        os.environ["CRYPTO_MARKET_LIVE_ENABLED"] = "false"
        get_settings.cache_clear()
        clear_crypto_market_cache()
        try:
            response = self.client.get("/crypto?lang=vi")
        finally:
            if old_live is None:
                os.environ.pop("CRYPTO_MARKET_LIVE_ENABLED", None)
            else:
                os.environ["CRYPTO_MARKET_LIVE_ENABLED"] = old_live
            get_settings.cache_clear()
            clear_crypto_market_cache()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Bảng tham khảo crypto", response.text)
        self.assertIn("Bảng chỉ số vĩ mô", response.text)
        self.assertIn("Bảng 12 nhóm coin", response.text)
        self.assertIn("TradingView", response.text)
        self.assertIn("CRYPTOCAP:BTC.D", response.text)
        self.assertIn("CoinGecko + Binance", response.text)
        self.assertIn("Google AdSense chưa được cấu hình", response.text)

    def test_crypto_analysis_public_empty_page_renders(self):
        response = self.client.get("/crypto/analysis?lang=vi")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Phân tích crypto", response.text)

    def test_ads_txt_without_adsense_configuration(self):
        response = self.client.get("/ads.txt")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Google AdSense is not configured", response.text)

    def test_crypto_market_keeps_binance_when_coingecko_fails(self):
        old_live = os.environ.get("CRYPTO_MARKET_LIVE_ENABLED")
        os.environ["CRYPTO_MARKET_LIVE_ENABLED"] = "true"
        get_settings.cache_clear()
        clear_crypto_market_cache()
        original_coingecko = crypto_market._fetch_coingecko
        original_binance = crypto_market._fetch_binance
        crypto_market._fetch_coingecko = lambda settings: (_ for _ in ()).throw(RuntimeError("down"))
        crypto_market._fetch_binance = lambda settings: {
            "BTCUSDT": {"lastPrice": "70000", "priceChangePercent": "1.25", "quoteVolume": "999"}
        }
        try:
            snapshot = crypto_market.get_crypto_market_snapshot(force_refresh=True)
        finally:
            crypto_market._fetch_coingecko = original_coingecko
            crypto_market._fetch_binance = original_binance
            if old_live is None:
                os.environ.pop("CRYPTO_MARKET_LIVE_ENABLED", None)
            else:
                os.environ["CRYPTO_MARKET_LIVE_ENABLED"] = old_live
            get_settings.cache_clear()
            clear_crypto_market_cache()
        self.assertEqual(snapshot["coin_map"]["BTC"]["price"], 70000.0)
        self.assertEqual(snapshot["coin_map"]["BTC"]["source"], "Binance")

    def test_crypto_market_keeps_coingecko_when_binance_fails(self):
        old_live = os.environ.get("CRYPTO_MARKET_LIVE_ENABLED")
        os.environ["CRYPTO_MARKET_LIVE_ENABLED"] = "true"
        get_settings.cache_clear()
        clear_crypto_market_cache()
        original_coingecko = crypto_market._fetch_coingecko
        original_binance = crypto_market._fetch_binance
        crypto_market._fetch_coingecko = lambda settings: {
            "bitcoin": {"usd": 71000, "usd_24h_change": 2.5, "usd_market_cap": 1, "usd_24h_vol": 2}
        }
        crypto_market._fetch_binance = lambda settings: (_ for _ in ()).throw(RuntimeError("down"))
        try:
            snapshot = crypto_market.get_crypto_market_snapshot(force_refresh=True)
        finally:
            crypto_market._fetch_coingecko = original_coingecko
            crypto_market._fetch_binance = original_binance
            if old_live is None:
                os.environ.pop("CRYPTO_MARKET_LIVE_ENABLED", None)
            else:
                os.environ["CRYPTO_MARKET_LIVE_ENABLED"] = old_live
            get_settings.cache_clear()
            clear_crypto_market_cache()
        self.assertEqual(snapshot["coin_map"]["BTC"]["price"], 71000.0)
        self.assertEqual(snapshot["coin_map"]["BTC"]["source"], "CoinGecko")

    def test_commercial_public_pages_render(self):
        for path, marker in [
            ("/jobs?lang=vi", "Tìm việc làm"),
            ("/shop?lang=vi", "Shop Shopee"),
            ("/utilities?lang=vi", "Tiện ích miễn phí"),
            ("/utilities/qr?lang=vi", "Tạo mã QR"),
            ("/utilities/shortlink?lang=vi", "Tạo shortlink"),
            ("/utilities/ping?lang=vi", "Ping website"),
            ("/utilities/free-vpn?lang=vi", "Free VPN"),
            ("/advertising?lang=vi", "Liên hệ quảng cáo"),
            ("/build-idea?lang=vi", "Ý tưởng website"),
        ]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn(marker, response.text)

    def test_shortlink_rejects_localhost(self):
        response = self.client.post(
            "/utilities/shortlink?lang=vi",
            data={"target_url": "http://127.0.0.1:8000/admin"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("not allowed", response.text)

    def test_shortlink_accepts_custom_code(self):
        custom_code = f"guilua-test-{os.getpid()}"
        response = self.client.post(
            "/utilities/shortlink?lang=vi",
            data={"target_url": "https://example.com", "custom_code": custom_code},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"/s/{custom_code}", response.text)

    def test_qr_generator_returns_svg_data_url(self):
        response = self.client.post("/utilities/qr?lang=vi", data={"payload": "https://example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("data:image/svg+xml;base64", response.text)

    def test_ai_agent_requires_key(self):
        response = self.client.post(
            "/api/agent/posts/job",
            json={"title": "Test Job", "summary": "A", "content": "B"},
        )
        self.assertEqual(response.status_code, 401)

    def test_ai_agent_creates_draft_job_post(self):
        with SessionLocal() as db:
            key, raw_key = create_agent_key(db, "Smoke Agent", ["job"], can_auto_publish=False)
            key_id = key.id
        response = self.client.post(
            "/api/agent/posts/job",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={
                "title": "Taiwan Factory Assistant Smoke",
                "summary": "Smoke summary",
                "content": "Smoke content",
                "target_url": "https://example.com/job",
                "platform": "website",
                "status": "published",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "draft")
        with SessionLocal() as db:
            post = db.get(ContentPost, payload["post_id"])
            self.assertIsNotNone(post)
            self.assertEqual(post.source.value, "ai_agent")
            db.delete(post)
            db.delete(db.get(type(key), key_id))
            db.commit()

    def test_ai_agent_creates_crypto_analysis_post(self):
        with SessionLocal() as db:
            key, raw_key = create_agent_key(db, "Crypto Agent", ["crypto_analysis"], can_auto_publish=False)
            key_id = key.id
        response = self.client.post(
            "/api/agent/posts/crypto_analysis",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={
                "title": "BTC Session Smoke Analysis",
                "summary": "Smoke crypto analysis",
                "content": "Market structure and tokenomics notes.",
                "status": "published",
                "tags": ["BTC", "ETH"],
                "market_session": "Asia",
                "market_bias": "neutral",
                "risk_level": "medium",
                "tradingview_symbol": "BINANCE:BTCUSDT",
                "tradingview_url": "https://www.tradingview.com/chart/?symbol=BINANCE%3ABTCUSDT",
                "analysis_category": "session_report",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "draft")
        with SessionLocal() as db:
            post = db.get(ContentPost, payload["post_id"])
            self.assertIsNotNone(post)
            self.assertEqual(post.post_type, ContentPostType.CRYPTO_ANALYSIS)
            self.assertEqual(post.market_session, "Asia")
            self.assertEqual(post.tradingview_symbol, "BINANCE:BTCUSDT")
            db.delete(post)
            db.delete(db.get(type(key), key_id))
            db.commit()

    def test_admin_post_upload_compresses_image_to_webp(self):
        email = f"admin-upload-{os.getpid()}@example.com"
        password = "AdminUpload!2026"
        with SessionLocal() as db:
            old_user = db.query(User).filter(User.email == email).first()
            if old_user:
                db.delete(old_user)
                db.commit()
            admin = User(
                email=email,
                password_hash=hash_password(password),
                full_name="Upload Admin",
                locale="vi",
                is_admin=True,
                is_email_verified=True,
            )
            db.add(admin)
            db.commit()
            admin_id = admin.id

        login_page = self.client.get("/login?lang=vi")
        token = login_page.text.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
        login = self.client.post(
            "/login?lang=vi",
            data={"csrf_token": token, "email": email, "password": password, "next_url": "/admin"},
        )
        self.assertEqual(login.status_code, 200)

        form_page = self.client.get("/admin/posts/jobs/new?lang=vi")
        self.assertEqual(form_page.status_code, 200)
        token = form_page.text.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
        image_buffer = BytesIO()
        Image.new("RGB", (640, 360), "#00d09c").save(image_buffer, format="PNG")
        response = self.client.post(
            "/admin/posts/jobs",
            data={
                "csrf_token": token,
                "title": "Upload Smoke Job Post",
                "summary": "Upload smoke summary",
                "content": "Upload smoke content",
                "target_url": "https://example.com/job",
                "platform": "website",
                "locale": "vi",
                "status": "published",
                "tags": "upload, smoke",
                "sort_order": "1",
            },
            files={"image_file": ("cover.png", image_buffer.getvalue(), "image/png")},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        settings = get_settings()
        with SessionLocal() as db:
            post = db.query(ContentPost).filter(ContentPost.title == "Upload Smoke Job Post").first()
            self.assertIsNotNone(post)
            self.assertTrue(post.image_url.endswith(".webp"))
            self.assertIn("/static/uploads/posts/jobs/", post.image_url)
            relative_url = post.image_url.replace(settings.public_base_url.rstrip(), "")
            saved_path = BASE_DIR / "app" / relative_url.lstrip("/")
            self.assertTrue(saved_path.exists())
            saved_path.unlink(missing_ok=True)
            db.delete(post)
            db.query(SecurityEvent).filter(SecurityEvent.user_id == admin_id).delete()
            db.delete(db.get(User, admin_id))
            db.commit()

    def test_security_firewall_env_blocklist_logs_event(self):
        old_blocklist = os.environ.get("SECURITY_IP_BLOCKLIST")
        os.environ["SECURITY_IP_BLOCKLIST"] = "203.0.113.250"
        get_settings.cache_clear()
        try:
            response = self.client.get("/", headers={"X-Forwarded-For": "203.0.113.250"})
            self.assertEqual(response.status_code, 403)
            with SessionLocal() as db:
                event = (
                    db.query(SecurityEvent)
                    .filter(SecurityEvent.ip_address == "203.0.113.250", SecurityEvent.event_type == "request_blocked")
                    .order_by(SecurityEvent.created_at.desc())
                    .first()
                )
                self.assertIsNotNone(event)
        finally:
            if old_blocklist is None:
                os.environ.pop("SECURITY_IP_BLOCKLIST", None)
            else:
                os.environ["SECURITY_IP_BLOCKLIST"] = old_blocklist
            get_settings.cache_clear()

    def test_email_webhook_requires_configuration(self):
        response = self.client.post(
            "/webhooks/email-reply",
            json={"from": "member@example.com", "text": "Xin chào"},
        )
        self.assertEqual(response.status_code, 503)

    def test_member_services_requires_login_when_open(self):
        response = self.client.get("/member/services?lang=vi", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/login", response.headers["location"])

    def test_transaction_form_requires_login_when_open(self):
        response = self.client.get("/member/transactions/send-home?lang=vi", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/login", response.headers["location"])

    def test_ip_connector_download_requires_login_when_open(self):
        response = self.client.get("/member/services/ip-switch/download", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/login", response.headers["location"])

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
