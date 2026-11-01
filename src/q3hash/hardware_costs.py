"""Internal target-model arithmetic; source verification belongs to the producer."""

from dataclasses import dataclass, field
from datetime import timedelta

from .hardware_models import (ErrorRange, HardwareContext, HardwarePlacement,
                              HardwareProfile, TimeRange, _digest, _error, _instant, _type)
from .ir import CircuitIR, GateKind


_SOURCE_STATUSES = ("pass", "unimplemented", "fail", "unsupported", "not-evaluated")


@dataclass(frozen=True)
class _CostInput:
    """Private ledger input, never accepted as public verification evidence."""

    candidate_id: str
    source_status: str
    circuit: CircuitIR | None
    placement: HardwarePlacement | None = None


@dataclass(frozen=True)
class _Rejection:
    code: str
    operation_index: int | None
    axis_index: int | None
    sites: tuple[int, ...]


@dataclass(frozen=True)
class _UsedError:
    kind: GateKind
    sites: tuple[int, ...]
    occurrences: int
    error: ErrorRange | None


@dataclass(frozen=True)
class _CircuitCosts:
    active_sites: int
    native_operations: int
    two_site_operations: int
    critical_path_ps: TimeRange | None
    serial_duration_ps: TimeRange | None
    timing_reason: str
    used_errors: tuple[_UsedError, ...]
    circuit_error: None = field(default=None, init=False)
    circuit_error_reason: str = field(default="no-noise-composition-model", init=False)


@dataclass(frozen=True)
class _CostEvaluation:
    candidate_id: str
    status: str
    reason_code: str
    rejections: tuple[_Rejection, ...] = ()
    gate_checks: int = 0
    costs: _CircuitCosts | None = None


@dataclass(frozen=True)
class _CostBatch:
    profile_id: str
    context_id: str
    freshness: str
    evaluations: tuple[_CostEvaluation, ...]
    gate_checks: int


def _freshness(profile, context):
    """Exact explicit-instant arithmetic, without a floating-point clock."""
    context.validate_profile(profile)
    data = profile.provenance
    if data.kind == "synthetic":
        return "synthetic"
    if data.calibrated_at is None:
        return "unknown"
    elapsed = _instant(context.as_of, "Q3-HARD-001") - _instant(data.calibrated_at, "Q3-HARD-002")
    return "fresh" if elapsed <= timedelta(seconds=context.max_calibration_age_seconds) else "stale"


def _preflight(inputs, profile, context):
    """Validate the entire input batch and fingerprints before inspecting gates."""
    _type(inputs, tuple, "Q3-HARD-001", "cost inputs")
    _type(profile, HardwareProfile, "Q3-HARD-001", "profile")
    _type(context, HardwareContext, "Q3-HARD-001", "context")
    if len(inputs) > 4096:
        _error("Q3-HARD-001", "at most 4096 cost inputs are supported")
    context.validate_profile(profile)
    seen = set()
    for item in inputs:
        _type(item, _CostInput, "Q3-HARD-001", "cost input")
        _digest(item.candidate_id, "Q3-HARD-003")
        _type(item.source_status, str, "Q3-HARD-001", "source status")
        if item.source_status not in _SOURCE_STATUSES:
            _error("Q3-HARD-005", "unknown source status")
        if item.candidate_id in seen:
            _error("Q3-HARD-003", "duplicate candidate input")
        seen.add(item.candidate_id)
        if item.circuit is None:
            if item.source_status != "unimplemented":
                _error("Q3-HARD-005", "source status requires a supplied circuit")
            if item.placement is not None:
                _error("Q3-HARD-003", "a missing circuit cannot have a placement")
            continue
        _type(item.circuit, CircuitIR, "Q3-HARD-001", "physical circuit")
        if item.source_status == "unimplemented":
            _error("Q3-HARD-005", "unimplemented source cannot contain a circuit")
        if len(item.circuit.registers) > 64:
            _error("Q3-HARD-003", "physical circuit exceeds the site domain")
        if item.source_status == "pass" and len(item.circuit.operations) > 16384:
            _error("Q3-HARD-005", "passing source exceeds the operation domain")
        if item.placement is not None:
            _type(item.placement, HardwarePlacement, "Q3-HARD-001", "placement")
            if item.placement.candidate_id != item.candidate_id:
                _error("Q3-HARD-003", "placement candidate does not match its input")
            item.placement.validate_for(profile, item.circuit.dimensions)
    # The future source-report producer additionally fingerprints its complete
    # source evidence and resolves identity collisions before calling this kernel.
    return profile.profile_id, context.context_id


