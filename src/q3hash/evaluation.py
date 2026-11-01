"""Immutable supplied-circuit inputs and producer-only comparison evidence."""

from dataclasses import dataclass
import math
from typing import Optional

from .encoding import BasisEncoding
from .equivalence import dense_limit
from .ir import CircuitIR
from .logical_ir import LogicalProgram
from .resources import ResourceCounts, count_resources
from .search import EncodingCandidate
from .verification import VerificationReport


@dataclass(frozen=True)
class CircuitImplementation:
    encoding: BasisEncoding
    circuit: CircuitIR

    def __post_init__(self):
        if not isinstance(self.encoding, BasisEncoding) or not isinstance(self.circuit, CircuitIR):
            raise TypeError("Q3-SEARCH-003: expected a basis encoding and physical CircuitIR")
        if self.circuit.dimensions != self.encoding.physical_dimensions:
            raise ValueError("Q3-SEARCH-003: circuit dimensions do not match its encoding")


_METRICS = ("subspace_residual", "leakage_norm", "logical_unitarity_error", "physical_unitarity_error")
_NO_CALL = {"no-implementation": "unimplemented", "operation-limit": "unsupported",
            "dense-limit": "unsupported", "verification-call-budget": "not-evaluated",
            "gate-column-budget": "not-evaluated"}


def _checked_options(tolerance, max_dimension, max_operations_per_program):
    if type(max_operations_per_program) is not int:
        raise TypeError("Q3-SEARCH-001: operation limit must be an exact integer")
    if type(tolerance) not in (int, float):
        raise TypeError("Q3-VERIFY-001: tolerance must be a built-in positive finite number")
    try:
        tolerance = float(tolerance)
    except OverflowError as error:
        raise ValueError("Q3-VERIFY-001: unrepresentable tolerance") from error
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("Q3-VERIFY-001: tolerance must be positive and finite")
    dense_limit(max_dimension)
    if not 1 <= max_operations_per_program <= 16384:
        raise ValueError("Q3-SEARCH-001: operation limit must be in 1..16384")
    return tolerance


def _checked_verification(report, logical, candidate, tolerance):
    if (type(report) is not VerificationReport or type(report.status) is not str or
            report.status not in ("pass", "fail") or type(report.evidence) is not str or
            report.evidence != "q3hash-circuit" or type(report.logical_size) is not int or
            type(report.physical_size) is not int or report.logical_size != logical.state_size or
            report.physical_size != candidate.encoding.physical_size or
            type(report.tolerance) is not float or report.tolerance != tolerance or
            type(report.reason) is not str or not report.reason):
        raise ValueError("Q3-SEARCH-005: inconsistent circuit-verification evidence")
    values = tuple(getattr(report, name) for name in _METRICS)
    if report.status == "fail" and all(value is None for value in values) and report.global_phase is None:
        return "nonfinite-metrics"
    phase = report.global_phase
    try:
        invalid = (any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
                       for value in values) or type(phase) is not complex or
                   not math.isfinite(phase.real) or not math.isfinite(phase.imag) or
                   abs(abs(phase) - 1) > 1e-12)
    except OverflowError:
        invalid = True
    if invalid:
        raise ValueError("Q3-SEARCH-005: invalid numerical verification snapshot")
    passed = all(value <= tolerance for value in values)
    if passed != (report.status == "pass"):
        raise ValueError("Q3-SEARCH-005: verification status disagrees with its metrics")
    return "verified" if passed else "equivalence-failed"


@dataclass(frozen=True, init=False)
class CandidateEvaluation:
    logical: LogicalProgram
    candidate: EncodingCandidate
    implementation: Optional[CircuitImplementation]
    tolerance: float
    max_dimension: int
    max_operations_per_program: int
    status: str
    reason_code: str
    verification: Optional[VerificationReport]
    resources: Optional[ResourceCounts]

    def __init__(self, *args, **kwargs):
        raise TypeError("Q3-SEARCH-005: use evaluate_candidate to produce comparison evidence")

    @property
    def candidate_id(self):
        return self.candidate.candidate_id

    @property
    def verification_calls(self):
        return int(self.verification is not None)

    @property
    def gate_column_steps(self):
        if self.verification is None:
            return 0
        return (self.logical.state_size * len(self.logical.ir.operations) +
                self.implementation.circuit.state_size * len(self.implementation.circuit.operations))

    @classmethod
    def _computed(cls, logical, candidate, implementation, tolerance, max_dimension,
                  max_operations_per_program, *, verification=None, reason_code=None):
        # Called only by the adapter after full input preflight. Caller-supplied
        # status/count vectors are never accepted by the public producer API.
        if verification is not None:
            reason_code = _checked_verification(verification, logical, candidate, tolerance)
            status = verification.status
        else:
            if reason_code not in _NO_CALL:
                raise ValueError("Q3-SEARCH-005: unsupported no-call evaluation reason")
            status = _NO_CALL[reason_code]
        resources = (count_resources(implementation.circuit, logical_size=logical.state_size)
                     if status == "pass" else None)
        value = object.__new__(cls)
        values = dict(logical=logical, candidate=candidate, implementation=implementation,
                      tolerance=tolerance, max_dimension=max_dimension,
                      max_operations_per_program=max_operations_per_program, status=status,
                      reason_code=reason_code, verification=verification, resources=resources)
        for name, item in values.items():
            object.__setattr__(value, name, item)
        return value

    def to_dict(self):
        snapshot = None
        if self.verification is not None:
            report = self.verification
            phase = report.global_phase
            snapshot = {"status": report.status, "evidence": report.evidence,
                        "reason": report.reason, "tolerance": report.tolerance,
                        "global_phase": None if phase is None else [phase.real, phase.imag],
                        **{name: getattr(report, name) for name in _METRICS}}
        return {"candidate_id": self.candidate_id, "status": self.status,
                "reason_code": self.reason_code, "verification": snapshot,
                "resources": None if self.resources is None else self.resources.to_dict()}
