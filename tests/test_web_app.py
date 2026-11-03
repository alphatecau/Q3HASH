"""End-to-end localhost v0.6 research-console API and security boundaries."""

import http.client
import importlib.util
import json
from pathlib import Path
import threading
import unittest

from q3hash import BasisEncoding

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("q3hash_web_app", ROOT / "tools/web_app.py")
WEB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WEB)


class WebAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = WEB.create_server(0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      kwargs={"poll_interval": 0.01}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        default = {"Content-Type": "application/json"} if method == "POST" else {}
        if headers:
            default.update(headers)
        conn.request(method, path, body=body, headers=default)
        response = conn.getresponse()
        data = response.read()
        metadata = dict(response.getheaders())
        status = response.status
        conn.close()
        if metadata.get("Content-Type", "").startswith("application/json"):
            return status, json.loads(data), metadata
        return status, data, metadata

    def post(self, route, payload):
        return self.call("POST", "/api/v1/" + route,
                         json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    def test_static_app_and_capabilities_have_security_headers(self):
        for path in ("/", "/app.js", "/styles.css"):
            with self.subTest(path=path):
                status, contents, headers = self.call("GET", path)
                self.assertEqual(status, 200)
                self.assertTrue(contents)
                self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertNotIn("Access-Control-Allow-Origin", headers)
        status, value, headers = self.call("GET", "/api/v1/capabilities")
        self.assertEqual(status, 200)
        self.assertEqual(value["schema"], "q3hash.web-response")
        self.assertTrue(value["local_only"])
        self.assertFalse(value["automatic_synthesis"])
        self.assertFalse(value["automatic_dimension_inference"])
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_simulate_real_q3hash_core(self):
        status, value, _ = self.post("simulate", {"source": "qutrit q\nshift q"})
        self.assertEqual((status, value["status"], value["dimensions"]), (200, "pass", [3]))
        self.assertEqual(value["state_size"], 3)
        self.assertAlmostEqual(value["basis"][1]["probability"], 1.0)
        self.assertEqual(len(value["basis"]), 3)
        self.assertEqual(value["basis"][0]["probability"], 0.0)

    def test_explicit_encoding_verification_and_bad_cases(self):
        encoding = BasisEncoding((3,), (2, 2), (0, 1, 2)).to_dict()
        status, value, _ = self.post("verify", {
            "logical_source": "qutrit q\nshift q",
            "physical_source": "qubit a\nqubit b\nsum a b\nsum b a\nshift b",
            "encoding": encoding,
        })
        self.assertEqual((status, value["status"]), (200, "pass"))
        for name in ("subspace_residual", "leakage_norm", "logical_unitarity_error",
                     "physical_unitarity_error"):
            self.assertLessEqual(value["verification"][name], 1e-10)
        status, wrong, _ = self.post("verify", {
            "logical_source": "qutrit q\nshift q",
            "physical_source": "qudit 4 q\nshift q",
            "encoding": BasisEncoding((3,), (4,), (0, 1, 2)).to_dict(),
        })
        self.assertEqual((status, wrong["status"]), (200, "fail"))
        self.assertAlmostEqual(wrong["verification"]["leakage_norm"], 1)

    def test_supported_status_vs_declared_unsupported(self):
        status, value, _ = self.post("simulate", {"source": "qudit 32 a\nqudit 3 b"})
        self.assertEqual((status, value["status"]), (200, "unsupported"))
        status, value, _ = self.post("verify", {
            "logical_source": "qutrit q\nshift q",
            "physical_source": "qudit 32 a\nqudit 2 b\nshift b",
            "encoding": BasisEncoding((3,), (32, 2), (0, 1, 2)).to_dict(),
        })
        self.assertEqual((status, value["status"]), (200, "unsupported"))
        self.assertIsNone(value["verification"]["subspace_residual"])

    def test_fixed_three_way_benchmark_reuses_real_reports(self):
        status, value, _ = self.post("compare", {})
        self.assertEqual((status, value["status"]), (200, "partial"))
        self.assertEqual(value["source_status_counts"]["pass"], 3)
        self.assertEqual(value["source_status_counts"]["unimplemented"], 1)
        self.assertEqual(value["hardware_status_counts"]["supported"], 3)
        self.assertEqual(value["hardware_provenance"], "synthetic")
        self.assertFalse(value["measured_hardware"])
        self.assertTrue(value["front_partial"])
        cases = {r["name"]: r for r in value["rows"] if r["name"] != "unimplemented"}
        self.assertEqual({k for k, v in cases.items() if v["on_front"]}, {"native", "mixed"})
        self.assertEqual(cases["native"]["critical_path_ps"], [40000, 60000])
        self.assertEqual(cases["binary"]["critical_path_ps"], [390000, 490000])
        self.assertEqual(cases["mixed"]["critical_path_ps"], [5000, 8000])

    def test_boundary_rejections_are_structured_not_tracebacks(self):
        cases = (
            ("simulate", {"source": "bad instruction"}),
            ("simulate", {"source": "qutrit q", "extra": 1}),
            ("simulate", {"source": "qutrit q\n" + "shift q\n" * 65}),
            ("simulate", {"source": "x" * 4097}),
            ("verify", {"logical_source": "qutrit q", "physical_source": "qutrit q", "encoding": {}}),
            ("compare", {"source": "user supplied fixture path"}),
        )
        for endpoint, payload in cases:
            with self.subTest(endpoint=endpoint, payload=str(payload)[:30]):
                status, value, _ = self.post(endpoint, payload)
                self.assertEqual(status, 422)
                self.assertEqual(value["status"], "invalid")
                self.assertNotIn("Traceback", json.dumps(value))
        status, value, _ = self.call("POST", "/api/v1/simulate", b'{"source":"qubit q","source":"qubit a"}')
        self.assertEqual((status, value["status"]), (422, "invalid"))
        status, value, _ = self.call("POST", "/api/v1/simulate", b'{"source":NaN}')
        self.assertEqual((status, value["status"]), (422, "invalid"))
        status, value, _ = self.call("POST", "/api/v1/simulate", b"x" * 16385)
        self.assertEqual(status, 413)

    def test_rejects_cross_site_and_nonlocal_host(self):
        payload = b'{"source":"qubit q"}'
        for headers in ({"Host": "attacker.invalid"},
                        {"Origin": "https://attacker.invalid"},
                        {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                status, value, _ = self.call("POST", "/api/v1/simulate", payload, headers=headers)
                self.assertEqual(status, 403)
                self.assertEqual(value["status"], "invalid")
        for path in ("/../LICENSE", "/.git/config", "/tools/web_app.py", "/api/v1/nope"):
            status, value, _ = self.call("GET", path)
            self.assertEqual(status, 404)
        status, value, _ = self.call("OPTIONS", "/api/v1/simulate")
        self.assertEqual(status, 405)
        status, value, _ = self.call("POST", "/api/v1/simulate", payload,
                                     headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)


if __name__ == "__main__":
    unittest.main()
