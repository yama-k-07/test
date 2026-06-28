import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from api.index import app


class IndexApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_area_status_post_accepts_area_id_list(self):
        response = self.client.post(
            "/api/area_status",
            json=[{"area_id": "A1", "instruction": "waiting", "fire": False}],
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("message", response.get_json())

    def test_area_post_requires_area_id_and_bssid(self):
        response = self.client.post("/api/area", json={"area_id": "A1"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    def test_ssid_post_accepts_username_or_device_id(self):
        response = self.client.post(
            "/api/ssid",
            json={"username": "alice", "device_id": "device-1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("message", response.get_json())


if __name__ == "__main__":
    unittest.main()
