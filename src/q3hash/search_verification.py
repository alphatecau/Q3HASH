"""Manual candidate verification adapter; aggregate search orchestration is pending."""

import math

from .equivalence import dense_limit
from .evaluation import CandidateEvaluation, CircuitImplementation
from .logical_ir import LogicalProgram
from .search import EncodingCandidate
from .verification import verify_equivalence


def evaluate_candidate(logical, candidate, implementation=None, *, tolerance=1e-10,
                       max_dimension=64, max_operations_per_program=1024):
    """Verify one supplied circuit and derive its structural counts only on pass."""
    if (not isinstance(logical, LogicalProgram) or not isinstance(candidate, EncodingCandidate) or
            (implementation is not None and not isinstance(implementation, CircuitImplementation))):
        raise TypeError("Q3-SEARCH-001: expected logical program, candidate and optional circuit implementation")
    if type(max_operations_per_program) is not int:
        raise TypeError("Q3-SEARCH-001: operation limit must be an exact integer")
    if (logical.dimensions != candidate.encoding.logical_dimensions or
            (implementation is not None and implementation.encoding != candidate.encoding)):
        raise ValueError("Q3-SEARCH-003: logical program, candidate and implementation disagree")
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
    options = (logical, candidate, implementation, tolerance, max_dimension, max_operations_per_program)
    if implementation is None:
        return CandidateEvaluation._computed(*options, reason_code="no-implementation")
    if (len(logical.ir.operations) > max_operations_per_program or
            len(implementation.circuit.operations) > max_operations_per_program):
        return CandidateEvaluation._computed(*options, reason_code="operation-limit")
    if candidate.encoding.physical_size > max_dimension:
        return CandidateEvaluation._computed(*options, reason_code="dense-limit")
    report = verify_equivalence(logical, implementation.circuit, candidate.encoding,
                                tolerance=tolerance, max_dimension=max_dimension)
    return CandidateEvaluation._computed(*options, verification=report)
