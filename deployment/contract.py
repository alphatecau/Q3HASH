"""Hosted wire contract. The local v1 console and numerical core stay pinned."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re

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
OPERATIONS = {
    "simulate": ("simulation", ("source",), {"pass", "unsupported"}),
    "verify": ("verification", ("logical_source", "physical_source", "encoding"), {"pass", "fail", "unsupported"}),
    "compare": ("comparison", (), {"partial"}),
}
COMMIT = re.compile(r"[0-9a-f]{40}")
TOKEN = re.compile(r"[A-Za-z0-9._~-]{32,256}")


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
        fields = {name: value for name, value in payload.items()
                  if name not in {"schema", "schema_version", "kind", "status", "engine_version"}}
        if operation == "simulate":
            fields["basis_order"] = BASIS_ORDER
            if payload["status"] == "unsupported":
                # Preserve exact counts when they exceed JavaScript's safe integer range.
                fields["state_size"] = str(fields["state_size"])
        if operation == "verify" and payload["status"] == "unsupported":
            fields["verification"]["physical_size"] = str(fields["verification"]["physical_size"])
        return self.envelope(kind, payload["status"], **fields)


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
