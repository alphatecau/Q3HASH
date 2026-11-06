"""Exercise the authenticated hosted contract over local HTTP or authorised HTTPS."""
from __future__ import annotations

import argparse
import cmath
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import secrets
import ssl
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deployment.contract import COMMIT, MAX_RESPONSE_BYTES, TOKEN
from deployment.render_api import make_server

ENGINE_SOURCE = "19e44ada3a5a31deec7875c403b2efc0ee4c8488"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@contextmanager
def local_server(key, commit):
    with make_server("127.0.0.1", 0, key, deployment_commit=commit, interval_seconds=0) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join()


def encoding(logical, physical):
    return dict(schema="q3hash.basis-encoding", schema_version=1, kind="basis-injection",
                logical_dimensions=logical, physical_dimensions=physical,
                physical_basis_indices=list(range(math.prod(logical))))


def check_state(result, dims, amplitudes):
    assert result["dimensions"] == dims
    assert result["basis_order"] == "last-register-fastest"
    assert result["state_size"] == len(amplitudes) == math.prod(dims)
    assert len(result["basis"]) == len(amplitudes)
    for i, (row, amplitude) in enumerate(zip(result["basis"], amplitudes)):
        assert row["index"] == i and abs(complex(*row["amplitude"]) - amplitude) < 1e-12
        assert math.isclose(row["probability"], abs(amplitude) ** 2, abs_tol=1e-12)
    assert math.isclose(sum(row["probability"] for row in result["basis"]), 1, abs_tol=1e-12)


