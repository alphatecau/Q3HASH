"""Bounded, deterministic basis-encoding generation; no circuit synthesis or verification."""

from dataclasses import dataclass, field, fields as dataclass_fields
import hashlib
from itertools import combinations, product
import math
from typing import Optional

from . import _serialization as wire
from .encoding import BasisEncoding
from .ir import MAX_DIMENSION


_FAMILIES = ("flat-prefix", "register-prefix")
_OBJECTIVES = ("physical_registers", "max_register_dimension", "unused_basis_states",
               "gate_count", "two_register_gate_count", "dependency_depth")
_LIMITS = {
    "max_registers": (1, 8), "max_physical_size": (2, 64),
    "max_dimension_tuples": (1, 65_536), "max_mapping_attempts": (1, 262_144),
    "max_candidates": (1, 4096), "max_verifications": (1, 256),
    "max_operations_per_program": (1, 16_384), "max_gate_column_steps": (1, 4_194_304),
}
_CONSTRAINT_SCHEMA = "q3hash.encoding-search-constraints"
_GENERATION_SCHEMA = "q3hash.encoding-generation"
_CANDIDATE_FIELDS = ("candidate_id", "encoding", "origin", "seed_index", "block_cuts")
_STOP_REASONS = ("dimension-budget", "mapping-budget", "candidate-budget")


def _error(code, message, *, type_error=False):
    raise (TypeError if type_error else ValueError)(f"{code}: {message}")


def _object(value):
    if type(value) is not dict:
        _error("Q3-SER-003", "expected a nested JSON object")
    return value


def _array(value, element_type):
    values = wire.array(value)
    if any(type(item) is not element_type for item in values):
        _error("Q3-SER-003", "incorrect array element type")
    return tuple(values)


def _dimensions(values):
    if not values or any(type(d) is not int or not 2 <= d <= MAX_DIMENSION for d in values):
        _error("Q3-ENC-001", "logical dimensions must be nonempty exact integers in 2..32")


@dataclass(frozen=True)
class SearchConstraints:
    allowed_dimensions: tuple[int, ...] = (2, 3)
    max_registers: int = 4
    max_physical_size: int = 64
    mapping_families: tuple[str, ...] = _FAMILIES
    max_dimension_tuples: int = 4096
    max_mapping_attempts: int = 16384
    max_candidates: int = 256
    max_verifications: int = 64
    max_operations_per_program: int = 1024
    max_gate_column_steps: int = 262144
    objectives: tuple[str, ...] = _OBJECTIVES

    def __post_init__(self):
        # Check all public top-level types before semantic values.
        for name in ("allowed_dimensions", "mapping_families", "objectives"):
            if type(getattr(self, name)) is not tuple:
                _error("Q3-SEARCH-001", f"{name} must be an exact tuple", type_error=True)
        for name in _LIMITS:
            if type(getattr(self, name)) is not int:
                _error("Q3-SEARCH-001", f"{name} must be an exact integer", type_error=True)
        alphabet = self.allowed_dimensions
        if (not alphabet or len(alphabet) > MAX_DIMENSION - 1 or
                any(type(d) is not int or not 2 <= d <= MAX_DIMENSION for d in alphabet) or
                any(a >= b for a, b in zip(alphabet, alphabet[1:]))):
            _error("Q3-SEARCH-001", "allowed dimensions must be strictly increasing integers in 2..32")
        for name, (low, high) in _LIMITS.items():
            if not low <= getattr(self, name) <= high:
                _error("Q3-SEARCH-001", f"{name} must be in {low}..{high}")
        families = self.mapping_families
        if (not families or any(type(name) is not str or name not in _FAMILIES for name in families) or
                families != tuple(name for name in _FAMILIES if name in families)):
            _error("Q3-SEARCH-001", "mapping families must be a unique, canonically ordered subset")
        objectives = self.objectives
        if (not objectives or any(type(name) is not str or name not in _OBJECTIVES for name in objectives) or
                len(set(objectives)) != len(objectives)):
            _error("Q3-SEARCH-001", "objectives must be distinct known names")

    def to_dict(self):
        value = {"schema": _CONSTRAINT_SCHEMA, "schema_version": 1}
        for item in dataclass_fields(self):
            value[item.name] = list(getattr(self, item.name)) if item.name in (
                "allowed_dimensions", "mapping_families", "objectives") else getattr(self, item.name)
        return value

    def to_json(self):
        return wire.write_json(self.to_dict())

    @classmethod
    def from_dict(cls, value):
        names = tuple(item.name for item in dataclass_fields(cls))
        wire.header(value, _CONSTRAINT_SCHEMA, ("schema", "schema_version", *names))
        values = {}
        for name in names:
            if name in ("allowed_dimensions", "mapping_families", "objectives"):
                values[name] = _array(value[name], int if name == "allowed_dimensions" else str)
            elif type(value[name]) is not int:
                _error("Q3-SER-003", f"{name} must be a JSON integer")
            else:
                values[name] = value[name]
        return cls(**values)

    @classmethod
    def from_json(cls, text):
        return cls.from_dict(wire.read_json(text))


