"""Verified hardware reports and strict pure replay; no numerical orchestrator."""

from dataclasses import dataclass, field
import hashlib

from . import _serialization as wire
from ._version import __version__
from .hardware_costs import _CostInput, _evaluate_costs
from .hardware_models import (ErrorRange, HardwareContext, HardwarePlacement, HardwareProfile,
                              TimeRange, _error, _object, _type, _wire_tuple, _wire_type)
from .logical_ir import LogicalProgram
from .search_report import SearchReport


SCHEMA = "q3hash.hardware-report"
RANKING_SCOPE = "verified-supplied-placements-under-one-profile"
SCHEDULE_SCOPE = "exclusive-sites-critical-path-v1"
_FIELDS = ("schema", "schema_version", "source_report", "source_id", "profile", "profile_id",
           "context", "context_id", "placements", "evaluations", "freshness", "gate_checks",
           "front_ids", "ranking_scope", "schedule_scope", "engine_version")
_ROW_FIELDS = ("candidate_id", "placement_id", "status", "reason_code", "rejections", "gate_checks", "costs")
_COST_FIELDS = ("active_sites", "native_operations", "two_site_operations", "critical_path_ps",
                "serial_duration_ps", "timing_reason", "used_errors", "circuit_error", "circuit_error_reason")
_STATUSES = ("ineligible", "unplaced", "unsupported", "not-evaluated", "supported")


def _hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _metadata(value):
    if type(value) is not str or not value:
        _error("Q3-HARD-005", "engine metadata must be a nonempty string")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("Q3-SER-001: invalid hardware metadata Unicode") from error
    return value


@dataclass(frozen=True)
class _Prepared:
    source: SearchReport
    source_id: str
    profile: HardwareProfile
    profile_id: str
    context: HardwareContext
    context_id: str
    placements: tuple
    requests: tuple
    placement_ids: tuple


def _prepare(source, profile, placements, context, *, recorded=False):
    """Preflight all source evidence, placements and identity inputs before costs."""
    _type(source, SearchReport, "Q3-HARD-001", "source report")
    if not recorded and source.evidence_origin != "computed":
        _error("Q3-HARD-005", "producer requires computed source evidence; reevaluate recorded inputs first")
    _type(profile, HardwareProfile, "Q3-HARD-001", "profile")
    _type(context, HardwareContext, "Q3-HARD-001", "context")
    _type(placements, tuple, "Q3-HARD-001", "placements")
    if len(placements) > 4096:
        _error("Q3-HARD-003", "at most 4096 placements are accepted")
    # Structural replay validates even manually altered computed objects. It
    # neither invokes a verifier nor authenticates a numerical snapshot.
    source_json = source.to_json()
    checked = SearchReport.from_json(source_json)
    if checked != source:
        _error("Q3-HARD-005", "source report differs from its validated snapshot")
    context.validate_profile(profile)
    source_id, profile_id, context_id = _hash(source_json), profile.profile_id, context.context_id
    identities = {}

    def register(identifier, content):
        previous = identities.get(identifier)
        if previous is not None and previous != content:
            _error("Q3-HARD-004", "digest collision between unequal identity inputs")
        identities[identifier] = content

    for identifier, content in ((source_id, source_json), (profile_id, profile.to_json()),
                                (context_id, context.to_json()), (source.logical_id, source.logical.to_json())):
        register(identifier, content)
    members = {}
    for candidate in source.generation.candidates:
        register(candidate.candidate_id, candidate.encoding.to_json())
        members[candidate.candidate_id] = candidate
    implementations = {}
    for implementation, physical_id in zip(source.implementations, source._physical_ids):
        physical_json = LogicalProgram(implementation.circuit).to_json()
        register(physical_id, physical_json)
        implementations[implementation.encoding] = implementation.circuit, physical_id
    supplied = {}
    for placement in placements:
        _type(placement, HardwarePlacement, "Q3-HARD-001", "placement")
        candidate = members.get(placement.candidate_id)
        if candidate is None or placement.candidate_id in supplied:
            _error("Q3-HARD-003", "unknown or duplicate placement candidate")
        implementation = implementations.get(candidate.encoding)
        if implementation is None:
            _error("Q3-HARD-003", "placement requires a supplied circuit")
        circuit, physical_id = implementation
        placement.validate_for(profile, circuit.dimensions)
        identifier = placement.identifier(profile_id, physical_id)
        identity = wire.write_json(dict(schema="q3hash.hardware-placement-key", schema_version=1,
            profile_id=profile_id, candidate_id=placement.candidate_id, physical_id=physical_id,
            site_indices=list(placement.site_indices)))
        register(identifier, identity)
        supplied[placement.candidate_id] = placement, identifier
    ordered, requests, placement_ids = [], [], []
    for evaluation in source.evaluations:
        candidate_id = evaluation.candidate_id
        item = supplied.get(candidate_id)
        placement, placement_id = (None, None) if item is None else item
        if placement is not None:
            ordered.append(placement)
        circuit = None if evaluation.implementation is None else evaluation.implementation.circuit
        requests.append(_CostInput(candidate_id, evaluation.status, circuit, placement))
        placement_ids.append(placement_id)
    return _Prepared(source, source_id, profile, profile_id, context, context_id,
                     tuple(ordered), tuple(requests), tuple(placement_ids))


