"""Authenticated Q3HASH research API behind a managed HTTPS ingress."""
from __future__ import annotations

from dataclasses import dataclass
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))

from deployment.contract import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, OPERATIONS, TOKEN, verify_engine_source

WORKER = ROOT / "deployment" / "worker.py"
SECRET_ENV = "Q3HASH_API_KEY"
HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
MAX_HEADER_BYTES = 8192
READ_SECONDS = 5


@dataclass(frozen=True)
class Limits:
    request_bytes: int = MAX_REQUEST_BYTES
    output_bytes: int = MAX_RESPONSE_BYTES
    timeout_seconds: float = 12
    cpu_seconds: int = 8
    memory_mib: int = 384

    def __post_init__(self):
        if (not 1024 <= self.request_bytes <= MAX_REQUEST_BYTES or
                not 4096 <= self.output_bytes <= MAX_RESPONSE_BYTES or
                not 0 < self.timeout_seconds <= 15 or not 1 <= self.cpu_seconds <= 8 or
                not 64 <= self.memory_mib <= 384):
            raise ValueError("Worker limits fall outside the hosted safety bounds")

    @classmethod
    def from_environment(cls):
        return cls(
            request_bytes=int(os.environ.get("Q3HASH_MAX_REQUEST_BYTES", MAX_REQUEST_BYTES)),
            output_bytes=int(os.environ.get("Q3HASH_WORKER_OUTPUT_BYTES", MAX_RESPONSE_BYTES)),
            timeout_seconds=float(os.environ.get("Q3HASH_WORKER_TIMEOUT_SECONDS", "12")),
            cpu_seconds=int(os.environ.get("Q3HASH_WORKER_CPU_SECONDS", "8")),
            memory_mib=int(os.environ.get("Q3HASH_WORKER_MEMORY_MIB", "384")),
        )


class BoundedServer(ThreadingHTTPServer):
    request_queue_size = 12

    def __init__(self, address, api_key, identity, limits, interval_seconds):
        if not TOKEN.fullmatch(api_key):
            raise ValueError("Q3HASH_API_KEY requires 32–256 URL-safe ASCII characters")
        if not 0 <= interval_seconds <= 60:
            raise ValueError("Invalid research rate interval")
        self.api_key = api_key.encode("ascii")
        self.identity = identity
        self.limits = limits
        self.compute_slot = threading.BoundedSemaphore(1)
        self.connection_slots = threading.BoundedSemaphore(8)
        self.interval_seconds = interval_seconds
        self._rate_lock = threading.Lock()
        self._last_start = float("-inf")
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.connection_slots.acquire(blocking=False):
            self.shutdown_request(request)
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

    def handle_error(self, request, client_address):
        # Socket failures and unhandled errors must not dump request state.
        pass

    def rate_allowed(self):
        with self._rate_lock:
            now = time.monotonic()
            if now - self._last_start < self.interval_seconds:
                return False
            self._last_start = now
            return True


