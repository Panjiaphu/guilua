import unittest

from fastapi.testclient import TestClient

from app.main import app


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


if __name__ == "__main__":
    unittest.main()
