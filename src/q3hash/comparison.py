"""Exact integer dominance and pass-only supplied-circuit Pareto fronts."""

from .evaluation import CandidateEvaluation
from .resources import ResourceCounts, checked_objectives


def _dominates(left, right, objectives):
    return (all(getattr(left, name) <= getattr(right, name) for name in objectives) and
            any(getattr(left, name) < getattr(right, name) for name in objectives))


def dominates(left, right, objectives):
    """Strict vector mathematics; this operation does not certify a circuit."""
    if not isinstance(left, ResourceCounts) or not isinstance(right, ResourceCounts):
        raise TypeError("Q3-SEARCH-001: dominance requires two ResourceCounts values")
    checked_objectives(objectives)
    return _dominates(left, right, objectives)


def pareto_front(evaluations, objectives):
    """Return passing supplied-circuit candidate IDs, retaining ties/input order."""
    if type(evaluations) is not tuple:
        raise TypeError("Q3-SEARCH-001: evaluations must be an exact tuple")
    if type(objectives) is not tuple:
        raise TypeError("Q3-SEARCH-001: objectives must be an exact tuple")
    if len(evaluations) > 4096:
        raise ValueError("Q3-SEARCH-001: at most 4096 evaluations can be compared")
    if any(type(value) is not CandidateEvaluation for value in evaluations):
        raise TypeError("Q3-SEARCH-001: evaluations must be produced by evaluate_candidate")
    checked_objectives(objectives)
    identifiers = {}
    first = evaluations[0] if evaluations else None
    for value in evaluations:
        if value.logical != first.logical:
            raise ValueError("Q3-SEARCH-003: comparisons require one identical logical program")
        if (value.tolerance, value.max_dimension, value.max_operations_per_program) != (
                first.tolerance, first.max_dimension, first.max_operations_per_program):
            raise ValueError("Q3-SEARCH-001: comparison verification settings must agree")
        if value.candidate_id in identifiers:
            if identifiers[value.candidate_id] != value.candidate.encoding:
                raise ValueError("Q3-SEARCH-004: unequal encodings share a candidate digest")
            raise ValueError("Q3-SEARCH-003: each candidate must occur exactly once")
        identifiers[value.candidate_id] = value.candidate.encoding
    front = []
    for value in evaluations:
        if value.status != "pass":
            continue
        if any(_dominates(other.resources, value.resources, objectives) for other in front):
            continue
        front = [other for other in front if not _dominates(value.resources, other.resources, objectives)]
        front.append(value)
    return tuple(value.candidate_id for value in front)
