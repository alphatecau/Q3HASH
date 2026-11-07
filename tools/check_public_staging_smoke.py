"""Read-only, credential-free hosted API smoke checks for staging.

Checks only health, missing authentication and browser-origin rejection.
Never sends bearer credentials or compute requests. Does not certify Sites.
"""
from __future__ import annotations

import argparse
import json
import ssl
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def probe(opener, origin, path, headers=None):
    req = Request(origin + path, headers=headers or {}, method="GET")
    try:
        response = opener.open(req, timeout=90)
    except HTTPError as exc:
        response = exc
    with response:
        raw = response.read(8193)
        if len(raw) > 8192:
            raise AssertionError("Response exceeds smoke-test limit")
        if response.headers.get_content_type() != "application/json":
            raise AssertionError("Unexpected response content type")
        return response.status, json.loads(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", help="Bare HTTPS origin of the staging API")
    parser.add_argument("--commit", help="Expected 40-character deployment SHA")
    args = parser.parse_args()
    parsed = urlsplit(args.origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        parser.error("Provide a bare HTTPS origin with no credentials or path")
    if args.commit and (len(args.commit) != 40 or any(c not in "0123456789abcdef" for c in args.commit)):
        parser.error("--commit requires a lowercase 40-character SHA")
    origin = args.origin.rstrip("/")
    opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    cases = (
        ("health", "/healthz", {}, 200, "ok", None),
        ("missing_auth", "/api/v1/capabilities", {}, 401, "error", "Q3-HTTPS-AUTH"),
        ("browser_origin", "/api/v1/capabilities",
         {"Origin": "https://example.invalid"}, 403, "invalid", "Q3-HTTPS-ORIGIN"),
    )
    for name, path, headers, expected_http, expected_status, expected_code in cases:
        http, payload = probe(opener, origin, path, headers)
        if http != expected_http or payload.get("status") != expected_status:
            raise AssertionError(f"{name}: unexpected HTTP or status: {http}")
        if expected_code and payload.get("code") != expected_code:
            raise AssertionError(f"{name}: unexpected error code")
        if args.commit and name != "health" and payload.get("deployment_commit") != args.commit:
            raise AssertionError(f"{name}: deployment commit mismatch")
        print(f"PASS {name}: HTTP {http}")
    print("PASS: 3 credential-free checks. Sites authentication, quota and expiry remain unverified.")


if __name__ == "__main__":
    main()
