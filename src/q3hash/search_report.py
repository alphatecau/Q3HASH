"""Strict aggregate snapshots and pure preflight/budget planning; no numerics."""

from dataclasses import dataclass, field
import hashlib
import math
import platform
import re
from typing import Optional

from . import _serialization as wire
from ._version import __version__, VERIFIER_VERSION
from .comparison import pareto_front
from .evaluation import CandidateEvaluation, CircuitImplementation, _checked_options, _METRICS
from .logical_ir import LogicalProgram
from .resources import RESOURCE_OBJECTIVES, ResourceCounts
from .search import GenerationReport
from .verification import VerificationReport


SCHEMA = "q3hash.encoding-search-report"
RANKING_SCOPE = "passing-supplied-circuits-only"
_FIELDS = ("schema", "schema_version", "logical_program", "logical_id", "generation",
           "implementations", "tolerance", "max_dimension", "evaluations", "front_ids",
           "ranking_scope", "verification_calls", "gate_column_steps", "engine_version",
           "verifier_version", "source_commit", "numerical_environment")
_ENV_FIELDS = ("python_implementation", "python_version", "system", "machine", "libc", "numeric_backend")
_STATUSES = ("unimplemented", "pass", "fail", "unsupported", "not-evaluated")


def _invalid(detail):
    raise ValueError(f"Q3-SEARCH-005: {detail}")


def _text(value):
    if type(value) is not str or not value:
        _invalid("metadata must contain nonempty strings")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("Q3-SER-001: invalid metadata Unicode") from error
    return value


def _number(value):
    if type(value) not in (int, float):
        _invalid("numerical evidence requires finite built-in numbers")
    try:
        result = float(value)
    except OverflowError:
        _invalid("unrepresentable numerical evidence")
    if not math.isfinite(result):
        _invalid("nonfinite numerical evidence")
    return result