def run_worker(operation, raw, limits):
    command = [sys.executable, "-I", "-B", str(WORKER), operation,
               str(limits.request_bytes), str(limits.memory_mib), str(limits.cpu_seconds),
               str(limits.output_bytes)]
    # The child has a hard file-size limit and no service secrets in its environment.
    # No shell, inherited input handles, unbounded pipes, or exception text.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(command, cwd=ROOT, input=raw, stdout=output,
                                stderr=subprocess.DEVNULL, env={"LC_ALL": "C"},
                                timeout=limits.timeout_seconds, check=False)
        output.seek(0)
        data = output.read(limits.output_bytes + 1)
    if result.returncode or len(data) > limits.output_bytes:
        raise ValueError("Worker process failed")
    value = json.loads(data)
    if (type(value) is not dict or value.keys() != {"http_status", "payload"} or
            type(value["http_status"]) is not int or value["http_status"] not in (200, 422, 500)):
        raise ValueError("Invalid worker response")
    return value["http_status"], value["payload"]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Q3HASH-API"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(READ_SECONDS)
        self.read_deadline = threading.Timer(READ_SECONDS, self._abort_slow_read)
        self.read_deadline.daemon = True
        self.read_deadline.start()

    def finish(self):
        self.read_deadline.cancel()
        super().finish()

    def _abort_slow_read(self):
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def log_message(self, fmt, *args):
        pass

    def send_json(self, status, payload, extra_headers=()):
        body = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.close_connection = True
        self.send_response(status)
        for name, value in (
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
            ("Connection", "close"),
            *extra_headers,
        ):
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def reject(self, http_status, code, message):
        invalid = 400 <= http_status < 500 and http_status not in (401, 429)
        payload = self.server.identity.envelope("error", "invalid" if invalid else "error",
                                                code=code, message=message)
        headers = {401: (("WWW-Authenticate", "Bearer"),),
                   429: (("Retry-After", str(max(1, int(self.server.interval_seconds + 0.999)))),)}
        self.send_json(http_status, payload, headers.get(http_status, ()))

    def send_error(self, code, message=None, explain=None):
        # BaseHTTPRequestHandler errors use safe JSON too, with no echoed input.
        status = 405 if code == 501 else code
        self.reject(status, "Q3-HTTPS-HTTP", "Invalid or unsupported HTTP request")

    def handle_expect_100(self):
        self.reject(417, "Q3-HTTPS-EXPECT", "Expect is not supported")
        return False

    def _valid_headers(self):
        raw = list(self.headers.raw_items())
        if (self.headers.defects or len(self.headers.get_all("Host", [])) != 1 or
                not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?|\[[0-9A-Fa-f:]+\](?::[0-9]{1,5})?",
                                 self.headers["Host"]) or
                any(not HEADER_NAME.fullmatch(name) or any(ord(ch) < 32 and ch != "\t" or ord(ch) == 127
                                                          for ch in value) for name, value in raw)):
            self.reject(400, "Q3-HTTPS-HEADERS", "Malformed request headers")
            return False
        if sum(len(name) + len(value) + 4 for name, value in raw) > MAX_HEADER_BYTES:
            self.reject(431, "Q3-HTTPS-HEADERS", "Request headers exceed the permitted length")
            return False
        if self.headers.get_all("Transfer-Encoding", []):
            self.reject(400, "Q3-HTTPS-TRANSFER", "Transfer-Encoding is not supported")
            return False
        if self.headers.get_all("Expect", []):
            self.reject(417, "Q3-HTTPS-EXPECT", "Expect is not supported")
            return False
        return True

    def _secure_request(self):
        if self.headers.get_all("Origin", []):
            self.reject(403, "Q3-HTTPS-ORIGIN", "Browser-origin access is disabled")
            return False
        auth = self.headers.get_all("Authorization", [])
        if len(auth) == 1 and auth[0].startswith("Bearer "):
            token = auth[0][7:]
            if TOKEN.fullmatch(token) and hmac.compare_digest(token.encode("ascii"), self.server.api_key):
                return True
        self.reject(401, "Q3-HTTPS-AUTH", "Authentication required")
        return False

    def _check_rate(self):
        if self.server.rate_allowed():
            return True
        self.reject(429, "Q3-HTTPS-RATE", "Research request limit exceeded")
        return False

    def do_GET(self):
        self.read_deadline.cancel()
        if not self._valid_headers():
            return
        if self.headers.get_all("Content-Length", []) not in ([], ["0"]):
            self.reject(400, "Q3-HTTPS-LENGTH", "GET and HEAD do not accept a request body")
            return
        if self.path == "/healthz":
            self.send_json(200, {"status": "ok"})
            return
        if not self._secure_request():
            return
        if self.path != "/api/v1/capabilities":
            self.reject(404, "Q3-HTTPS-NOTFOUND", "Endpoint not found")
            return
        if self.command != "GET":
            self.reject(405, "Q3-HTTPS-METHOD", "Use GET for capabilities")
            return
        if self._check_rate():
            self.send_json(200, self.server.identity.capabilities(self.server.limits.request_bytes))

    def _read_body(self):
        encodings = self.headers.get_all("Content-Encoding", [])
        content_types = self.headers.get_all("Content-Type", [])
        if (encodings not in ([], ["identity"]) or len(content_types) != 1 or
                content_types[0].split(";", 1)[0].strip().lower() != "application/json"):
            self.reject(415, "Q3-HTTPS-TYPE", "Send uncompressed application/json")
            return None
        lengths = self.headers.get_all("Content-Length", [])
        if not lengths:
            self.reject(411, "Q3-HTTPS-LENGTH", "Content-Length is required")
            return None
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0]):
            self.reject(400, "Q3-HTTPS-LENGTH", "Invalid or repeated Content-Length")
            return None
        size = int(lengths[0])
        if not 1 <= size <= self.server.limits.request_bytes:
            self.reject(413, "Q3-HTTPS-SIZE", "Request exceeds permitted length")
            return None
        raw = self.rfile.read(size)
        if len(raw) != size:
            self.reject(400, "Q3-HTTPS-LENGTH", "Incomplete request body")
            return None
        return raw

    def do_POST(self):
        if not self._valid_headers() or not self._secure_request():
            return
        operation = self.path.removeprefix("/api/v1/")
        if operation == self.path or operation not in OPERATIONS:
            self.reject(404, "Q3-HTTPS-NOTFOUND", "Endpoint not found")
            return
        raw = self._read_body()
        self.read_deadline.cancel()
        if raw is None:
            return
        if not self.server.compute_slot.acquire(blocking=False):
            self.reject(503, "Q3-HTTPS-BUSY", "Research worker is busy")
            return
        try:
            if self._check_rate():
                self._compute(operation, raw)
        finally:
            self.server.compute_slot.release()

    def _compute(self, operation, raw):
        try:
            status, raw_payload = run_worker(operation, raw, self.server.limits)
            if status == 200:
                payload = self.server.identity.result(operation, raw_payload)
                # Check the final wire size as well as the raw child output limit.
                if len(json.dumps(payload, allow_nan=False).encode("utf-8")) > MAX_RESPONSE_BYTES:
                    raise ValueError("Response budget exceeded")
        except subprocess.TimeoutExpired:
            self.reject(504, "Q3-HTTPS-TIMEOUT", "Research operation timed out")
            return
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            status = 500
        if status == 200:
            self.send_json(status, payload)
        elif status == 422:
            self.reject(422, "Q3-HTTPS-INPUT", "Invalid JSON, Q3# source, encoding or research limits")
        else:
            self.reject(500, "Q3-HTTPS-WORKER", "Research worker failed")

    def do_OPTIONS(self):
        self.reject(405, "Q3-HTTPS-METHOD", "Cross-origin access is disabled")

    def do_HEAD(self):
        self.do_GET()


def make_server(host, port, api_key, *, deployment_commit, limits=None, interval_seconds=0.25):
    identity = verify_engine_source(ROOT, deployment_commit)
    return BoundedServer((host, port), api_key, identity, limits or Limits(), interval_seconds)


def main():
    try:
        deployment_commit = os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("Q3HASH_DEPLOYMENT_COMMIT", "")
        rate_interval = float(os.environ.get("Q3HASH_RATE_INTERVAL_SECONDS", "0.25"))
        if rate_interval < 0.25:
            raise ValueError("The hosted rate interval must be at least 0.25 seconds")
        server = make_server("0.0.0.0", int(os.environ.get("PORT", "10000")),
                             os.environ.get(SECRET_ENV, ""), deployment_commit=deployment_commit,
                             limits=Limits.from_environment(), interval_seconds=rate_interval)
    except (KeyError, OSError, TypeError, ValueError):
        raise SystemExit("Q3HASH startup failed: check installed engine, source manifest and server configuration") from None
    with server:
        # server_close waits for active request threads, each with bounded work.
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        print("Q3HASH authenticated research API listening behind HTTPS proxy", flush=True)
        server.serve_forever(poll_interval=0.1)


if __name__ == "__main__":
    main()
