import os
import sys
import unittest
from unittest.mock import patch


class FakeTable:
    def __init__(self, calls):
        self.calls = calls

    def upsert(self, payload):
        self.calls.append(payload)
        return self

    def execute(self):
        return type("Resp", (), {"data": []})()


class FakeSupabase:
    def __init__(self, *, fail_device_id=False, fail_area_id=False):
        self.calls = []
        self.fail_device_id = fail_device_id
        self.fail_area_id = fail_area_id

    def table(self, name):
        return FakeTable(self.calls)

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

    @patch("api.index.supabase", None)
    def test_area_rows_use_area_id_key_when_rendering(self):
        response = self.client.get("/api/area")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.get_json(), list)

    def test_ssid_post_preserves_non_numeric_device_id(self):
        with patch("api.index.supabase", FakeSupabase()):
            response = self.client.post(
                "/api/ssid",
                json={"username": "alice", "device_id": "device-1"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["message"], "user updated")


if __name__ == "__main__":
    unittest.main()
