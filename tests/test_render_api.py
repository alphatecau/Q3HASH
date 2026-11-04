"""HTTP boundary tests and a real subprocess-backed Q3HASH integration check."""
from __future__ import annotations

import http.client
import json
import threading
import unittest
from unittest.mock import patch
from pathlib import Path
import sys
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deployment import render_api

SECRET = "termux-local-test-key-not-a-real-secret-1234567890"


class APIBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = render_api.make_server("127.0.0.1", 0, SECRET, interval_seconds=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      kwargs={"poll_interval": 0.01}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(3)

    def request(self, method, route, body=None, authorized=True, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=30)
        h = {}
        if authorized:
            h["Authorization"] = "Bearer " + SECRET
        if body is not None:
            h["Content-Type"] = "application/json"
        if headers:
            h.update(headers)
        conn.request(method, route, body=body, headers=h)
        response = conn.getresponse()
        data = json.loads(response.read())
        status = response.status
        conn.close()
        return status, data

    def test_health_no_auth(self):
        status, response = self.request("GET", "/healthz", authorized=False)
        self.assertEqual((status, response["status"]), (200, "ok"))

    def test_capabilities_needs_auth(self):
        status, _ = self.request("GET", "/api/v1/capabilities", authorized=False)
        self.assertEqual(status, 401)
        status, response = self.request("GET", "/api/v1/capabilities")
        self.assertEqual(status, 200)
        self.assertTrue(response["synthetic_hardware_only"])
        self.assertFalse(response["public_browser_access"])

    def test_browser_origin_and_options_denied(self):
        status, _ = self.request("GET", "/api/v1/capabilities",
                                 headers={"Origin": "https://q3hash-lab.alpha-tec-au86.chatgpt.site"})
        self.assertEqual(status, 403)
        status, _ = self.request("OPTIONS", "/api/v1/simulate", authorized=False)
        self.assertEqual(status, 405)

    def test_body_limit_and_content_type(self):
        status, _ = self.request("POST", "/api/v1/simulate", body=b"x" * 16385)
        self.assertEqual(status, 413)
        status, _ = self.request("POST", "/api/v1/simulate", body=b"{}",
                                 headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)

    def test_real_engine_in_isolated_subprocess(self):
        # This test exercises the actual q3hash engine, not a mocked algorithm.
        if importlib.util.find_spec("q3hash") is None:
            self.skipTest("Q3HASH core is not installed in this environment")
        status, response = self.request(
            "POST", "/api/v1/simulate",
            body=json.dumps({"source": "qutrit q\nshift q"}).encode("utf-8"))
        self.assertEqual((status, response.get("status")), (200, "pass"), response)
        self.assertEqual(response["dimensions"], [3])
        self.assertAlmostEqual(response["basis"][1]["probability"], 1.0)

    def test_bad_json_is_structured(self):
        if importlib.util.find_spec("q3hash") is None:
            self.skipTest("Q3HASH core is not installed in this environment")
        status, response = self.request("POST", "/api/v1/simulate", body=b"{bad")
        self.assertEqual(status, 422)
        self.assertEqual(response["status"], "invalid")
        self.assertIn("code", response)


if __name__ == "__main__":
    unittest.main()