def acceptance(origin, key, commit, interval):
    opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    responses = {}
    checks = []
    last_request = float("-inf")

    def check(name, operation, *, body=None, raw=None, http=200, status="pass", bearer=key, extra=None):
        nonlocal last_request
        time.sleep(max(0, interval - (time.monotonic() - last_request)))
        last_request = time.monotonic()
        path = "/healthz" if operation == "health" else "/api/v1/" + operation
        headers = {"Accept": "application/json", **(extra or {})}
        if bearer is not None:
            headers["Authorization"] = "Bearer " + bearer
        if body is not None:
            raw = json.dumps(body, allow_nan=False).encode()
        if raw is not None:
            headers["Content-Type"] = "application/json"
        method = "GET" if operation in ("health", "capabilities") else "POST"
        request = Request(origin + path, data=raw, headers=headers, method=method)
        try:
            reply = opener.open(request, timeout=35)
        except HTTPError as error:
            reply = error
        with reply:
            payload = reply.read(MAX_RESPONSE_BYTES + 1)
            assert reply.status == http, f"{name}: expected HTTP {http}, got {reply.status}"
            assert 0 < len(payload) <= MAX_RESPONSE_BYTES and key.encode() not in payload, name
            assert reply.headers.get_content_type() == "application/json", name
            assert reply.headers.get("Cache-Control") == "no-store", name
            assert reply.headers.get("Access-Control-Allow-Origin") is None, name
        result = json.loads(payload)
        assert result["status"] == status, name
        if operation != "health":
            assert (result["schema"], result["schema_version"]) == ("q3hash.web-response", 2), name
            assert (result["engine_version"], result["web_version"]) == ("0.5.0", "0.6.0-rc.1"), name
            assert (result["source_commit"], result["deployment_commit"]) == (ENGINE_SOURCE, commit), name
            assert (result["kind"] == "error") == (http != 200), name
        checks.append(dict(check=name, operation=operation, http_status=http, status=status))
        responses[name] = result
        return result

    check("health", "health", bearer=None, status="ok")
    check("missing_auth", "capabilities", bearer=None, http=401, status="error")
    check("anonymous_compute", "compare", body={}, bearer=None, http=401, status="error")
    check("incorrect_auth", "capabilities", bearer="invalid-" + "x" * 32, http=401, status="error")
    check("browser_origin", "capabilities", extra={"Origin": "https://browser.example"}, http=403, status="invalid")
    cap = check("capabilities", "capabilities")
    assert cap["endpoints"] == ["simulate", "verify", "compare"]
    assert cap["synthetic_hardware_only"] and not cap["public_browser_access"]

    qutrit = "qutrit q\nshift q"
    check_state(check("simulate", "simulate", body={"source": qutrit}), [3], [0, 1, 0])
    w = cmath.exp(2j * math.pi / 3)
    check_state(check("qutrit_fourier", "simulate", body={"source": qutrit + "\nfourier q"}),
                [3], [1 / math.sqrt(3), w / math.sqrt(3), w**2 / math.sqrt(3)])
    a = 1 / math.sqrt(2)
    for name, dims, expected in (("bell", [2, 2], [a, 0, 0, a]),
                                  ("mixed", [2, 3], [a, 0, 0, 0, a, 0]),
                                  ("qutrit_entangled", [3, 3], [1 / math.sqrt(3) if i in (0, 4, 8) else 0 for i in range(9)])):
        target, control = ("qubit", "qubit") if name == "bell" else ("qutrit", "qubit" if name == "mixed" else "qutrit")
        source = f"{control} c\n{target} t\nfourier c\nsum c t"
        check_state(check(name, "simulate", body={"source": source}), dims, expected)
    check_state(check("qudit", "simulate", body={"source": "qudit 4 q\nfourier q"}), [4], [0.5] * 4)

    def verify(name, logical, physical, basis, status):
        return check(name, "verify", body=dict(logical_source=logical, physical_source=physical, encoding=basis),
                     status=status)["verification"]

    source = (ROOT / "examples/physical-qutrit-shift-binary.q3").read_text(encoding="utf-8")
    binary = json.loads((ROOT / "examples/qutrit-binary.encoding.json").read_text(encoding="utf-8"))
    good = verify("verify", qutrit, source, binary, "pass")
    assert good["subspace_residual"] == good["leakage_norm"] == 0
    assert good["physical_size"] == 4
    wrong = verify("negative", qutrit, "qutrit q", encoding([3], [3]), "fail")
    assert wrong["subspace_residual"] > wrong["tolerance"] and wrong["leakage_norm"] == 0
    leak = verify("leakage", qutrit, "qudit 4 q\nshift q", encoding([3], [4]), "fail")
    assert math.isclose(leak["leakage_norm"], 1, abs_tol=1e-12)
    phase = verify("relative_phase", "qubit q", "qubit q\nfourier q\nshift q\nfourier q",
                   encoding([2], [2]), "fail")
    assert math.isclose(phase["subspace_residual"], 2, abs_tol=1e-12) and phase["leakage_norm"] == 0
    assert phase["logical_unitarity_error"] < 1e-12 and phase["physical_unitarity_error"] < 1e-12
    large = check("unsupported", "simulate", body={"source": "qudit 9 q\nqudit 8 r"}, status="unsupported")
    assert large["state_size"] == "72" and "basis" not in large
    too_large = "\n".join(f"qudit 32 q{i}" for i in range(14))
    large = check("unsupported_large", "simulate", body={"source": too_large}, status="unsupported")
    assert large["state_size"] == str(32 ** 14)
    dense = verify("unsupported_verification", "qubit q", "qudit 8 q\nqudit 8 r", encoding([2], [8, 8]), "unsupported")
    assert dense["physical_size"] == "64" and dense["subspace_residual"] is None
    broken = {**encoding([3], [3]), "physical_basis_indices": [0, 1, 1]}
    check("invalid_mapping", "verify", body=dict(logical_source=qutrit, physical_source=qutrit, encoding=broken), http=422, status="invalid")
    check("invalid_dimension", "simulate", body={"source": "qudit 33 q"}, http=422, status="invalid")
    check("invalid_json", "simulate", raw=b"{", http=422, status="invalid")
    check("duplicate_json", "simulate", raw=b'{"source":"qubit q","source":"qutrit q"}', http=422, status="invalid")
    check("oversized", "simulate", raw=b"x" * (cap["max_request_bytes"] + 1), http=413, status="invalid")

    comparison = check("compare", "compare", body={}, status="partial")
    rows = {tuple(row["dimensions"]): row for row in comparison["rows"]}
    expected = {(3,): ([40000, 60000], True), (2, 2): ([390000, 490000], False), (2, 3): ([5000, 8000], True)}
    assert comparison["synthetic"] and comparison["front_partial"] and not comparison["measured_hardware"]
    assert set(rows) == {*expected, (3, 2)}
    assert rows[(3, 2)]["source_status"] == "unimplemented" and rows[(3, 2)]["verification"] is None
    for dims, (duration, on_front) in expected.items():
        row = rows[dims]
        assert row["verification"]["status"] == "pass" and row["verification"]["physical_size"] == math.prod(dims)
        assert row["critical_path_ps"] == duration and row["on_front"] is on_front
    return {"capture": {"transport": "https" if origin.startswith("https:") else "loopback-http",
                        "deployment_commit": commit, "source_commit": ENGINE_SOURCE},
            "checks": checks, "responses": responses}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True, help="Full deployment commit SHA under test")
    parser.add_argument("--https-origin", help="Bare authorised HTTPS origin. Read bearer from Q3HASH_API_KEY.")
    parser.add_argument("--interval", type=float, default=0.4, help="Seconds between HTTPS calls")
    parser.add_argument("--output", type=Path, help="Write accepted responses without credentials")
    parser.add_argument("--validate-schema", action="store_true", help="Validate response fixtures with jsonschema")
    args = parser.parse_args()
    if not COMMIT.fullmatch(args.commit):
        parser.error("--commit must be a 40-character lowercase Git SHA")
    if args.https_origin:
        origin = urlsplit(args.https_origin)
        key = os.environ.get("Q3HASH_API_KEY", "")
        if (origin.scheme != "https" or not origin.hostname or origin.username or origin.password or origin.query or
                origin.fragment or origin.path not in ("", "/") or not TOKEN.fullmatch(key) or not 0.25 <= args.interval <= 60):
            parser.error("HTTPS mode requires a bare HTTPS origin, a server-side key and a valid request interval")
        result = acceptance(args.https_origin.rstrip("/"), key, args.commit, args.interval)
    else:
        key = secrets.token_urlsafe(36)
        with local_server(key, args.commit) as origin:
            result = acceptance(origin, key, args.commit, 0)
    if args.validate_schema:
        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT / "docs/contracts/q3hash-hosted-v2.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        for response in result["responses"].values():
            Draft202012Validator(schema).validate(response)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for item in result["checks"]:
        print(f"PASS {item['check']}: HTTP {item['http_status']}, {item['status']}")
    print(f"PASS {len(result['checks'])} hosted API checks ({result['capture']['transport']}).")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, OSError, ValueError) as error:
        # No credentials, remote response bodies or request details in output.
        print(f"Hosted API acceptance failed ({type(error).__name__})"
              + (f": {error}" if isinstance(error, AssertionError) else ""), file=sys.stderr)
        raise SystemExit(1)