def _encoding_id(encoding):
    return hashlib.sha256(encoding.to_json().encode("utf-8")).hexdigest()


def _block_capacities(physical, cuts):
    boundaries = (0, *cuts, len(physical))
    return tuple(math.prod(physical[start:end])
                 for start, end in zip(boundaries, boundaries[1:]))


def _register_map(logical, capacities):
    """Build images from flat logical indices, independently of tensor-label oracles."""
    logical_strides = tuple(math.prod(logical[i + 1:]) for i in range(len(logical)))
    physical_strides = tuple(math.prod(capacities[i + 1:]) for i in range(len(capacities)))
    return tuple(sum((index // stride % dimension) * physical_stride
                     for dimension, stride, physical_stride in
                     zip(logical, logical_strides, physical_strides))
                 for index in range(math.prod(logical)))


@dataclass(frozen=True)
class EncodingCandidate:
    encoding: BasisEncoding
    origin: str
    seed_index: Optional[int] = None
    block_cuts: Optional[tuple[int, ...]] = None
    candidate_id: str = field(init=False)

    def __post_init__(self):
        code = "Q3-SEARCH-005"
        if (not isinstance(self.encoding, BasisEncoding) or type(self.origin) is not str or
                (self.seed_index is not None and type(self.seed_index) is not int) or
                (self.block_cuts is not None and type(self.block_cuts) is not tuple)):
            _error(code, "incorrect candidate field types", type_error=True)
        encoding = self.encoding
        if encoding.physical_size > 64 or len(encoding.physical_dimensions) > 8:
            _error(code, "candidate exceeds the first search version's physical bounds")
        if self.origin == "seed":
            if self.seed_index is None or not 0 <= self.seed_index < 4096 or self.block_cuts is not None:
                _error(code, "seed provenance requires an in-range index and null cuts")
        elif self.origin == "flat-prefix":
            if (self.seed_index is not None or self.block_cuts is not None or
                    encoding.physical_basis_indices != tuple(range(encoding.logical_size))):
                _error(code, "flat-prefix provenance or map disagrees")
        elif self.origin == "register-prefix":
            cuts = self.block_cuts
            if (self.seed_index is not None or cuts is None or
                    len(cuts) != len(encoding.logical_dimensions) - 1 or
                    any(type(cut) is not int or not 1 <= cut < len(encoding.physical_dimensions)
                        for cut in cuts) or any(a >= b for a, b in zip(cuts, cuts[1:]))):
                _error(code, "invalid register partition provenance")
            capacities = _block_capacities(encoding.physical_dimensions, cuts)
            if (any(d > capacity for d, capacity in zip(encoding.logical_dimensions, capacities)) or
                    encoding.physical_basis_indices != _register_map(encoding.logical_dimensions, capacities)):
                _error(code, "register-prefix map or block capacity disagrees")
        else:
            _error(code, "unknown candidate origin")
        object.__setattr__(self, "candidate_id", _encoding_id(encoding))

    def to_dict(self):
        return {"candidate_id": self.candidate_id, "encoding": self.encoding.to_dict(),
                "origin": self.origin, "seed_index": self.seed_index,
                "block_cuts": None if self.block_cuts is None else list(self.block_cuts)}

    @classmethod
    def from_dict(cls, value):
        wire.fields(value, _CANDIDATE_FIELDS, top=True)
        if (type(value["candidate_id"]) is not str or type(value["origin"]) is not str or
                (value["seed_index"] is not None and type(value["seed_index"]) is not int)):
            _error("Q3-SER-003", "incorrect candidate field types")
        cuts = None if value["block_cuts"] is None else _array(value["block_cuts"], int)
        result = cls(BasisEncoding.from_dict(_object(value["encoding"])),
                     value["origin"], value["seed_index"], cuts)
        if value["candidate_id"] != result.candidate_id:
            _error("Q3-SEARCH-005", "candidate ID does not match its canonical encoding")
        return result


@dataclass(frozen=True)
class DimensionRejections:
    insufficient_capacity: int = 0
    physical_size_limit: int = 0

    def __post_init__(self):
        counts = (self.insufficient_capacity, self.physical_size_limit)
        if any(type(count) is not int for count in counts):
            _error("Q3-SEARCH-005", "rejection counts must be exact integers", type_error=True)
        if any(count < 0 for count in counts):
            _error("Q3-SEARCH-005", "rejection counts must be nonnegative")

    def to_dict(self):
        return {"insufficient-capacity": self.insufficient_capacity,
                "physical-size-limit": self.physical_size_limit}

    @classmethod
    def from_dict(cls, value):
        wire.fields(value, ("insufficient-capacity", "physical-size-limit"), top=True)
        if any(type(count) is not int for count in value.values()):
            _error("Q3-SER-003", "rejection counts must be JSON integers")
        return cls(value["insufficient-capacity"], value["physical-size-limit"])


def _validate_inputs(logical_dimensions, constraints, seed_encodings):
    if (type(logical_dimensions) is not tuple or not isinstance(constraints, SearchConstraints) or
            type(seed_encodings) is not tuple):
        _error("Q3-SEARCH-001", "expected dimensions tuple, SearchConstraints and seed tuple", type_error=True)
    _dimensions(logical_dimensions)
    if len(seed_encodings) > 4096:
        _error("Q3-SEARCH-002", "at most 4096 seed encodings are supported")
    for seed in seed_encodings:
        if not isinstance(seed, BasisEncoding):
            _error("Q3-SEARCH-002", "seed entries must be BasisEncoding instances")
        if (seed.logical_dimensions != logical_dimensions or
                len(seed.physical_dimensions) > constraints.max_registers or
                seed.physical_size > constraints.max_physical_size or
                any(d not in constraints.allowed_dimensions for d in seed.physical_dimensions)):
            _error("Q3-SEARCH-002", "seed dimensions disagree with the logical/physical search constraints")


def _generate(logical, constraints, seeds):
    """Return trusted, immutable report fields from already validated inputs."""
    candidates, encodings, identities = [], set(), {}
    dimension_count = mapping_count = duplicates = insufficient = oversized = partitions = unavailable = 0
    logical_size = math.prod(logical)

    def finish(reason=None):
        return {"candidates": tuple(candidates), "completion": "truncated" if reason else "exhausted",
                "stop_reason": reason, "dimension_tuples_seen": dimension_count,
                "mapping_attempts": mapping_count, "emitted_candidates": len(candidates),
                "duplicate_mappings": duplicates,
                "dimension_rejections": DimensionRejections(insufficient, oversized),
                "partition_rejections": partitions, "family_unavailable": unavailable}

    def retain(candidate):
        nonlocal duplicates
        identifier, encoding = candidate.candidate_id, candidate.encoding
        if identifier in identities and identities[identifier] != encoding:
            _error("Q3-SEARCH-004", "candidate digest collision with unequal encoding content")
        if encoding in encodings:
            duplicates += 1
        elif len(candidates) == constraints.max_candidates:
            return False
        else:
            identities[identifier] = encoding
            encodings.add(encoding)
            candidates.append(candidate)
        return True

    for index, seed in enumerate(seeds):
        if mapping_count == constraints.max_mapping_attempts:
            return finish("mapping-budget")
        mapping_count += 1
        if not retain(EncodingCandidate(seed, "seed", seed_index=index)):
            return finish("candidate-budget")

    for register_count in range(1, constraints.max_registers + 1):
        for physical in product(constraints.allowed_dimensions, repeat=register_count):
            if dimension_count == constraints.max_dimension_tuples:
                return finish("dimension-budget")
            dimension_count += 1
            physical_size = math.prod(physical)
            if physical_size > constraints.max_physical_size:
                oversized += 1
                continue
            if physical_size < logical_size:
                insufficient += 1
                continue
            for family in constraints.mapping_families:
                if family == "register-prefix" and register_count < len(logical):
                    unavailable += 1
                    continue
                patterns = (None,) if family == "flat-prefix" else combinations(
                    range(1, register_count), len(logical) - 1)
                for cuts in patterns:
                    if mapping_count == constraints.max_mapping_attempts:
                        return finish("mapping-budget")
                    mapping_count += 1
                    if cuts is None:
                        mapping = tuple(range(logical_size))
                    else:
                        capacities = _block_capacities(physical, cuts)
                        if any(d > capacity for d, capacity in zip(logical, capacities)):
                            partitions += 1
                            continue
                        mapping = _register_map(logical, capacities)
                    encoding = BasisEncoding(logical, physical, mapping)
                    if not retain(EncodingCandidate(encoding, family, block_cuts=cuts)):
                        return finish("candidate-budget")
    return finish()


@dataclass(frozen=True)
class GenerationReport:
    constraints: SearchConstraints
    logical_dimensions: tuple[int, ...]
    seed_encodings: tuple[BasisEncoding, ...]
    candidates: tuple[EncodingCandidate, ...]
    completion: str
    stop_reason: Optional[str]
    dimension_tuples_seen: int
    mapping_attempts: int
    emitted_candidates: int
    duplicate_mappings: int
    dimension_rejections: DimensionRejections
    partition_rejections: int
    family_unavailable: int

    def __post_init__(self):
        # Public report construction/decoding must not accept invented evidence.
        code = "Q3-SEARCH-005"
        counters = ("dimension_tuples_seen", "mapping_attempts", "emitted_candidates",
                    "duplicate_mappings", "partition_rejections", "family_unavailable")
        if (not isinstance(self.constraints, SearchConstraints) or
                any(type(getattr(self, name)) is not tuple for name in
                    ("logical_dimensions", "seed_encodings", "candidates")) or
                type(self.completion) is not str or
                (self.stop_reason is not None and type(self.stop_reason) is not str) or
                not isinstance(self.dimension_rejections, DimensionRejections) or
                any(type(getattr(self, name)) is not int for name in counters)):
            _error(code, "incorrect report field types", type_error=True)
        if any(getattr(self, name) < 0 for name in counters):
            _error(code, "report counters must be nonnegative")
        _validate_inputs(self.logical_dimensions, self.constraints, self.seed_encodings)
        if (len(self.candidates) > self.constraints.max_candidates or
                any(not isinstance(candidate, EncodingCandidate) for candidate in self.candidates) or
                self.emitted_candidates != len(self.candidates) or
                self.dimension_tuples_seen > self.constraints.max_dimension_tuples or
                self.mapping_attempts > self.constraints.max_mapping_attempts or
                self.completion not in ("exhausted", "truncated") or
                (self.completion == "exhausted" and self.stop_reason is not None) or
                (self.completion == "truncated" and self.stop_reason not in _STOP_REASONS)):
            _error(code, "invalid report counts or completion")
        if (self.mapping_attempts != self.emitted_candidates + self.duplicate_mappings +
                self.partition_rejections + (self.stop_reason == "candidate-budget") or
                self.dimension_rejections.insufficient_capacity +
                self.dimension_rejections.physical_size_limit > self.dimension_tuples_seen):
            _error(code, "report counters do not conserve assessed work")
        expected = _generate(self.logical_dimensions, self.constraints, self.seed_encodings)
        if any(getattr(self, name) != value for name, value in expected.items()):
            _error(code, "report does not match replay of the declared bounded domain")

    @classmethod
    def _generated(cls, logical_dimensions, constraints, seeds, result):
        # Only generate_encodings calls this private constructor, after validation.
        # Its fields were just produced by _generate: avoid performing the search twice.
        report = object.__new__(cls)
        values = dict(constraints=constraints, logical_dimensions=logical_dimensions,
                      seed_encodings=seeds, **result)
        for item in dataclass_fields(cls):
            object.__setattr__(report, item.name, values[item.name])
        return report

    def to_dict(self):
        return {"schema": _GENERATION_SCHEMA, "schema_version": 1,
                "constraints": self.constraints.to_dict(), "logical_dimensions": list(self.logical_dimensions),
                "seed_encodings": [encoding.to_dict() for encoding in self.seed_encodings],
                "candidates": [candidate.to_dict() for candidate in self.candidates],
                "completion": self.completion, "stop_reason": self.stop_reason,
                "dimension_tuples_seen": self.dimension_tuples_seen, "mapping_attempts": self.mapping_attempts,
                "emitted_candidates": self.emitted_candidates, "duplicate_mappings": self.duplicate_mappings,
                "dimension_rejections": self.dimension_rejections.to_dict(),
                "partition_rejections": self.partition_rejections, "family_unavailable": self.family_unavailable}

    def to_json(self):
        return wire.write_json(self.to_dict())

    @classmethod
    def from_dict(cls, value):
        names = tuple(item.name for item in dataclass_fields(cls))
        wire.header(value, _GENERATION_SCHEMA, ("schema", "schema_version", *names))
        constraints = SearchConstraints.from_dict(_object(value["constraints"]))
        logical = _array(value["logical_dimensions"], int)
        seed_values, candidate_values = wire.array(value["seed_encodings"]), wire.array(value["candidates"])
        if len(seed_values) > 4096:
            _error("Q3-SEARCH-002", "at most 4096 seed encodings are supported")
        if len(candidate_values) > constraints.max_candidates:
            _error("Q3-SEARCH-005", "candidate array exceeds the declared cap")
        seeds = tuple(BasisEncoding.from_dict(_object(item)) for item in seed_values)
        candidates = tuple(EncodingCandidate.from_dict(_object(item)) for item in candidate_values)
        rejections = DimensionRejections.from_dict(_object(value["dimension_rejections"]))
        counters = ("dimension_tuples_seen", "mapping_attempts", "emitted_candidates",
                    "duplicate_mappings", "partition_rejections", "family_unavailable")
        if (any(type(value[name]) is not int for name in counters) or type(value["completion"]) is not str or
                (value["stop_reason"] is not None and type(value["stop_reason"]) is not str)):
            _error("Q3-SER-003", "incorrect report scalar field types")
        return cls(constraints=constraints, logical_dimensions=logical, seed_encodings=seeds,
                   candidates=candidates, completion=value["completion"], stop_reason=value["stop_reason"],
                   dimension_rejections=rejections, **{name: value[name] for name in counters})

    @classmethod
    def from_json(cls, text):
        return cls.from_dict(wire.read_json(text))


def generate_encodings(logical_dimensions, constraints, *, seed_encodings=()):
    """Generate maps within declared families/budgets; never synthesise or verify circuits."""
    _validate_inputs(logical_dimensions, constraints, seed_encodings)
    return GenerationReport._generated(logical_dimensions, constraints, seed_encodings,
                                       _generate(logical_dimensions, constraints, seed_encodings))
