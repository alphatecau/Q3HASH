"""Hosted wire contract. The local v1 console and numerical core stay pinned."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import importlib.util
import json
from math import hypot, prod
from pathlib import Path
import re
from sys import float_info

SCHEMA = "q3hash.web-response"
SCHEMA_VERSION = 2
WEB_VERSION = "0.6.0-rc.1"
ENGINE_VERSION = "0.5.0"
MAX_REQUEST_BYTES = 16_384
MAX_PROGRAM_CHARACTERS = 4_096
MAX_OPERATIONS = 64
MAX_SIMULATED_STATES = 64
MAX_VERIFIED_DIMENSION = 32
MAX_REGISTER_DIMENSION = 32
MAX_RESPONSE_BYTES = 262_144
BASIS_ORDER = "last-register-fastest"
VERIFICATION_TOLERANCE = 1e-10
STATE_TOLERANCE = 1e-8
OPERATIONS = {
    "simulate": ("simulation", ("source",), {"pass", "unsupported"}),
    "verify": ("verification", ("logical_source", "physical_source", "encoding"), {"pass", "fail", "unsupported"}),
    "compare": ("comparison", (), {"partial"}),
}
COMMIT = re.compile(r"[0-9a-f]{40}")
TOKEN = re.compile(r"[A-Za-z0-9._~-]{32,256}")
_METRICS = ("subspace_residual", "leakage_norm", "logical_unitarity_error", "physical_unitarity_error")
_BENCHMARK_STATUSES = {(3,): "pass", (2, 2): "pass", (2, 3): "pass", (3, 2): "unimplemented"}
_SOURCE_COUNTS = {"unimplemented": 1, "pass": 3, "fail": 0, "unsupported": 0, "not-evaluated": 0}
_HARDWARE_COUNTS = {"ineligible": 1, "supported": 3, "unsupported": 0, "unplaced": 0, "not-evaluated": 0}


def _finite(value):
    return type(value) in (int, float) and -float_info.max <= value <= float_info.max


def _pair(value):
    return type(value) is list and len(value) == 2 and all(_finite(part) for part in value)


def _dimensions(value):
    return type(value) is list and bool(value) and all(
        type(dimension) is int and 2 <= dimension <= MAX_REGISTER_DIMENSION for dimension in value)


def _matches_counts(value, expected):
    return type(value) is dict and value.keys() == expected.keys() and all(
        type(value[key]) is int and value[key] == count for key, count in expected.items())


def _simulation_status(payload):
    dimensions, size = payload["dimensions"], payload["state_size"]
    if not _dimensions(dimensions) or type(size) is not int or size != prod(dimensions):
        raise ValueError("Invalid state size")
    if size > MAX_SIMULATED_STATES:
        reason = payload["reason"]
        if {"basis", "operations"} & payload.keys() or type(reason) is not str or not reason:
            raise ValueError("Unsupported simulation carries results")
        return "unsupported"
    basis, operations = payload["basis"], payload["operations"]
    if (type(basis) is not list or len(basis) != size or
            type(operations) is not int or not 0 <= operations <= MAX_OPERATIONS):
        raise ValueError("Incomplete simulation evidence")
    total = 0.0
    for index, row in enumerate(basis):
        if (type(row) is not dict or type(row["index"]) is not int or row["index"] != index or
                not _pair(row["amplitude"]) or not _finite(row["probability"])):
            raise ValueError("Invalid basis row")
        probability = row["probability"]
        magnitude = hypot(*row["amplitude"])
        if (not 0 <= probability <= 1 + STATE_TOLERANCE or magnitude > 1 + STATE_TOLERANCE or
                abs(magnitude ** 2 - probability) > STATE_TOLERANCE):
            raise ValueError("Inconsistent basis probability")
        total += probability
    if abs(total - 1) >= STATE_TOLERANCE:
        raise ValueError("Simulation is not normalised")
    return "pass"


def _verification_status(value):
    logical, physical = value["logical_size"], value["physical_size"]
    if (type(logical) is not int or type(physical) is not int or not 2 <= logical <= physical or
            value["tolerance"] != VERIFICATION_TOLERANCE or value["evidence"] != "q3hash-circuit"):
        raise ValueError("Invalid verification dimensions or tolerance")
    phase = value["global_phase"]
    metrics = [value[name] for name in _METRICS]
    if physical > MAX_VERIFIED_DIMENSION:
        if phase is not None or any(metric is not None for metric in metrics):
            raise ValueError("Unsupported verification carries numerical evidence")
        return "unsupported"
    if (not _pair(phase) or abs(hypot(*phase) - 1) > STATE_TOLERANCE or
            not all(_finite(metric) and metric >= 0 for metric in metrics)):
        raise ValueError("Invalid verification metrics")
    return "pass" if all(metric <= VERIFICATION_TOLERANCE for metric in metrics) else "fail"


def _comparison_status(payload):
    rows = payload["rows"]
    if (type(rows) is not list or len(rows) != len(_BENCHMARK_STATUSES) or
            payload["front_partial"] is not True or payload["search_complete"] is not True or
            payload["synthetic"] is not True or payload["measured_hardware"] is not False or
            payload["hardware_provenance"] != "synthetic" or
            not _matches_counts(payload["source_status_counts"], _SOURCE_COUNTS) or
            not _matches_counts(payload["hardware_status_counts"], _HARDWARE_COUNTS)):
        raise ValueError("Invalid fixed benchmark coverage")
    seen = {}
    for row in rows:
        dimensions = row["dimensions"]
        if not _dimensions(dimensions) or tuple(dimensions) in seen:
            raise ValueError("Invalid or repeated benchmark dimensions")
        status = row["source_status"]
        seen[tuple(dimensions)] = status
        verification = row["verification"]
        if status == "pass":
            if (_verification_status(verification) != "pass" or verification["status"] != "pass" or
                    verification["logical_size"] != 3 or verification["physical_size"] != prod(dimensions) or
                    row["target_status"] != "supported"):
                raise ValueError("Benchmark row lacks passing verification")
        elif (status != "unimplemented" or row["target_status"] != "ineligible" or row["on_front"] is not False or
              any(row[field] is not None for field in ("verification", "resources", "active_sites", "operations",
                                                      "two_site_operations", "critical_path_ps"))):
            raise ValueError("Unevaluated benchmark row carries results")
    if seen != _BENCHMARK_STATUSES or type(payload["verification_calls"]) is not int or payload["verification_calls"] != 3:
        raise ValueError("Incorrect fixed benchmark coverage")
    return "partial"


@dataclass(frozen=True)
class Identity:
    source_commit: str
    deployment_commit: str

    def envelope(self, kind, status, **fields):
        return dict(schema=SCHEMA, schema_version=SCHEMA_VERSION, kind=kind,
                    status=status, engine_version=ENGINE_VERSION, web_version=WEB_VERSION,
                    source_commit=self.source_commit, deployment_commit=self.deployment_commit,
                    **fields)

    def capabilities(self, max_request_bytes):
        return self.envelope(
            "capabilities", "pass", endpoints=list(OPERATIONS),
            max_request_bytes=max_request_bytes, max_program_characters=MAX_PROGRAM_CHARACTERS,
            max_operations=MAX_OPERATIONS, max_simulated_states=MAX_SIMULATED_STATES,
            max_verified_dimension=MAX_VERIFIED_DIMENSION, max_register_dimension=MAX_REGISTER_DIMENSION,
            basis_order=BASIS_ORDER, local_only=False, public_browser_access=False,
            synthetic_hardware_only=True, automatic_synthesis=False, automatic_dimension_inference=False,
        )

    def result(self, operation, payload):
        kind, _, statuses = OPERATIONS[operation]
        if (type(payload) is not dict or payload.get("schema") != SCHEMA or
                type(payload.get("schema_version")) is not int or payload["schema_version"] != 1 or
                payload.get("kind") != kind or payload.get("status") not in statuses or
                payload.get("engine_version") != ENGINE_VERSION or
                {"source_commit", "deployment_commit", "web_version", "basis_order", "site_bridge"} & payload.keys()):
            raise ValueError("Unexpected local worker contract")
        if operation == "simulate":
            status = _simulation_status(payload)
        elif operation == "verify":
            verification = payload["verification"]
            status = _verification_status(verification)
            if verification["status"] != status:
                raise ValueError("Verification status contradicts its metrics")
        else:
            status = _comparison_status(payload)
        if payload["status"] != status:
            raise ValueError("Worker status contradicts its evidence")
        fields = {name: value for name, value in payload.items()
                  if name not in {"schema", "schema_version", "kind", "status", "engine_version"}}
        if operation == "simulate":
            fields["basis_order"] = BASIS_ORDER
            if status == "unsupported":
                # Preserve exact counts when they exceed JavaScript's safe integer range.
                fields["state_size"] = str(fields["state_size"])
        if operation == "verify" and status == "unsupported":
            fields["verification"] = {**verification, "physical_size": str(verification["physical_size"])}
        return self.envelope(kind, status, **fields)


def verify_engine_source(root: Path, deployment_commit: str) -> Identity:
    """Verify the actual installed module files and the source-side workload."""
    if not COMMIT.fullmatch(deployment_commit):
        raise ValueError("A full deployment commit SHA is required")
    manifest = json.loads((root / "deployment/engine-source.json").read_text(encoding="utf-8"))
    if manifest["engine_version"] != ENGINE_VERSION or not COMMIT.fullmatch(manifest["source_commit"]):
        raise ValueError("Invalid engine source manifest")
    spec = importlib.util.find_spec("q3hash")
    if spec is None or spec.origin is None:
        raise ValueError("Install the Q3HASH core before starting the API")
    package_root = Path(spec.origin).resolve().parent
    source_prefix = "src/q3hash/"
    expected_modules = {name[len(source_prefix):] for name in manifest["sha256"]
                        if name.startswith(source_prefix)}
    installed_modules = {p.relative_to(package_root).as_posix() for p in package_root.rglob("*.py")}
    if not expected_modules or installed_modules != expected_modules:
        raise ValueError("Installed engine modules do not match the manifest")
    for name, digest in manifest["sha256"].items():
        file = (package_root / name[len(source_prefix):]
                if name.startswith(source_prefix) else root / name)
        if sha256(file.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Engine source digest mismatch: {name}")
    return Identity(manifest["source_commit"], deployment_commit)
