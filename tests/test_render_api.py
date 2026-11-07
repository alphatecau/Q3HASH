"""HTTP boundary tests and a real subprocess-backed Q3HASH integration check."""
from __future__ import annotations

import http.client
import json
import threading
import unittest
from unittest.mock import patch
from pathlib import Path
import sys
from dataclasses import replace
import socket
import tempfile
import os

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deployment import render_api

DEPLOYMENT = "1" * 40
SECRET = "termux-local-test-key-not-a-real-secret-1234567890"


class APIBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = render_api.make_server("127.0.0.1", 0, SECRET, deployment_commit=DEPLOYMENT, interval_seconds=0)
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
        self.assertEqual(response["source_commit"], "19e44ada3a5a31deec7875c403b2efc0ee4c8488")
        self.assertEqual(response["deployment_commit"], DEPLOYMENT)
        self.assertEqual((response["engine_version"], response["web_version"], response["schema_version"]),
                         ("0.5.0", "0.6.0-rc.1", 2))
        self.assertEqual(response["basis_order"], "last-register-fastest")
        self.assertEqual(response["max_program_characters"], 4096)
        self.assertEqual(response["max_operations"], 64)

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
        status, response = self.request(
            "POST", "/api/v1/simulate",
            body=json.dumps({"source": "qutrit q\nshift q"}).encode("utf-8"))
        self.assertEqual((status, response.get("status")), (200, "pass"), response)
        self.assertEqual(response["dimensions"], [3])
        self.assertAlmostEqual(response["basis"][1]["probability"], 1.0)
        self.assertEqual(response["deployment_commit"], DEPLOYMENT)

    def test_bad_json_is_structured(self):
        status, response = self.request("POST", "/api/v1/simulate", body=b"{bad")
        self.assertEqual(status, 422)
        self.assertEqual(response["status"], "invalid")
        self.assertIn("code", response)


    def raw_request(self, wire):
        with socket.create_connection(self.server.server_address, timeout=3) as conn:
            conn.sendall(wire)
            conn.shutdown(socket.SHUT_WR)
            with conn.makefile("rb") as response:
                return response.read()

    def test_ambiguous_headers_are_rejected_and_connection_closes(self):
        prefix = b"POST /api/v1/compare HTTP/1.1\r\nHost: localhost\r\n"
        auth = b"Authorization: Bearer " + SECRET.encode() + b"\r\n"
        suffix = b"Content-Type: application/json\r\n\r\n{}GET /healthz HTTP/1.1\r\nHost: localhost\r\n\r\n"
        for invalid in (
            b"Content-Length: 2\r\nContent-Length: 2\r\n",
            b"Content-Length: 2\r\nTransfer-Encoding: chunked\r\n",
            b"Content-Length: 2\r\nX-Folded: first\r\n continued\r\n",
            b"Host: second.example\r\nContent-Length: 2\r\n",
            b"Content-Length: 99999999999999999999999999\r\n",
        ):
            with self.subTest(header=invalid):
                reply = self.raw_request(prefix + auth + invalid + suffix)
                self.assertTrue(reply.startswith(b"HTTP/1.1 400 "), reply[:250])
                self.assertIn(b"Connection: close", reply)
                self.assertEqual(reply.count(b"HTTP/1.1"), 1)

    def test_oversize_headers_and_expect_continue(self):
        prefix = b"POST /api/v1/compare HTTP/1.1\r\nHost: localhost\r\n"
        for headers, code in ((b"X-Large: " + b"x" * 8200, 431),
                              (b"Expect: 100-continue", 417)):
            reply = self.raw_request(prefix + headers + b"\r\n\r\n")
            self.assertTrue(reply.startswith(f"HTTP/1.1 {code} ".encode()), reply[:250])
            self.assertNotIn(b"100 Continue", reply)

    def test_wrong_duplicate_and_non_ascii_credentials_are_safe(self):
        for authorization in ("Bearer " + "x" * 32, "Bearer " + "\xe9" * 32, "Basic a"):
            status, data = self.request("GET", "/api/v1/capabilities",
                                        headers={"Authorization": authorization})
            self.assertEqual((status, data["code"]), (401, "Q3-HTTPS-AUTH"))
            self.assertNotIn(authorization, json.dumps(data))
        key = SECRET.encode()
        reply = self.raw_request(b"GET /api/v1/capabilities HTTP/1.1\r\nHost: localhost\r\n"
                                 b"Authorization: Bearer " + key + b"\r\nAuthorization: Bearer "
                                 + key + b"\r\n\r\n")
        self.assertTrue(reply.startswith(b"HTTP/1.1 401 "))
        self.assertNotIn(key, reply)

    def test_auth_before_rate_budget_and_expensive_work(self):
        with patch.object(self.server, "rate_allowed", return_value=False) as budget, patch.object(render_api, "run_worker") as worker:
            self.assertEqual(self.request("GET", "/api/v1/capabilities", authorized=False)[0], 401)
            self.assertEqual(self.request("POST", "/api/v1/compare", b"{}", authorized=False)[0], 401)
            budget.assert_not_called()
            self.assertEqual(self.request("GET", "/api/v1/capabilities")[0], 429)
            self.assertEqual(self.request("POST", "/api/v1/compare", b"{}")[0], 429)
            self.assertEqual(budget.call_count, 2)
            worker.assert_not_called()

    def test_slow_body_does_not_reserve_compute_slot(self):
        with socket.create_connection(self.server.server_address, timeout=3) as conn:
            conn.sendall(b"POST /api/v1/compare HTTP/1.1\r\nHost: localhost\r\n"
                         b"Authorization: Bearer " + SECRET.encode() + b"\r\n"
                         b"Content-Type: application/json\r\nContent-Length: 10\r\n\r\n{")
            status, result = self.request("POST", "/api/v1/simulate", b'{"source":"qubit q"}')
            self.assertEqual((status, result["status"]), (200, "pass"))

    def test_worker_timeout_is_real_and_slot_is_released(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "sleep_worker.py"
            script.write_text("import time; time.sleep(5)", encoding="utf-8")
            with patch.object(render_api, "WORKER", script), patch.object(
                    self.server, "limits", replace(self.server.limits, timeout_seconds=0.15)):
                status, result = self.request("POST", "/api/v1/compare", b"{}")
                self.assertEqual((status, result["code"]), (504, "Q3-HTTPS-TIMEOUT"))
        self.assertEqual(self.request("POST", "/api/v1/simulate", b'{"source":"qubit q"}')[0], 200)

    def test_child_does_not_receive_parent_secret_and_output_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "output_worker.py"
            script.write_text(
                "import os, resource, sys\n"
                "assert 'Q3HASH_API_KEY' not in os.environ\n"
                "resource.setrlimit(resource.RLIMIT_FSIZE, (4096, 4096))\n"
                "sys.stdout.write('x' * 262145)\n", encoding="utf-8")
            with patch.object(render_api, "WORKER", script), patch.dict(os.environ, {"Q3HASH_API_KEY": SECRET}):
                status, result = self.request("POST", "/api/v1/compare", b"{}")
                self.assertEqual((status, result["code"]), (500, "Q3-HTTPS-WORKER"))
                self.assertNotIn(SECRET, json.dumps(result))

    def test_worker_conflicting_or_malformed_identity_never_succeeds(self):
        for result in ([], {"schema": "q3hash.web-response", "schema_version": 1,
                            "kind": "simulation", "status": "pass", "engine_version": "0.5.0",
                            "source_commit": "0" * 40}):
            with patch.object(render_api, "run_worker", return_value=(200, result)):
                status, data = self.request("POST", "/api/v1/simulate", b'{"source":"qubit q"}')
                self.assertEqual((status, data["kind"]), (500, "error"))

    def test_worker_simulation_status_requires_normalised_basis_evidence(self):
        raw = b'{"source":"qubit q"}'
        _, result = render_api.run_worker("simulate", raw, self.server.limits)
        result["basis"][0]["probability"] = 0
        with patch.object(render_api, "run_worker", return_value=(200, result)):
            status, data = self.request("POST", "/api/v1/simulate", raw)
        self.assertEqual((status, data["code"]), (500, "Q3-HTTPS-WORKER"))
        self.assertNotIn("basis", data)

    def test_worker_verification_status_requires_matching_numerical_evidence(self):
        raw = json.dumps(dict(logical_source="qubit q", physical_source="qubit q", encoding={
            "schema": "q3hash.basis-encoding", "schema_version": 1, "kind": "basis-injection",
            "logical_dimensions": [2], "physical_dimensions": [2], "physical_basis_indices": [0, 1],
        })).encode()
        for label, residual, nested_label in (("pass", 2, "pass"), ("fail", 0, "fail"),
                                               ("unsupported", 0, "unsupported"), ("pass", 0, "fail")):
            with self.subTest(label=label, residual=residual, nested_label=nested_label):
                _, result = render_api.run_worker("verify", raw, self.server.limits)
                result["status"] = label
                result["verification"].update(status=nested_label, subspace_residual=residual)
                with patch.object(render_api, "run_worker", return_value=(200, result)):
                    status, data = self.request("POST", "/api/v1/verify", raw)
                self.assertEqual((status, data["code"]), (500, "Q3-HTTPS-WORKER"))
                self.assertNotIn("verification", data)

    def test_partial_comparison_cannot_hide_bad_or_missing_candidate_evidence(self):
        for fault in ("leakage", "missing-candidate", "coverage-count"):
            with self.subTest(fault=fault):
                _, result = render_api.run_worker("compare", b"{}", self.server.limits)
                if fault == "leakage":
                    row = next(row for row in result["rows"] if row["source_status"] == "pass")
                    row["verification"]["leakage_norm"] = 1
                elif fault == "missing-candidate":
                    result["rows"] = [row for row in result["rows"] if row["source_status"] != "unimplemented"]
                else:
                    result["source_status_counts"]["unimplemented"] = 0
                with patch.object(render_api, "run_worker", return_value=(200, result)):
                    status, data = self.request("POST", "/api/v1/compare", b"{}")
                self.assertEqual((status, data["code"]), (500, "Q3-HTTPS-WORKER"))
                self.assertNotIn("rows", data)

    def test_invalid_payloads_do_not_echo_program_details(self):
        for body in (b'{"source":"private-test-source"}', b'{"source":"\\ud800"}',
                     b'{"source":"qubit q","source":"qubit r"}', b'{"source":NaN}',
                     b'{"source":' + b'[' * 1200 + b'0' + b']' * 1200 + b'}',
                     b'{"source":"\xff"}'):
            status, data = self.request("POST", "/api/v1/simulate", body)
            self.assertEqual((status, data["kind"], data["status"]), (422, "error", "invalid"))
            self.assertNotIn("private-test-source", json.dumps(data))

    def test_maximum_raw_input_is_not_truncated_by_worker_protocol(self):
        # Unicode and escaped quotes expand when wrapped in a second JSON document.
        program = "qutrit q\n# " + '\u03c0' * 3000
        raw = json.dumps({"source": program}, ensure_ascii=False).encode()
        raw += b" " * (16384 - len(raw))
        status, data = self.request("POST", "/api/v1/simulate", raw)
        self.assertEqual((status, data["status"]), (200, "pass"))


class SourceIdentityTests(unittest.TestCase):
    def test_startup_rejects_stale_or_modified_checked_file(self):
        from deployment.contract import verify_engine_source

        original = Path.read_bytes
        def changed(path):
            return b"tampered" if path.name == "core.py" else original(path)

        with patch.object(Path, "read_bytes", changed):
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                verify_engine_source(ROOT, DEPLOYMENT)
        with self.assertRaisesRegex(ValueError, "full deployment commit"):
            verify_engine_source(ROOT, "short")

    def test_invalid_resource_settings_fail_closed(self):
        for key, value in (("timeout_seconds", float("nan")), ("request_bytes", 32768),
                           ("memory_mib", 1024), ("output_bytes", 1), ("cpu_seconds", 100)):
            with self.subTest(limit=key), self.assertRaises(ValueError):
                render_api.Limits(**{key: value})


if __name__ == "__main__":
    unittest.main()