def _cost_dict(costs):
    if costs is None:
        return None
    return dict(active_sites=costs.active_sites, native_operations=costs.native_operations,
        two_site_operations=costs.two_site_operations,
        critical_path_ps=None if costs.critical_path_ps is None else costs.critical_path_ps.to_dict(),
        serial_duration_ps=None if costs.serial_duration_ps is None else costs.serial_duration_ps.to_dict(),
        timing_reason=costs.timing_reason,
        used_errors=[dict(kind=e.kind.value, sites=list(e.sites), occurrences=e.occurrences,
                          error=None if e.error is None else e.error.to_dict()) for e in costs.used_errors],
        circuit_error=costs.circuit_error, circuit_error_reason=costs.circuit_error_reason)


@dataclass(frozen=True, init=False)
class HardwareEvaluation:
    candidate_id: str
    placement_id: str | None
    status: str
    reason_code: str
    rejections: tuple
    gate_checks: int
    costs: object

    def __init__(self, *args, **kwargs):
        raise TypeError("Q3-HARD-005: hardware evaluations are producer-derived")

    @classmethod
    def _derived(cls, row, placement_id):
        value = object.__new__(cls)
        for name in ("candidate_id", "status", "reason_code", "rejections", "gate_checks", "costs"):
            object.__setattr__(value, name, getattr(row, name))
        object.__setattr__(value, "placement_id", placement_id)
        return value

    def to_dict(self):
        return dict(candidate_id=self.candidate_id, placement_id=self.placement_id, status=self.status,
            reason_code=self.reason_code,
            rejections=[dict(code=r.code, operation_index=r.operation_index, axis_index=r.axis_index, sites=list(r.sites))
                        for r in self.rejections], gate_checks=self.gate_checks, costs=_cost_dict(self.costs))


def _vector(row, objectives):
    if row.status != "supported":
        return None
    values = []
    for name in objectives:
        value = getattr(row.costs, name)
        if value is None:
            return None
        values.append((value, value) if type(value) is int else (value.lower_ps, value.upper_ps))
    return tuple(values)


def _interval_front(rows, objectives):
    eligible = [(row.placement_id, _vector(row, objectives)) for row in rows]
    eligible = [(identifier, vector) for identifier, vector in eligible if vector is not None]

    def dominates(left, right):
        return all(a[1] <= b[0] for a, b in zip(left, right)) and any(a[1] < b[0] for a, b in zip(left, right))

    return tuple(identifier for i, (identifier, vector) in enumerate(eligible)
                 if not any(j != i and dominates(other, vector) for j, (_, other) in enumerate(eligible)))


def _claimed_row(value):
    """Strict nested shapes/types, normalising only permitted error endpoints."""
    wire.fields(value, _ROW_FIELDS)
    for name in ("candidate_id", "status", "reason_code"):
        _wire_type(value[name], str)
    if value["placement_id"] is not None:
        _wire_type(value["placement_id"], str)
    _wire_type(value["gate_checks"], int)
    rejections = []
    for item in wire.array(value["rejections"]):
        wire.fields(item, ("code", "operation_index", "axis_index", "sites"))
        _wire_type(item["code"], str)
        for name in ("operation_index", "axis_index"):
            if item[name] is not None:
                _wire_type(item[name], int)
        rejections.append({**item, "sites": list(_wire_tuple(item["sites"], int))})
    costs = value["costs"]
    if costs is not None:
        wire.fields(costs, _COST_FIELDS)
        costs = dict(costs)
        for name in ("active_sites", "native_operations", "two_site_operations"):
            _wire_type(costs[name], int)
        for name in ("critical_path_ps", "serial_duration_ps"):
            if costs[name] is not None:
                costs[name] = TimeRange.from_dict(_object(costs[name])).to_dict()
        for name in ("timing_reason", "circuit_error_reason"):
            _wire_type(costs[name], str)
        if costs["circuit_error"] is not None:
            _error("Q3-HARD-005", "a circuit error estimate is not part of this model")
        errors = []
        for item in wire.array(costs["used_errors"]):
            wire.fields(item, ("kind", "sites", "occurrences", "error"))
            _wire_type(item["kind"], str)
            _wire_type(item["occurrences"], int)
            errors.append(dict(kind=item["kind"], sites=list(_wire_tuple(item["sites"], int)), occurrences=item["occurrences"],
                               error=None if item["error"] is None else ErrorRange.from_dict(_object(item["error"])).to_dict()))
        costs["used_errors"] = errors
    return {**value, "rejections": rejections, "costs": costs}


