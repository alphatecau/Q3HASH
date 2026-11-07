#!/usr/bin/env python3
"""Opt-in staging HTTPS acceptance checks. No secrets printed or stored.

Run from the repository root:
  Q3HASH_API_URL=https://q3-u12l.onrender.com python tools/live_acceptance.py
Requires Q3HASH_API_KEY in the environment and installed q3hash package.
"""
from __future__ import annotations

import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from q3hash import BasisEncoding

BASE = os.getenv("Q3HASH_API_URL", "https://q3-u12l.onrender.com").rstrip("/")
KEY = os.getenv("Q3HASH_API_KEY", "")
if not BASE.startswith("https://") or len(KEY) < 32:
    sys.exit("Set an HTTPS Q3HASH_API_URL and Q3HASH_API_KEY (>=32 chars).")

def call(method, path, payload=None, *, authenticated=True, origin=None):
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if authenticated:
        headers["Authorization"] = "Bearer " + KEY
    if origin:
        headers["Origin"] = origin
    req = Request(BASE + path, data=data, headers=headers, method=method)
    for attempt in range(4):
        try:
            with urlopen(req, timeout=100) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            try:
                result = json.load(exc)
            except (ValueError, UnicodeError):
                result = {}
            if exc.code in (429, 503) and attempt < 3:
                time.sleep(2)
                continue
            return exc.code, result

checks = []
def check(label, method, path, payload, predicate, **kwargs):
    try:
        code, body = call(method, path, payload, **kwargs)
        passed = bool(predicate(code, body))
        print(f"{'PASS' if passed else 'FAIL'} | {label} | HTTP {code} | {body.get('status', 'n/a')}")
    except (URLError, TimeoutError, ValueError, OSError) as exc:
        passed = False
        print(f"FAIL | {label} | {type(exc).__name__}")
    checks.append(passed)

logical = "qutrit q\nshift q"
physical = "qubit a\nqubit b\nsum a b\nsum b a\nshift b"
good = BasisEncoding((3,), (2, 2), (0, 1, 2)).to_dict()
bad = BasisEncoding((3,), (4,), (0, 1, 2)).to_dict()
check("Public health", "GET", "/healthz", None,
      lambda c, b: c == 200 and b.get("status") == "ok", authenticated=False)
check("Authentication required", "GET", "/api/v1/capabilities", None,
      lambda c, b: c == 401, authenticated=False)
check("Browser Origin blocked", "GET", "/api/v1/capabilities", None,
      lambda c, b: c == 403, origin="https://example.invalid")
check("Capabilities", "GET", "/api/v1/capabilities", None,
      lambda c, b: c == 200 and b.get("public_browser_access") is False
      and set(b.get("endpoints", [])) == {"simulate", "verify", "compare"})
check("Qutrit shift", "POST", "/api/v1/simulate", {"source": logical},
      lambda c, b: c == 200 and b.get("status") == "pass"
      and b.get("dimensions") == [3]
      and abs(b["basis"][1]["probability"] - 1) < 1e-10)
check("Correct encoding equivalence", "POST", "/api/v1/verify",
      {"logical_source": logical, "physical_source": physical, "encoding": good},
      lambda c, b: c == 200 and b.get("status") == "pass"
      and b.get("verification", {}).get("leakage_norm", 1) <= 1e-10)
check("Incorrect encoding fails", "POST", "/api/v1/verify",
      {"logical_source": logical, "physical_source": "qudit 4 q\nshift q", "encoding": bad},
      lambda c, b: c == 200 and b.get("status") == "fail"
      and b.get("verification", {}).get("leakage_norm", 0) > 0.5)
check("Malformed encoding rejected", "POST", "/api/v1/verify",
      {"logical_source": logical, "physical_source": physical, "encoding": {}},
      lambda c, b: c == 422 and b.get("status") == "invalid")
check("Fixed three-way benchmark", "POST", "/api/v1/compare", {},
      lambda c, b: c == 200 and b.get("kind") == "comparison"
      and b.get("status") == "partial" and b.get("synthetic") is True
      and b.get("measured_hardware") is False and b.get("front_partial") is True
      and b.get("source_status_counts", {}).get("unimplemented") == 1)
check("Reject injected fixture path", "POST", "/api/v1/compare",
      {"source": "/etc/passwd"},
      lambda c, b: c == 422 and b.get("status") == "invalid")
print(f"RESULT: {sum(checks)}/{len(checks)} checks passed")
sys.exit(0 if all(checks) else 1)
