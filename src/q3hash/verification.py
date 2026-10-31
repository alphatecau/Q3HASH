"""Typed preflight and pass/fail/unsupported reports; no reverse model imports."""

from dataclasses import dataclass
import math
from typing import Optional

from .encoding import BasisEncoding
from .equivalence import ReferenceOperator, compare_operators, dense_limit, operator_matrix
from .ir import CircuitIR
from .logical_ir import LogicalProgram


@dataclass(frozen=True)
class VerificationReport:
    status: str
    reason: str
    evidence: str
    logical_size: int
    physical_size: int
    tolerance: float
    global_phase: Optional[complex] = None
    subspace_residual: Optional[float] = None
    leakage_norm: Optional[float] = None
    logical_unitarity_error: Optional[float] = None
    physical_unitarity_error: Optional[float] = None


def verify_equivalence(logical, physical, encoding, *, tolerance=1e-10, max_dimension=64):
    if not isinstance(logical, LogicalProgram):
        raise TypeError("Q3-COMP-001: logical input must be a LogicalProgram")
    if not isinstance(physical, (CircuitIR, ReferenceOperator)):
        raise TypeError("Q3-COMP-001: physical input must be a CircuitIR or ReferenceOperator")
    if not isinstance(encoding, BasisEncoding):
        raise TypeError("Q3-COMP-001: encoding input must be a BasisEncoding")
    if type(tolerance) not in (int, float):
        raise TypeError("Q3-VERIFY-001: tolerance must be a built-in positive finite number")
    try:
        tolerance = float(tolerance)
    except OverflowError as error:
        raise ValueError("Q3-VERIFY-001: unrepresentable tolerance") from error
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("Q3-VERIFY-001: tolerance must be positive and finite")
    dense_limit(max_dimension)
    if logical.dimensions != encoding.logical_dimensions or physical.dimensions != encoding.physical_dimensions:
        raise ValueError("Q3-COMP-001: logical or physical dimensions do not match the encoding")
    evidence = "reference-only" if isinstance(physical, ReferenceOperator) else "q3hash-circuit"
    base = (evidence, encoding.logical_size, encoding.physical_size, tolerance)
    if encoding.physical_size > max_dimension:
        return VerificationReport("unsupported", "Physical dimension exceeds the declared dense verification limit", *base)
    logical_matrix = operator_matrix(logical.ir, max_dimension=max_dimension)
    physical_matrix = (physical.matrix if isinstance(physical, ReferenceOperator) else
                       operator_matrix(physical, max_dimension=max_dimension))
    try:
        metrics = compare_operators(logical_matrix, physical_matrix, encoding)
    except OverflowError:
        return VerificationReport("fail", "Nonfinite numerical calculation; candidate does not meet the unitary criterion", *base)
    numbers = (metrics.subspace_residual, metrics.leakage_norm,
               metrics.logical_unitarity_error, metrics.physical_unitarity_error)
    if not all(math.isfinite(value) for value in numbers):
        return VerificationReport("fail", "Nonfinite numerical calculation; candidate does not meet the unitary criterion", *base)
    passed = all(value <= tolerance for value in numbers)
    reason = ("Complete encoded-subspace residual, leakage and unitarity meet the declared tolerance" if passed else
              "Complete encoded-subspace residual, leakage or unitarity exceeds the declared tolerance")
    return VerificationReport("pass" if passed else "fail", reason, *base,
                              metrics.global_phase, *numbers)
