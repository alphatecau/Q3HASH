"""Single-request isolated Q3HASH subprocess invoked by render_api.py.

Only restricted Q3# source is parsed; no user code executes as Python or shell.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def bound_resources():
    # Linux Render/Termux resource bounds; fail closed if unavailable.
    import resource
    memory_bytes = 384 * 1024 * 1024
    if not sys.prefix.startswith(("/data/data/com.termux/files/usr", "/data/user/0/com.termux/files/usr")):
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))


def run():
    bound_resources()
    import web_app  # Authenticated adapter dispatches to the unchanged local engine.

    request = json.loads(sys.stdin.read(20_000))
    route = request["route"]
    raw = request["body"].encode("utf-8")
    routes = {
        "/api/v1/simulate": (("source",), web_app.simulate_request),
        "/api/v1/verify": (("logical_source", "physical_source", "encoding"), web_app.verify_request),
        "/api/v1/compare": ((), web_app.compare_request),
    }
    if route not in routes:
        return 404, {"schema": "q3hash.web-response", "schema_version": 1,
                     "kind": "error", "status": "invalid", "code": "Q3-HTTPS-NOTFOUND"}
    fields, callback = routes[route]
    try:
        body = web_app._request_object(raw, fields)
        return 200, callback(body)
    except (web_app.InputError, ValueError, TypeError) as exc:
        return 422, web_app._base("error", "invalid", code="Q3-HTTPS-INPUT",
                                  message=str(exc)[:384])


if __name__ == "__main__":
    try:
        status, payload = run()
    except Exception:
        # Fail closed; never serialize traceback, filesystem paths or program details.
        status, payload = 500, {"schema": "q3hash.web-response", "schema_version": 1,
                                "kind": "error", "status": "error",
                                "code": "Q3-HTTPS-INTERNAL", "message": "Research worker failed"}
    sys.stdout.write(json.dumps({"http_status": status, "payload": payload}, allow_nan=False))