def _ordered_sites(operation, placement):
    if operation.kind is GateKind.SUM:
        return placement[operation.control], placement[operation.target]
    return (placement[operation.target],)


def _inspect_circuit(circuit, placement, profile, freshness, edges, bindings):
    """Inspect every gate and fold timing along the most recent touched sites."""
    rejections, used = [], {}
    finish_lower = [0] * len(profile.site_dimensions)
    finish_upper = [0] * len(profile.site_dimensions)
    serial_lower = serial_upper = two_site = 0
    missing_duration = False
    timing_available = freshness in ("synthetic", "fresh")
    for index, operation in enumerate(circuit.operations):
        sites = _ordered_sites(operation, placement)
        if operation.kind is GateKind.SUM:
            two_site += 1
            if sites not in edges:
                rejections.append(_Rejection("directed-coupling", index, None, sites))
                continue
        binding_index = bindings.get((operation.kind, sites))
        if binding_index is None:
            rejections.append(_Rejection("native-gate", index, None, sites))
            continue
        binding = profile.bindings[binding_index]
        used[binding_index] = used.get(binding_index, 0) + 1
        duration = binding.duration
        if duration is None:
            missing_duration = True
        elif timing_available and not missing_duration:
            lower = duration.lower_ps + max(finish_lower[site] for site in sites)
            upper = duration.upper_ps + max(finish_upper[site] for site in sites)
            for site in sites:
                finish_lower[site], finish_upper[site] = lower, upper
            serial_lower += duration.lower_ps
            serial_upper += duration.upper_ps
    if rejections:
        return tuple(rejections), None
    errors = tuple(_UsedError(profile.bindings[index].kind, profile.bindings[index].sites, used[index],
                              profile.bindings[index].error) for index in sorted(used))
    operations = len(circuit.operations)
    if not operations:
        critical = serial = TimeRange(0, 0)
        reason = "empty-circuit"
    elif freshness in ("stale", "unknown"):
        critical = serial = None
        reason = freshness + "-calibration"
    elif missing_duration:
        critical = serial = None
        reason = "missing-duration"
    else:
        critical = TimeRange(max(finish_lower), max(finish_upper))
        serial = TimeRange(serial_lower, serial_upper)
        reason = "model-range"
    return (), _CircuitCosts(len(circuit.registers), operations, two_site, critical, serial, reason, errors)


def _evaluate_costs(inputs, profile, context):
    """Pure bounded kernel; no fresh-source claim, report codec, front or verifier."""
    profile_id, context_id = _preflight(inputs, profile, context)
    freshness = _freshness(profile, context)
    edges = frozenset(profile.couplings)
    bindings = {(entry.kind, entry.sites): index for index, entry in enumerate(profile.bindings)}
    charged, rows = 0, []
    for item in inputs:
        if item.source_status != "pass":
            rows.append(_CostEvaluation(item.candidate_id, "ineligible", "source-" + item.source_status))
            continue
        if item.placement is None:
            rows.append(_CostEvaluation(item.candidate_id, "unplaced", "no-placement"))
            continue
        sites = item.placement.site_indices
        dimensions = item.circuit.dimensions
        mismatches = tuple(_Rejection("site-dimension", None, axis, (site,))
                           for axis, site in enumerate(sites)
                           if dimensions[axis] != profile.site_dimensions[site])
        if mismatches:
            rows.append(_CostEvaluation(item.candidate_id, "unsupported", "site-dimension", mismatches))
            continue
        operations = len(item.circuit.operations)
        if charged + operations > context.max_gate_checks:
            rows.append(_CostEvaluation(item.candidate_id, "not-evaluated", "hardware-operation-budget"))
            continue
        charged += operations
        rejections, costs = _inspect_circuit(item.circuit, sites, profile, freshness, edges, bindings)
        status, reason = ("unsupported", "target-rejections") if rejections else ("supported", "native-model-supported")
        rows.append(_CostEvaluation(item.candidate_id, status, reason, rejections, operations, costs))
    return _CostBatch(profile_id, context_id, freshness, tuple(rows), charged)
