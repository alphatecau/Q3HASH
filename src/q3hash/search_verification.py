"""Bounded supplied-circuit verification using the unchanged complete verifier."""

from .evaluation import CandidateEvaluation, CircuitImplementation, _checked_options
from .logical_ir import LogicalProgram
from .search import EncodingCandidate
from .verification import verify_equivalence
from .search_report import SearchReport, _plan, _prepare


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
    tolerance = _checked_options(tolerance, max_dimension, max_operations_per_program)
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


def evaluate_candidates(logical, generation, implementations=(), *, tolerance=1e-10,
                        max_dimension=64):
    """Evaluate every retained candidate under one deterministic global ledger."""
    inputs = _prepare(logical, generation, implementations, tolerance, max_dimension)
    plan = _plan(inputs)
    evaluations = []
    for candidate, implementation, reason in plan.rows:
        options = (logical, candidate, implementation, inputs.tolerance, max_dimension,
                   generation.constraints.max_operations_per_program)
        if reason is not None:
            result = CandidateEvaluation._computed(*options, reason_code=reason)
        else:
            report = verify_equivalence(logical, implementation.circuit, candidate.encoding,
                                        tolerance=inputs.tolerance, max_dimension=max_dimension)
            result = CandidateEvaluation._computed(*options, verification=report)
        evaluations.append(result)
    return SearchReport._computed(inputs, tuple(evaluations))