def _program_id(program):
    return hashlib.sha256(program.to_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NumericalEnvironment:
    python_implementation: str
    python_version: str
    system: str
    machine: str
    libc: Optional[str]
    numeric_backend: str

    def __post_init__(self):
        for name in _ENV_FIELDS:
            value = getattr(self, name)
            if name != "libc" or value is not None:
                _text(value)

    @classmethod
    def capture(cls):
        libc = " ".join(part for part in platform.libc_ver() if part) or None
        return cls(platform.python_implementation() or "unknown", platform.python_version() or "unknown",
                   platform.system() or "unknown", platform.machine() or "unknown", libc,
                   "python-complex-cmath")

    def to_dict(self):
        return {name: getattr(self, name) for name in _ENV_FIELDS}

    @classmethod
    def from_dict(cls, value):
        wire.fields(value, _ENV_FIELDS)
        return cls(**value)


@dataclass(frozen=True)
class _Inputs:
    logical: LogicalProgram
    generation: GenerationReport
    implementations: tuple
    tolerance: float
    max_dimension: int
    logical_id: str
    physical_ids: tuple


def _prepare(logical, generation, implementations, tolerance, max_dimension):
    """Validate every binding, option and program ID before any numerical work."""
    if (not isinstance(logical, LogicalProgram) or not isinstance(generation, GenerationReport) or
            type(implementations) is not tuple):
        raise TypeError("Q3-SEARCH-001: expected logical program, generation and implementation tuple")
    if len(implementations) > 4096:
        raise ValueError("Q3-SEARCH-003: at most 4096 implementations are accepted")
    if logical.dimensions != generation.logical_dimensions:
        raise ValueError("Q3-SEARCH-003: logical program and generation dimensions disagree")
    tolerance = _checked_options(tolerance, max_dimension, generation.constraints.max_operations_per_program)
    members = {candidate.encoding: candidate for candidate in generation.candidates}
    bindings = {}
    for implementation in implementations:
        if not isinstance(implementation, CircuitImplementation):
            raise TypeError("Q3-SEARCH-001: implementations must contain CircuitImplementation values")
        if implementation.encoding not in members:
            raise ValueError("Q3-SEARCH-003: implementation is not a retained candidate")
        if implementation.encoding in bindings:
            raise ValueError("Q3-SEARCH-003: duplicate implementation for one candidate")
        bindings[implementation.encoding] = implementation
    ordered = tuple(bindings[candidate.encoding] for candidate in generation.candidates
                    if candidate.encoding in bindings)
    logical_id = _program_id(logical)
    # Shared physical circuits need only one canonical serialisation during preflight.
    identifiers = {}
    physical_ids = []
    for implementation in ordered:
        circuit = implementation.circuit
        if circuit not in identifiers:
            identifiers[circuit] = _program_id(LogicalProgram(circuit))
        physical_ids.append(identifiers[circuit])
    return _Inputs(logical, generation, ordered, tolerance, max_dimension, logical_id, tuple(physical_ids))


@dataclass(frozen=True)
class _Plan:
    rows: tuple
    verification_calls: int
    gate_column_steps: int


def _plan(inputs):
    bindings = {value.encoding: value for value in inputs.implementations}
    constraints = inputs.generation.constraints
    logical = inputs.logical
    calls = steps = 0
    rows = []
    for candidate in inputs.generation.candidates:
        implementation = bindings.get(candidate.encoding)
        reason = None
        if implementation is None:
            reason = "no-implementation"
        elif (len(logical.ir.operations) > constraints.max_operations_per_program or
              len(implementation.circuit.operations) > constraints.max_operations_per_program):
            reason = "operation-limit"
        elif candidate.encoding.physical_size > inputs.max_dimension:
            reason = "dense-limit"
        elif calls >= constraints.max_verifications:
            reason = "verification-call-budget"
        else:
            cost = (logical.state_size * len(logical.ir.operations) +
                    implementation.circuit.state_size * len(implementation.circuit.operations))
            if steps + cost > constraints.max_gate_column_steps:
                reason = "gate-column-budget"
            else:
                calls += 1
                steps += cost
        rows.append((candidate, implementation, reason))
    return _Plan(tuple(rows), calls, steps)


def _decode_evaluation(value, inputs, row):
    wire.fields(value, ("candidate_id", "status", "reason_code", "verification", "resources"))
    candidate, implementation, reason = row
    if (type(value["candidate_id"]) is not str or value["candidate_id"] != candidate.candidate_id or
            type(value["status"]) is not str or type(value["reason_code"]) is not str):
        _invalid("evaluation identity, order or field types disagree")
    options = (inputs.logical, candidate, implementation, inputs.tolerance, inputs.max_dimension,
               inputs.generation.constraints.max_operations_per_program)
    if reason is not None:
        if value["verification"] is not None or value["resources"] is not None:
            _invalid("a skipped or unsupported row cannot contain numerical evidence or resources")
        result = CandidateEvaluation._computed(*options, reason_code=reason)
    else:
        snapshot = value["verification"]
        wire.fields(snapshot, ("status", "evidence", "reason", "tolerance", "global_phase", *_METRICS))
        phase = snapshot["global_phase"]
        if phase is not None:
            phase = wire.array(phase)
            if len(phase) != 2:
                _invalid("phase must be a real/imaginary pair")
            phase = complex(_number(phase[0]), _number(phase[1]))
        tolerance = _number(snapshot["tolerance"])
        metrics = {name: None if snapshot[name] is None else _number(snapshot[name]) for name in _METRICS}
        verification = VerificationReport(
            status=snapshot["status"], evidence=snapshot["evidence"], reason=_text(snapshot["reason"]),
            logical_size=inputs.logical.state_size, physical_size=candidate.encoding.physical_size,
            tolerance=tolerance, global_phase=phase, **metrics)
        result = CandidateEvaluation._computed(*options, verification=verification)
        if result.resources is not None:
            wire.fields(value["resources"], RESOURCE_OBJECTIVES)
            if ResourceCounts(**value["resources"]) != result.resources:
                _invalid("resource counts disagree with the stored physical circuit")
        elif value["resources"] is not None:
            _invalid("failed evidence cannot carry resource counts")
    if (value["status"], value["reason_code"]) != (result.status, result.reason_code):
        _invalid("evaluation status or reason disagrees with evidence and budget plan")
    return result


@dataclass(frozen=True, init=False)
class SearchReport:
    logical: LogicalProgram
    logical_id: str
    generation: GenerationReport
    implementations: tuple
    tolerance: float
    max_dimension: int
    evaluations: tuple
    front_ids: tuple
    ranking_scope: str
    verification_calls: int
    gate_column_steps: int
    engine_version: str
    verifier_version: str
    source_commit: Optional[str]
    numerical_environment: NumericalEnvironment
    evidence_origin: str = field(compare=False)
    _physical_ids: tuple = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("Q3-SEARCH-005: use evaluate_candidates or strict report decoding")

    @property
    def status_counts(self):
        return {status: sum(value.status == status for value in self.evaluations) for status in _STATUSES}

    @property
    def front_reason(self):
        if not self.generation.candidates:
            return "no-candidates"
        return RANKING_SCOPE if self.front_ids else "no-passing-supplied-circuits"

    @property
    def front_is_partial(self):
        return (self.generation.completion == "truncated" or
                any(value.status in ("unimplemented", "unsupported", "not-evaluated")
                    for value in self.evaluations))

    @classmethod
    def _make(cls, inputs, evaluations, *, engine_version, verifier_version, source_commit,
              numerical_environment, evidence_origin):
        _text(engine_version)
        _text(verifier_version)
        if source_commit is not None and (type(source_commit) is not str or
                                         re.fullmatch("[0-9a-f]{40}", source_commit) is None):
            _invalid("source commit must be null or 40 lowercase hexadecimal characters")
        if type(numerical_environment) is not NumericalEnvironment:
            _invalid("invalid numerical environment")
        plan = _plan(inputs)
        if type(evaluations) is not tuple or len(evaluations) != len(plan.rows):
            _invalid("one evaluation is required for every candidate")
        for value, (candidate, implementation, reason) in zip(evaluations, plan.rows):
            if (type(value) is not CandidateEvaluation or value.logical != inputs.logical or
                    value.candidate != candidate or value.implementation != implementation or
                    (value.tolerance, value.max_dimension, value.max_operations_per_program) !=
                    (inputs.tolerance, inputs.max_dimension, inputs.generation.constraints.max_operations_per_program) or
                    (reason is None) != (value.verification is not None) or
                    (reason is not None and value.reason_code != reason)):
                _invalid("evaluations disagree with their complete input and budget plan")
        if (sum(value.verification_calls for value in evaluations) != plan.verification_calls or
                sum(value.gate_column_steps for value in evaluations) != plan.gate_column_steps):
            _invalid("evaluation ledger is inconsistent")
        front = pareto_front(evaluations, inputs.generation.constraints.objectives)
        value = object.__new__(cls)
        values = dict(logical=inputs.logical, logical_id=inputs.logical_id, generation=inputs.generation,
                      implementations=inputs.implementations, tolerance=inputs.tolerance,
                      max_dimension=inputs.max_dimension, evaluations=evaluations, front_ids=front,
                      ranking_scope=RANKING_SCOPE, verification_calls=plan.verification_calls,
                      gate_column_steps=plan.gate_column_steps, engine_version=engine_version,
                      verifier_version=verifier_version, source_commit=source_commit,
                      numerical_environment=numerical_environment, evidence_origin=evidence_origin,
                      _physical_ids=inputs.physical_ids)
        for name, item in values.items():
            object.__setattr__(value, name, item)
        return value

    @classmethod
    def _computed(cls, inputs, evaluations):
        return cls._make(inputs, evaluations, engine_version=__version__, verifier_version=VERIFIER_VERSION,
                         source_commit=None, numerical_environment=NumericalEnvironment.capture(),
                         evidence_origin="computed")

    def to_dict(self):
        candidate_ids = {candidate.encoding: candidate.candidate_id for candidate in self.generation.candidates}
        return {"schema": SCHEMA, "schema_version": 1, "logical_program": self.logical.to_dict(),
                "logical_id": self.logical_id, "generation": self.generation.to_dict(),
                "implementations": [{"candidate_id": candidate_ids[value.encoding],
                                     "physical_program": LogicalProgram(value.circuit).to_dict(),
                                     "physical_id": identifier}
                                    for value, identifier in zip(self.implementations, self._physical_ids)],
                "tolerance": self.tolerance, "max_dimension": self.max_dimension,
                "evaluations": [value.to_dict() for value in self.evaluations], "front_ids": list(self.front_ids),
                "ranking_scope": self.ranking_scope, "verification_calls": self.verification_calls,
                "gate_column_steps": self.gate_column_steps, "engine_version": self.engine_version,
                "verifier_version": self.verifier_version, "source_commit": self.source_commit,
                "numerical_environment": self.numerical_environment.to_dict()}

    def to_json(self):
        return wire.write_json(self.to_dict())

    @classmethod
    def from_dict(cls, value):
        wire.header(value, SCHEMA, _FIELDS)
        logical = LogicalProgram.from_dict(value["logical_program"])
        generation = GenerationReport.from_dict(value["generation"])
        candidates = {candidate.candidate_id: candidate for candidate in generation.candidates}
        implementation_values = wire.array(value["implementations"])
        if len(implementation_values) > len(candidates):
            _invalid("too many implementation bindings")
        implementations = []
        physical_ids = []
        for item in implementation_values:
            wire.fields(item, ("candidate_id", "physical_program", "physical_id"))
            identifier = item["candidate_id"]
            if type(identifier) is not str or identifier not in candidates:
                raise ValueError("Q3-SEARCH-003: unknown implementation candidate")
            physical = LogicalProgram.from_dict(item["physical_program"])
            implementations.append(CircuitImplementation(candidates[identifier].encoding, physical.ir))
            physical_ids.append(item["physical_id"])
        inputs = _prepare(logical, generation, tuple(implementations), value["tolerance"], value["max_dimension"])
        if tuple(implementations) != inputs.implementations:
            _invalid("implementation arrays must be in candidate order")
        if (type(value["logical_id"]) is not str or value["logical_id"] != inputs.logical_id or
                any(type(identifier) is not str for identifier in physical_ids) or
                tuple(physical_ids) != inputs.physical_ids):
            _invalid("logical or physical program digest disagrees with content")
        evaluation_values = wire.array(value["evaluations"])
        plan = _plan(inputs)
        if len(evaluation_values) != len(plan.rows):
            _invalid("evaluation count disagrees with candidate count")
        evaluations = tuple(_decode_evaluation(item, inputs, row)
                            for item, row in zip(evaluation_values, plan.rows))
        result = cls._make(inputs, evaluations, engine_version=value["engine_version"],
                           verifier_version=value["verifier_version"], source_commit=value["source_commit"],
                           numerical_environment=NumericalEnvironment.from_dict(value["numerical_environment"]),
                           evidence_origin="recorded")
        for name in ("verification_calls", "gate_column_steps"):
            if type(value[name]) is not int or value[name] != getattr(result, name):
                _invalid("stored numerical ledger disagrees with the budget plan")
        if (type(value["ranking_scope"]) is not str or value["ranking_scope"] != RANKING_SCOPE or
                any(type(identifier) is not str for identifier in wire.array(value["front_ids"])) or
                tuple(value["front_ids"]) != result.front_ids):
            _invalid("front identity, order or declared scope disagrees")
        return result

    @classmethod
    def from_json(cls, text):
        return cls.from_dict(wire.read_json(text))
