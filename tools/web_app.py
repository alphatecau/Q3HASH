"""Q3HASH v0.6 local web/core research bridge (Python standard library only).

Deliberately localhost-only: not an Internet-facing service or security-hardened
multi-user deployment. All quantum results come from the installed q3hash core.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlsplit

from q3hash import (
    BasisEncoding, CircuitImplementation, HardwareContext, HardwarePlacement,
    HardwareProfile, SearchConstraints, __version__, assess_hardware,
    evaluate_candidates, generate_encodings, logical_from_source,
    probabilities, simulate, verify_equivalence,
)

ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = ROOT / "web"
SCHEMA = "q3hash.web-response"
MAX_REQUEST_BYTES = 16_384
MAX_PROGRAM_CHARACTERS = 4_096
MAX_OPERATIONS = 64
MAX_SIMULATED_STATES = 64
MAX_VERIFIED_DIMENSION = 32
FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


class InputError(ValueError):
    """Safe, client-correctable input error."""


def _pairs(items):
    result = {}
    for name, value in items:
        if name in result:
            raise InputError(f"Duplicate JSON key: {name}")
        result[name] = value
    return result


def _reject_constant(value):
    raise InputError("Non-finite JSON numbers are not permitted")


def _request_object(raw, fields):
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"),
                           object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except (ValueError, UnicodeError) as exc:
        raise InputError("Invalid UTF-8 or JSON input") from exc
    if type(value) is not dict or set(value) != set(fields):
        raise InputError("Unexpected or missing request properties")
    return value


def _program(source):
    if type(source) is not str or not 1 <= len(source) <= MAX_PROGRAM_CHARACTERS:
        raise InputError("Q3# source must be 1–4096 characters")
    try:
        program = logical_from_source(source)
    except (TypeError, ValueError) as exc:
        raise InputError(f"Invalid Q3# program: {exc}") from exc
    if len(program.ir.operations) > MAX_OPERATIONS:
        raise InputError("Program exceeds the 64-operation web limit")
    return program


def _base(kind, status="pass", **kwargs):
    return dict(schema=SCHEMA, schema_version=1, kind=kind, status=status,
                engine_version=__version__, **kwargs)


def _phase(value):
    return None if value is None else [value.real, value.imag]


def _verification(value):
    return dict(status=value.status, reason=value.reason, evidence=value.evidence,
                logical_size=value.logical_size, physical_size=value.physical_size,
                tolerance=value.tolerance, global_phase=_phase(value.global_phase),
                subspace_residual=value.subspace_residual, leakage_norm=value.leakage_norm,
                logical_unitarity_error=value.logical_unitarity_error,
                physical_unitarity_error=value.physical_unitarity_error)


def simulate_request(body):
    program = _program(body["source"])
    if program.state_size > MAX_SIMULATED_STATES:
        return _base("simulation", "unsupported", dimensions=list(program.dimensions),
                     state_size=program.state_size,
                     reason="State size exceeds the 64-basis-state web response limit")
    state = simulate(program.ir)
    probs = probabilities(state)
    return _base("simulation", dimensions=list(program.dimensions), state_size=len(state),
                 operations=len(program.ir.operations),
                 basis=[dict(index=i, amplitude=[z.real, z.imag], probability=probs[i])
                        for i, z in enumerate(state)])


def verify_request(body):
    logical = _program(body["logical_source"])
    physical = _program(body["physical_source"])
    if type(body["encoding"]) is not dict:
        raise InputError("Encoding must be a versioned basis-injection JSON object")
    try:
        encoding = BasisEncoding.from_dict(body["encoding"])
        result = verify_equivalence(logical, physical.ir, encoding,
                                    max_dimension=MAX_VERIFIED_DIMENSION)
    except (TypeError, ValueError) as exc:
        raise InputError(f"Invalid encoding or dimension assignment: {exc}") from exc
    return _base("verification", result.status, verification=_verification(result))


def _fixture(relative):
    # Only paths originating in the repository's checked-in benchmark fixture.
    # The caller cannot provide filesystem paths to this endpoint.
    if type(relative) is not str or not relative.startswith("examples/"):
        raise RuntimeError("Invalid fixture asset path")
    filepath = ROOT / relative
    if filepath.resolve().parent != (ROOT / "examples").resolve():
        raise RuntimeError("Fixture cannot escape the examples directory")
    return filepath.read_text(encoding="utf-8")


def compare_request(_body):
    fixture = json.loads((ROOT / "benchmarks/three-way-qutrit-shift-v1.json").read_text(encoding="utf-8"))
    logical = _program(_fixture(fixture["logical_source"]))
    constraints = SearchConstraints.from_json(_fixture(fixture["constraints"]))
    generation = generate_encodings(logical.dimensions, constraints)
    sources = {}
    implementations = []
    for case in fixture["cases"]:
        encoding = BasisEncoding.from_json(_fixture(case["encoding"]))
        physical = _program(_fixture(case["physical_source"]))
        sources[encoding] = case
        implementations.append(CircuitImplementation(encoding, physical.ir))
    result = evaluate_candidates(logical, generation, tuple(implementations),
                                 tolerance=fixture["tolerance"])
    profile = HardwareProfile.from_json(_fixture(fixture["hardware_profile"]))
    context = HardwareContext.from_json(_fixture(fixture["hardware_context"]))
    placements = tuple(HardwarePlacement(row.candidate_id,
                        tuple(sources[row.candidate.encoding]["placement"]))
                       for row in result.evaluations if row.candidate.encoding in sources)
    hardware = assess_hardware(result, profile, placements, context)
    rows = []
    for candidate_row, physical_row in zip(result.evaluations, hardware.evaluations):
        cost = physical_row.costs
        rows.append(dict(
            name=sources[candidate_row.candidate.encoding]["id"]
                 if candidate_row.candidate.encoding in sources else "unimplemented",
            dimensions=list(candidate_row.candidate.encoding.physical_dimensions),
            source_status=candidate_row.status,
            source_reason=candidate_row.reason_code,
            verification=None if candidate_row.verification is None else _verification(candidate_row.verification),
            resources=None if candidate_row.resources is None else candidate_row.resources.to_dict(),
            target_status=physical_row.status,
            target_reason=physical_row.reason_code,
            active_sites=None if cost is None else cost.active_sites,
            operations=None if cost is None else cost.native_operations,
            two_site_operations=None if cost is None else cost.two_site_operations,
            critical_path_ps=None if cost is None or cost.critical_path_ps is None
                              else [cost.critical_path_ps.lower_ps, cost.critical_path_ps.upper_ps],
            on_front=physical_row.placement_id is not None and physical_row.placement_id in hardware.front_ids,
        ))
    return _base("comparison", "partial" if hardware.front_is_partial else "pass",
                 workload=fixture["benchmark_id"],
                 ranking_scope=hardware.ranking_scope,
                 synthetic=True, measured_hardware=False,
                 hardware_provenance=profile.provenance.kind,
                 front_partial=hardware.front_is_partial,
                 search_complete=generation.completion == "exhausted",
                 verification_calls=result.verification_calls,
                 source_status_counts=result.status_counts,
                 hardware_status_counts=hardware.status_counts,
                 objective_names=list(context.objectives), rows=rows,
                 warning="Synthetic model intervals, not measured quantum-device performance. "
                         "The (3,2) candidate has no supplied circuit; the front is partial.")


class ResearchHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Q3HASH-local/0.6"
    sys_version = ""

    def log_message(self, format, *args):
        # Local requests only; do not print request bodies or code into logs.
        pass

    def _headers(self, status, mime, length):
        self.send_response(status)
        for name, value in (
            ("Content-Type", mime), ("Content-Length", str(length)),
            ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY"),
            ("Content-Security-Policy", "default-src 'none'; script-src 'self'; "
             "style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; "
             "frame-ancestors 'none'; form-action 'none'"),
            ("Connection", "close"),
        ):
            self.send_header(name, value)
        self.end_headers()
        self.close_connection = True

    def _bytes(self, status, contents, mime):
        self._headers(status, mime, len(contents))
        if self.command != "HEAD":
            self.wfile.write(contents)

    def _json(self, status, value):
        self._bytes(status, json.dumps(value, allow_nan=False, separators=(",", ":"),
                                       sort_keys=True).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, http_status, code, message):
        self._json(http_status, _base("error", "invalid" if http_status < 500 else "error",
                                      code=code, message=message))

    def _trusted_host(self):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1:
            return False
        port = self.server.server_address[1]
        return hosts[0].lower() in (f"localhost:{port}", f"127.0.0.1:{port}")

    def _allow_request(self):
        if not self._trusted_host():
            self._error(403, "Q3-WEB-HOST", "Only the local research console origin is permitted")
            return False
        if self.command == "POST":
            allowed = {"http://" + host for host in
                       (f"127.0.0.1:{self.server.server_address[1]}",
                        f"localhost:{self.server.server_address[1]}")}
            origins = self.headers.get_all("Origin", [])
            if len(origins) > 1 or (origins and origins[0] not in allowed):
                self._error(403, "Q3-WEB-ORIGIN", "Cross-origin requests are not permitted")
                return False
            fetch_site = self.headers.get("Sec-Fetch-Site")
            if fetch_site is not None and fetch_site not in ("same-origin", "none"):
                self._error(403, "Q3-WEB-SITE", "Cross-site requests are not permitted")
                return False
        return True

    def do_GET(self):
        if not self._allow_request():
            return
        path = urlsplit(self.path).path
        if path == "/api/v1/capabilities":
            self._json(200, _base("capabilities", endpoints=["simulate", "verify", "compare"],
                                  web_version="0.6-dev", max_request_bytes=MAX_REQUEST_BYTES,
                                  max_program_characters=MAX_PROGRAM_CHARACTERS,
                                  max_simulated_states=MAX_SIMULATED_STATES,
                                  max_verified_dimension=MAX_VERIFIED_DIMENSION,
                                  local_only=True, synthetic_hardware_only=True,
                                  automatic_synthesis=False, automatic_dimension_inference=False))
            return
        item = FILES.get(path)
        if item is None:
            self._error(404, "Q3-WEB-NOTFOUND", "Endpoint not found")
            return
        filename, mime = item
        try:
            content = (STATIC_ROOT / filename).read_bytes()
        except OSError:
            self._error(500, "Q3-WEB-STATIC", "Local research console asset is missing")
            return
        self._bytes(200, content, mime)

    def do_POST(self):
        if not self._allow_request():
            return
        path = urlsplit(self.path).path
        routes = {"/api/v1/simulate": (("source",), simulate_request),
                  "/api/v1/verify": (("logical_source", "physical_source", "encoding"), verify_request),
                  "/api/v1/compare": ((), compare_request)}
        if path not in routes:
            self._error(404, "Q3-WEB-NOTFOUND", "Endpoint not found")
            return
        if self.headers.get("Transfer-Encoding") is not None:
            self._error(400, "Q3-WEB-TRANSFER", "Chunked request bodies are not accepted")
            return
        if self.headers.get("Content-Type", "").lower().split(";", 1)[0].strip() != "application/json":
            self._error(415, "Q3-WEB-TYPE", "Content-Type must be application/json")
            return
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1:
            self._error(411, "Q3-WEB-LENGTH", "A single Content-Length header is required")
            return
        if not lengths[0].isascii() or not lengths[0].isdecimal():
            self._error(400, "Q3-WEB-LENGTH", "Invalid Content-Length")
            return
        size = int(lengths[0])
        if size > MAX_REQUEST_BYTES:
            self._error(413, "Q3-WEB-BUDGET", "Request exceeds 16 KiB")
            return
        raw = self.rfile.read(size)
        if len(raw) != size:
            self._error(400, "Q3-WEB-LENGTH", "Incomplete request body")
            return
        fields, callback = routes[path]
        try:
            payload = _request_object(raw, fields)
            response = callback(payload)
            self._json(200, response)
        except (InputError, ValueError, TypeError) as exc:
            self._error(422, "Q3-WEB-INPUT", str(exc)[:384])
        except (OSError, RuntimeError, OverflowError) as exc:
            # Do not expose internal file paths/tracebacks or environment details.
            print(f"Q3HASH internal request error ({type(exc).__name__})", file=sys.stderr)
            self._error(500, "Q3-WEB-INTERNAL", "Local research operation failed")

    def do_HEAD(self):
        self.do_GET()

    def do_OPTIONS(self):
        self._error(405, "Q3-WEB-METHOD", "Method not supported")


def create_server(port=8765):
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Port must be an integer in 0..65535")
    server = ThreadingHTTPServer(("127.0.0.1", port), ResearchHandler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description="Q3HASH localhost-only v0.6 research console")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with create_server(args.port) as server:
        print(f"Q3HASH research console: http://127.0.0.1:{server.server_address[1]}/", flush=True)
        print("Local-only development. Synthetic hardware data is not measured performance.", flush=True)
        try:
            server.serve_forever(poll_interval=0.1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
