"""Immutable hardware inputs and strict v1 wire contracts; no cost assessment."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import math
import re
from urllib.parse import urlsplit

from . import _serialization as wire
from .ir import GateKind, MAX_DIMENSION


HARDWARE_OBJECTIVES = ("active_sites", "native_operations", "two_site_operations",
                       "critical_path_ps", "serial_duration_ps")
DEFAULT_HARDWARE_OBJECTIVES = HARDWARE_OBJECTIVES[:4]
_KINDS = (GateKind.SHIFT, GateKind.FOURIER, GateKind.SUM)
_METRICS = ("average-gate-infidelity", "process-infidelity", "reported-unspecified-error")
_PROVENANCE_FIELDS = ("kind", "provider", "device_id", "snapshot_id", "source_uri",
                      "retrieved_at", "calibrated_at", "notes")
_PROFILE_FIELDS = ("schema", "schema_version", "name", "site_dimensions", "couplings", "bindings", "provenance")
_CONTEXT_FIELDS = ("schema", "schema_version", "as_of", "max_calibration_age_seconds", "max_gate_checks", "objectives")


def _error(code, message, *, wrong_type=False):
    if wrong_type:
        code = "Q3-HARD-001"
    raise (TypeError if wrong_type else ValueError)(f"{code}: {message}")


def _type(value, expected, code, label):
    if type(value) is not expected:
        _error(code, f"{label} must be an exact {expected.__name__}", wrong_type=True)


def _text(value, limit, code, label, *, empty=False):
    _type(value, str, code, label)
    if not (0 if empty else 1) <= len(value) <= limit:
        _error(code, f"{label} exceeds its character bounds")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise ValueError(f"{code}: {label} must be valid UTF-8") from error


def _instant(value, code):
    _text(value, 20, code, "timestamp")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value):
        _error(code, "timestamp must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        result = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise ValueError(f"{code}: invalid calendar instant") from error
    if result.year < 1970:
        _error(code, "timestamp year must be in 1970..9999")
    return result


def _digest(value, code):
    _type(value, str, code, "digest")
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        _error(code, "digest must be 64 lowercase hexadecimal characters")


def _indices(value, code, label, *, length=None):
    _type(value, tuple, code, label)
    if (not value or len(value) > 64 or (length is not None and len(value) != length) or
            any(type(i) is not int or not 0 <= i < 64 for i in value) or len(set(value)) != len(value)):
        _error(code, f"{label} requires distinct integer site indices in 0..63")


def _wire_type(value, expected):
    if type(value) not in (expected if type(expected) is tuple else (expected,)):
        _error("Q3-SER-003", "incorrect wire field type")
    return value


def _object(value):
    return _wire_type(value, dict)


def _wire_tuple(value, element_type):
    return tuple(_wire_type(item, element_type) for item in wire.array(value))


class _WireModel:
    def to_json(self):
        return wire.write_json(self.to_dict())

    @classmethod
    def from_json(cls, text):
        return cls.from_dict(wire.read_json(text))


@dataclass(frozen=True)
class TimeRange(_WireModel):
    lower_ps: int
    upper_ps: int

    def __post_init__(self):
        for value in (self.lower_ps, self.upper_ps):
            _type(value, int, "Q3-HARD-002", "picosecond endpoint")
        if not 0 <= self.lower_ps <= self.upper_ps <= 16384 * 10**15:
            _error("Q3-HARD-002", "time range must be ordered within aggregate bounds")

    def to_dict(self):
        return {"lower_ps": self.lower_ps, "upper_ps": self.upper_ps}

    @classmethod
    def from_dict(cls, value):
        wire.fields(value, ("lower_ps", "upper_ps"), top=True)
        return cls(*(_wire_type(value[name], int) for name in ("lower_ps", "upper_ps")))


@dataclass(frozen=True)
class ErrorRange(_WireModel):
    metric: str
    lower: float
    upper: float

    def __post_init__(self):
        _type(self.metric, str, "Q3-HARD-002", "error metric")
        if self.metric not in _METRICS:
            _error("Q3-HARD-002", "unknown error metric")
        values = []
        for endpoint in (self.lower, self.upper):
            if type(endpoint) not in (int, float):
                _error("Q3-HARD-002", "error endpoints must be built-in numbers", wrong_type=True)
            try:
                number = float(endpoint)
            except (OverflowError, ValueError) as error:
                raise ValueError("Q3-HARD-002: unrepresentable error endpoint") from error
            if not math.isfinite(number) or not 0 <= number <= 1:
                _error("Q3-HARD-002", "error endpoints must be finite in 0..1")
            values.append(0.0 if number == 0 else number)
        if values[0] > values[1]:
            _error("Q3-HARD-002", "error range must be ordered")
        object.__setattr__(self, "lower", values[0])
        object.__setattr__(self, "upper", values[1])

    def to_dict(self):
        return {"metric": self.metric, "lower": self.lower, "upper": self.upper}

    @classmethod
    def from_dict(cls, value):
        wire.fields(value, ("metric", "lower", "upper"), top=True)
        return cls(_wire_type(value["metric"], str), _wire_type(value["lower"], (int, float)),
                   _wire_type(value["upper"], (int, float)))


@dataclass(frozen=True)
class ProfileProvenance(_WireModel):
    kind: str
    provider: str
    device_id: str
    snapshot_id: str
    source_uri: str
    retrieved_at: str
    calibrated_at: str | None
    notes: str

    def __post_init__(self):
        code = "Q3-HARD-002"
        for name in ("kind", "provider", "device_id", "snapshot_id"):
            _text(getattr(self, name), 128, code, name)
        if self.kind not in ("synthetic", "reported-device"):
            _error(code, "unknown provenance kind")
        _text(self.notes, 4096, code, "notes", empty=True)
        _text(self.source_uri, 2048, code, "source_uri")
        uri = self.source_uri
        if any(character.isspace() or ord(character) < 32 or ord(character) == 127 or character == "\\" for character in uri):
            _error(code, "source URI cannot contain whitespace or control characters")
        try:
            parsed = urlsplit(uri)
            port = parsed.port
            https = (parsed.scheme == "https" and bool(parsed.hostname) and parsed.username is None and
                     parsed.password is None and (port is None or 1 <= port <= 65535))
        except ValueError as error:
            raise ValueError(f"{code}: invalid source URI") from error
        prefix = "urn:q3hash:synthetic:"
        synthetic = self.kind == "synthetic" and uri.startswith(prefix) and len(uri) > len(prefix)
        if not (https or synthetic):
            _error(code, "source URI must be absolute HTTPS or a synthetic Q3# URN")
        retrieved = _instant(self.retrieved_at, code)
        if self.calibrated_at is not None:
            _type(self.calibrated_at, str, code, "calibrated_at")
        if self.kind == "synthetic":
            if self.calibrated_at is not None:
                _error(code, "synthetic provenance requires null calibration")
        elif self.calibrated_at is not None and _instant(self.calibrated_at, code) > retrieved:
            _error(code, "calibration cannot follow retrieval")

    def to_dict(self):
        return {name: getattr(self, name) for name in _PROVENANCE_FIELDS}

    @classmethod
    def from_dict(cls, value):
        wire.fields(value, _PROVENANCE_FIELDS, top=True)
        for name in _PROVENANCE_FIELDS:
            if name != "calibrated_at" or value[name] is not None:
                _wire_type(value[name], str)
        return cls(**value)


@dataclass(frozen=True)
class NativeBinding(_WireModel):
    kind: GateKind
    sites: tuple[int, ...]
    duration: TimeRange | None
    error: ErrorRange | None

    def __post_init__(self):
        code = "Q3-HARD-002"
        _type(self.kind, GateKind, code, "gate kind")
        _indices(self.sites, code, "binding sites", length=2 if self.kind is GateKind.SUM else 1)
        if self.duration is not None:
            _type(self.duration, TimeRange, code, "duration")
            if self.duration.upper_ps > 10**15:
                _error(code, "a native duration cannot exceed 10**15 picoseconds")
        if self.error is not None:
            _type(self.error, ErrorRange, code, "error")

    def to_dict(self):
        return {"kind": self.kind.value, "sites": list(self.sites),
                "duration": None if self.duration is None else self.duration.to_dict(),
                "error": None if self.error is None else self.error.to_dict()}

    @classmethod
    def from_dict(cls, value):
        wire.fields(value, ("kind", "sites", "duration", "error"), top=True)
        kind = _wire_type(value["kind"], str)
        if kind not in tuple(item.value for item in _KINDS):
            _error("Q3-HARD-002", "unknown native gate kind")
        return cls(GateKind(kind), _wire_tuple(value["sites"], int),
                   None if value["duration"] is None else TimeRange.from_dict(_object(value["duration"])),
                   None if value["error"] is None else ErrorRange.from_dict(_object(value["error"])))


@dataclass(frozen=True)
class HardwareProfile(_WireModel):
    name: str
    site_dimensions: tuple[int, ...]
    couplings: tuple[tuple[int, int], ...]
    bindings: tuple[NativeBinding, ...]
    provenance: ProfileProvenance

    def __post_init__(self):
        code = "Q3-HARD-002"
        _text(self.name, 128, code, "profile name")
        for name in ("site_dimensions", "couplings", "bindings"):
            _type(getattr(self, name), tuple, code, name)
        _type(self.provenance, ProfileProvenance, code, "provenance")
        dimensions = self.site_dimensions
        if not 1 <= len(dimensions) <= 64 or any(type(d) is not int or not 2 <= d <= MAX_DIMENSION for d in dimensions):
            _error(code, "profile requires 1..64 site dimensions in 2..32")
        if len(self.couplings) > 4032 or len(self.bindings) > 8192:
            _error(code, "profile exceeds edge or binding limits")
        for edge in self.couplings:
            _indices(edge, code, "coupling", length=2)
            if max(edge) >= len(dimensions):
                _error(code, "coupling site is outside the profile")
        if self.couplings != tuple(sorted(set(self.couplings))):
            _error(code, "couplings must be unique and lexicographically ordered")
        edges, keys = set(self.couplings), []
        for binding in self.bindings:
            _type(binding, NativeBinding, code, "binding")
            if max(binding.sites) >= len(dimensions):
                _error(code, "native binding site is outside the profile")
            if binding.kind is GateKind.SUM and binding.sites not in edges:
                _error(code, "SUM binding requires its directed coupling")
            keys.append((_KINDS.index(binding.kind), binding.sites))
        if keys != sorted(set(keys)):
            _error(code, "native bindings must be unique and canonically ordered")

    @property
    def profile_id(self):
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def to_dict(self):
        return {"schema": "q3hash.hardware-profile", "schema_version": 1, "name": self.name,
                "site_dimensions": list(self.site_dimensions), "couplings": [list(edge) for edge in self.couplings],
                "bindings": [binding.to_dict() for binding in self.bindings], "provenance": self.provenance.to_dict()}

    @classmethod
    def from_dict(cls, value):
        wire.header(value, "q3hash.hardware-profile", _PROFILE_FIELDS)
        dimensions, raw_edges, raw_bindings = (wire.array(value[key]) for key in ("site_dimensions", "couplings", "bindings"))
        if not 1 <= len(dimensions) <= 64 or len(raw_edges) > 4032 or len(raw_bindings) > 8192:
            _error("Q3-HARD-002", "profile array bounds exceeded")
        edges = tuple(_wire_tuple(edge, int) for edge in raw_edges)
        bindings = tuple(NativeBinding.from_dict(_object(item)) for item in raw_bindings)
        return cls(_wire_type(value["name"], str), _wire_tuple(value["site_dimensions"], int), edges,
                   bindings, ProfileProvenance.from_dict(_object(value["provenance"])))


@dataclass(frozen=True)
class HardwareContext(_WireModel):
    as_of: str
    max_calibration_age_seconds: int
    max_gate_checks: int = 262144
    objectives: tuple[str, ...] = DEFAULT_HARDWARE_OBJECTIVES

    def __post_init__(self):
        code = "Q3-HARD-001"
        _instant(self.as_of, code)
        for name in ("max_calibration_age_seconds", "max_gate_checks"):
            _type(getattr(self, name), int, code, name)
        _type(self.objectives, tuple, code, "objectives")
        if not 0 <= self.max_calibration_age_seconds <= 31536000 or not 1 <= self.max_gate_checks <= 4194304:
            _error(code, "context age or gate-check budget is out of range")
        if (not self.objectives or any(type(key) is not str or key not in HARDWARE_OBJECTIVES for key in self.objectives) or
                len(set(self.objectives)) != len(self.objectives)):
            _error(code, "objectives must be distinct supported names")

    def validate_profile(self, profile):
        """Validate relative instants without consulting the current clock."""
        _type(profile, HardwareProfile, "Q3-HARD-001", "profile")
        if _instant(self.as_of, "Q3-HARD-001") < _instant(profile.provenance.retrieved_at, "Q3-HARD-002"):
            _error("Q3-HARD-001", "as_of cannot precede profile retrieval or calibration")

    @property
    def context_id(self):
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def to_dict(self):
        return {"schema": "q3hash.hardware-context", "schema_version": 1, "as_of": self.as_of,
                "max_calibration_age_seconds": self.max_calibration_age_seconds,
                "max_gate_checks": self.max_gate_checks, "objectives": list(self.objectives)}

    @classmethod
    def from_dict(cls, value):
        wire.header(value, "q3hash.hardware-context", _CONTEXT_FIELDS)
        return cls(_wire_type(value["as_of"], str), _wire_type(value["max_calibration_age_seconds"], int),
                   _wire_type(value["max_gate_checks"], int), _wire_tuple(value["objectives"], str))


@dataclass(frozen=True)
class HardwarePlacement(_WireModel):
    candidate_id: str
    site_indices: tuple[int, ...]

    def __post_init__(self):
        _digest(self.candidate_id, "Q3-HARD-003")
        _indices(self.site_indices, "Q3-HARD-003", "placement sites")

    def validate_for(self, profile, physical_dimensions):
        """Check arity/index validity; dimension mismatch is a later outcome."""
        code = "Q3-HARD-003"
        _type(profile, HardwareProfile, code, "profile")
        _type(physical_dimensions, tuple, code, "physical dimensions")
        if (not physical_dimensions or len(physical_dimensions) > 64 or
                any(type(d) is not int or not 2 <= d <= MAX_DIMENSION for d in physical_dimensions)):
            _error(code, "invalid physical dimensions")
        if len(self.site_indices) != len(physical_dimensions) or max(self.site_indices) >= len(profile.site_dimensions):
            _error(code, "placement arity or profile site index disagrees")

    def identifier(self, profile_id, physical_id):
        """Content key only; does not establish source membership or verification."""
        for digest in (profile_id, physical_id):
            _digest(digest, "Q3-HARD-003")
        body = {"schema": "q3hash.hardware-placement-key", "schema_version": 1,
                "profile_id": profile_id, "candidate_id": self.candidate_id,
                "physical_id": physical_id, "site_indices": list(self.site_indices)}
        return hashlib.sha256(wire.write_json(body).encode("utf-8")).hexdigest()

    def to_dict(self):
        return {"candidate_id": self.candidate_id, "site_indices": list(self.site_indices)}

    @classmethod
    def from_dict(cls, value):
        wire.fields(value, ("candidate_id", "site_indices"), top=True)
        return cls(_wire_type(value["candidate_id"], str), _wire_tuple(value["site_indices"], int))
