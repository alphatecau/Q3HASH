"""Private, HTTPS-proxy-ready API adapter for Q3HASH research, not the localhost UI.

Deploy behind Render's managed TLS. This adapter deliberately does not support
browser-to-API calls: Q3HASH_API_KEY must never be embedded in public JavaScript.
"""
from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "deployment" / "worker.py"
SECRET_ENV = "Q3HASH_API_KEY"
MAX_BODY = 16_384
MAX_WORKER_OUTPUT = 524_288
WORKER_TIMEOUT_SECONDS = 12
ROUTES = frozenset(("/api/v1/simulate", "/api/v1/verify", "/api/v1/compare"))


def envelope(status: str, code: str, message: str) -> dict:
    return {"schema": "q3hash.web-response", "schema_version": 1,
            "kind": "error", "status": status, "code": code, "message": message}


class BoundedServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 12
    allow_reuse_address = True

    def __init__(self, address, handler, api_key: str, *, interval_seconds=0.25):
        if len(api_key) < 32:
            raise ValueError("Q3HASH_API_KEY must contain at least 32 characters")
        self.api_key = api_key
        self.compute_slot = threading.BoundedSemaphore(1)
        self.connection_slots = threading.BoundedSemaphore(8)
        self.interval_seconds = interval_seconds
        self._rate_lock = threading.Lock()
        self._last_start = 0.0
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self.connection_slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connection_slots.release()

    def rate_allowed(self):
        with self._rate_lock:
            now = time.monotonic()
            if now - self._last_start < self.interval_seconds:
                return False
            self._last_start = now
            return True


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Q3HASH-API"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, fmt, *args):
        # Never log requests, query strings, source programs or authorization tokens.
        pass

    def send_json(self, status, payload):
        body = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        for name, value in (
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
            ("Connection", "close"),
        ):
            self.send_header(name, value)
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(body)

    def reject(self, http_status, code, message):
        self.send_json(http_status, envelope(
            "invalid" if http_status in (400, 403, 404, 405, 411, 413, 415, 422) else "error",
            code, message))

    def _secure_request(self):
        # A private API intended for trusted backend/curl clients only.
        # Explicitly reject browser Origin requests: never distribute the key in JS.
        if self.headers.get_all("Origin", []):
            self.reject(403, "Q3-HTTPS-ORIGIN", "Browser-origin access is disabled")
            return False
        auth = self.headers.get_all("Authorization", [])
        if len(auth) != 1 or not auth[0].startswith("Bearer "):
            self.reject(401, "Q3-HTTPS-AUTH", "Authentication required")
            return False
        token = auth[0][7:]
        if not hmac.compare_digest(token, self.server.api_key):
            self.reject(401, "Q3-HTTPS-AUTH", "Authentication required")
            return False
        return True

    def do_GET(self):
        if self.path == "/healthz":
            self.send_json(200, {"status": "ok"})
            return
        if not self._secure_request():
            return
        if self.path == "/api/v1/capabilities":
            self.send_json(200, {"schema": "q3hash.web-response", "schema_version": 1,
                                 "kind": "capabilities", "status": "pass",
                                 "endpoints": ["simulate", "verify", "compare"],
                                 "max_request_bytes": MAX_BODY,
                                 "max_simulated_states": 64,
                                 "max_verified_dimension": 32,
                                 "synthetic_hardware_only": True,
                                 "public_browser_access": False,
                                 "automatic_synthesis": False,
                                 "automatic_dimension_inference": False})
        else:
            self.reject(404, "Q3-HTTPS-NOTFOUND", "Endpoint not found")

    def do_POST(self):
        if not self._secure_request():
            return
        if self.path not in ROUTES:
            self.reject(404, "Q3-HTTPS-NOTFOUND", "Endpoint not found")
            return
        if self.headers.get("Transfer-Encoding") is not None:
            self.reject(400, "Q3-HTTPS-TRANSFER", "Chunked requests are disabled")
            return
        content_types = self.headers.get_all("Content-Type", [])
        if len(content_types) != 1 or content_types[0].split(";", 1)[0].strip().lower() != "application/json":
            self.reject(415, "Q3-HTTPS-TYPE", "Content-Type must be application/json")
            return
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1:
            self.reject(411, "Q3-HTTPS-LENGTH", "One Content-Length is required")
            return
        length = lengths[0]
        if not length.isascii() or not length.isdecimal():
            self.reject(400, "Q3-HTTPS-LENGTH", "Invalid Content-Length")
            return
        size = int(length)
        if not 1 <= size <= MAX_BODY:
            self.reject(413, "Q3-HTTPS-SIZE", "Request exceeds permitted length")
            return
        if not self.server.compute_slot.acquire(blocking=False):
            self.reject(503, "Q3-HTTPS-BUSY", "Research worker is busy")
            return
        try:
            if not self.server.rate_allowed():
                self.reject(429, "Q3-HTTPS-RATE", "Rate limit exceeded")
                return
            raw = self.rfile.read(size)
            if len(raw) != size:
                self.reject(400, "Q3-HTTPS-LENGTH", "Incomplete request body")
                return
            try:
                raw.decode("utf-8", "strict")
            except UnicodeDecodeError:
                self.reject(422, "Q3-HTTPS-INPUT", "Invalid UTF-8 request body")
                return
            command = {"route": self.path, "body": raw.decode("utf-8")}
            try:
                result = subprocess.run(
                    [sys.executable, "-I", str(WORKER)],
                    cwd=ROOT, input=json.dumps(command), text=True,
                    capture_output=True, timeout=WORKER_TIMEOUT_SECONDS, check=False)
            except subprocess.TimeoutExpired:
                self.reject(504, "Q3-HTTPS-TIMEOUT", "Research operation timed out")
                return
            except OSError:
                self.reject(500, "Q3-HTTPS-WORKER", "Research worker unavailable")
                return
            if result.returncode or len(result.stdout) > MAX_WORKER_OUTPUT:
                self.reject(500, "Q3-HTTPS-WORKER", "Research worker failed")
                return
            try:
                value = json.loads(result.stdout)
                code, payload = value["http_status"], value["payload"]
                if type(code) is not int or not 200 <= code <= 599 or type(payload) is not dict:
                    raise ValueError("Invalid worker envelope")
            except (ValueError, TypeError, KeyError):
                self.reject(500, "Q3-HTTPS-WORKER", "Research worker returned an invalid response")
                return
            self.send_json(code, payload)
        finally:
            self.server.compute_slot.release()

    def do_OPTIONS(self):
        self.reject(405, "Q3-HTTPS-METHOD", "Cross-origin access is disabled")

    def do_HEAD(self):
        self.do_GET()


def make_server(host, port, api_key, *, interval_seconds=0.25):
    return BoundedServer((host, port), Handler, api_key, interval_seconds=interval_seconds)


def main():
    key = os.environ.get(SECRET_ENV, "")
    if len(key) < 32:
        raise SystemExit("Set Q3HASH_API_KEY (at least 32 characters) in Render secrets")
    port = int(os.environ.get("PORT", "10000"))
    with make_server("0.0.0.0", port, key) as server:
        print("Q3HASH authenticated research API listening behind HTTPS proxy", flush=True)
        server.serve_forever(poll_interval=0.1)


if __name__ == "__main__":
    main()