@dataclass(frozen=True, init=False)
class HardwareReport:
    source_report: SearchReport
    source_id: str
    profile: HardwareProfile
    profile_id: str
    context: HardwareContext
    context_id: str
    placements: tuple
    evaluations: tuple
    freshness: str
    gate_checks: int
    front_ids: tuple
    ranking_scope: str
    schedule_scope: str
    engine_version: str
    evidence_origin: str = field(compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("Q3-HARD-005: use assess_hardware or strict report decoding")

    @classmethod
    def _make(cls, inputs, *, engine_version, evidence_origin):
        _metadata(engine_version)
        batch = _evaluate_costs(inputs.requests, inputs.profile, inputs.context)
        evaluations = tuple(HardwareEvaluation._derived(row, identifier)
                            for row, identifier in zip(batch.evaluations, inputs.placement_ids))
        value = object.__new__(cls)
        for name in ("source_id", "profile", "profile_id", "context", "context_id", "placements"):
            object.__setattr__(value, name, getattr(inputs, name))
        fields = dict(source_report=inputs.source, evaluations=evaluations, freshness=batch.freshness,
                      gate_checks=batch.gate_checks, front_ids=_interval_front(evaluations, inputs.context.objectives),
                      ranking_scope=RANKING_SCOPE, schedule_scope=SCHEDULE_SCOPE,
                      engine_version=engine_version, evidence_origin=evidence_origin)
        for name, item in fields.items():
            object.__setattr__(value, name, item)
        return value

    @property
    def status_counts(self):
        return {status: sum(row.status == status for row in self.evaluations) for status in _STATUSES}

    @property
    def front_is_partial(self):
        return (self.source_report.front_is_partial or
                any(row.status in ("unplaced", "not-evaluated") or
                    (row.status == "supported" and _vector(row, self.context.objectives) is None)
                    for row in self.evaluations))

    @property
    def front_reason(self):
        if not self.evaluations:
            return "no-candidates"
        if not any(row.status == "pass" for row in self.source_report.evaluations):
            return "no-verified-supplied-circuits"
        if not any(source.status == "pass" and row.placement_id is not None
                   for source, row in zip(self.source_report.evaluations, self.evaluations)):
            return "no-placed-verified-circuits"
        if not any(row.status == "supported" for row in self.evaluations):
            return "no-supported-placements"
        return RANKING_SCOPE if self.front_ids else "no-complete-objective-vectors"

    def to_dict(self):
        return dict(schema=SCHEMA, schema_version=1, source_report=self.source_report.to_dict(), source_id=self.source_id,
            profile=self.profile.to_dict(), profile_id=self.profile_id, context=self.context.to_dict(),
            context_id=self.context_id, placements=[p.to_dict() for p in self.placements],
            evaluations=[row.to_dict() for row in self.evaluations], freshness=self.freshness,
            gate_checks=self.gate_checks, front_ids=list(self.front_ids), ranking_scope=self.ranking_scope,
            schedule_scope=self.schedule_scope, engine_version=self.engine_version)

    def to_json(self):
        return wire.write_json(self.to_dict())

    @classmethod
    def from_dict(cls, value):
        wire.header(value, SCHEMA, _FIELDS)
        source = SearchReport.from_dict(_object(value["source_report"]))
        profile = HardwareProfile.from_dict(_object(value["profile"]))
        context = HardwareContext.from_dict(_object(value["context"]))
        raw_placements = wire.array(value["placements"])
        if len(raw_placements) > 4096:
            _error("Q3-HARD-003", "too many recorded placements")
        placements = tuple(HardwarePlacement.from_dict(_object(p)) for p in raw_placements)
        inputs = _prepare(source, profile, placements, context, recorded=True)
        if placements != inputs.placements:
            _error("Q3-HARD-005", "recorded placements must be in source candidate order")
        for name in ("source_id", "profile_id", "context_id"):
            if type(value[name]) is not str or value[name] != getattr(inputs, name):
                _error("Q3-HARD-005", "recorded input fingerprint disagrees")
        rows = wire.array(value["evaluations"])
        if len(rows) != len(source.evaluations):
            _error("Q3-HARD-005", "one evaluation is required per retained source candidate")
        claimed = [_claimed_row(_object(row)) for row in rows]
        result = cls._make(inputs, engine_version=value["engine_version"], evidence_origin="recorded")
        for name in ("freshness", "ranking_scope", "schedule_scope"):
            if type(value[name]) is not str or value[name] != getattr(result, name):
                _error("Q3-HARD-005", "recorded identity, freshness or scope disagrees")
        if type(value["gate_checks"]) is not int or value["gate_checks"] != result.gate_checks:
            _error("Q3-HARD-005", "recorded work counter disagrees")
        if _wire_tuple(value["front_ids"], str) != result.front_ids:
            _error("Q3-HARD-005", "recorded front identities or order disagree")
        if wire.write_json(claimed) != wire.write_json([row.to_dict() for row in result.evaluations]):
            _error("Q3-HARD-005", "recorded statuses, rejections, timing or error records disagree")
        return result

    @classmethod
    def from_json(cls, text):
        return cls.from_dict(wire.read_json(text))


def hardware_front(report):
    _type(report, HardwareReport, "Q3-HARD-001", "hardware report")
    return report.front_ids
