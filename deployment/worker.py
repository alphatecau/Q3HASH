"""Single-request isolated Q3HASH worker. Q3# input is data, never Python."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

from deployment.contract import ENGINE_VERSION, OPERATIONS


def bound_resources(memory_mib, cpu_seconds, output_bytes):
    import resource

    memory_bytes = memory_mib * 1024 * 1024
    # Termux local developer compatibility. Hosted Linux always applies RLIMIT_AS.
    if not sys.base_prefix.startswith(("/data/data/com.termux/files/usr", "/data/user/0/com.termux/files/usr")):
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (output_bytes, output_bytes))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def run(operation, max_body, memory_mib, cpu_seconds, output_bytes):
    bound_resources(memory_mib, cpu_seconds, output_bytes)
    import web_app

    if web_app.__version__ != ENGINE_VERSION:
        raise RuntimeError("Installed engine version mismatch")
    fields = OPERATIONS[operation][1]
    callbacks = {"simulate": web_app.simulate_request, "verify": web_app.verify_request,
                 "compare": web_app.compare_request}
    raw = sys.stdin.buffer.read(max_body + 1)
    if not raw or len(raw) > max_body:
        return 422, None
    try:
        body = web_app._request_object(raw, fields)
        # Reject JSON escape sequences that create invalid Unicode source strings.
        for name in fields:
            if name.endswith("source") and type(body[name]) is str:
                body[name].encode("utf-8", errors="strict")
        return 200, callbacks[operation](body)
    except (ValueError, TypeError, RecursionError):
        # Engine input errors can include user-supplied source. Keep them private.
        return 422, None


if __name__ == "__main__":
    try:
        operation, *limits = sys.argv[1:]
        status, payload = run(operation, *map(int, limits))
        result = json.dumps({"http_status": status, "payload": payload}, allow_nan=False)
    except Exception:
        # No exception text, program contents or filesystem paths cross the boundary.
        result = '{"http_status":500,"payload":null}'
    sys.stdout.write(result)
