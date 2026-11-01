"""Fresh supplied-circuit verification and conditional hardware assessment CLI."""

import argparse
import hashlib
from pathlib import Path
import sys

from . import _serialization as wire
from ._version import __version__
from .encoding import BasisEncoding
from .evaluation import CircuitImplementation
from .hardware import assess_hardware
from .hardware_models import HardwareContext, HardwarePlacement, HardwareProfile, _wire_tuple
from .logical_ir import LogicalProgram, logical_from_source
from .search import SearchConstraints, generate_encodings
from .search_cli import _read_input
from .search_report import _prepare as _prepare_source
from .search_verification import evaluate_candidates


def _preflight(logical, generation, implementations, profile, context, raw_placements, tolerance, max_dimension):
    """Validate the complete request and available identity inputs before numerics."""
    source = _prepare_source(logical, generation, implementations, tolerance, max_dimension)
    context.validate_profile(profile)
    profile_id, context_id = profile.profile_id, context.context_id
    identities = {}

    def register(identifier, content):
        if identifier in identities and identities[identifier] != content:
            raise ValueError("Q3-HARD-004: digest collision between unequal identity inputs")
        identities[identifier] = content

    for identifier, content in ((source.logical_id, logical.to_json()), (profile_id, profile.to_json()),
                                (context_id, context.to_json())):
        register(identifier, content)
    members = {}
    for candidate in generation.candidates:
        register(candidate.candidate_id, candidate.encoding.to_json())
        members[candidate.encoding] = candidate.candidate_id
    supplied = {}
    for implementation, physical_id in zip(source.implementations, source.physical_ids):
        register(physical_id, LogicalProgram(implementation.circuit).to_json())
        supplied[implementation.encoding] = implementation.circuit, physical_id
    placements, seen = [], set()
    for encoding, sites in raw_placements:
        encoding_json = encoding.to_json()
        candidate_id = hashlib.sha256(encoding_json.encode("utf-8")).hexdigest()
        register(candidate_id, encoding_json)
        if encoding not in members or candidate_id in seen or encoding not in supplied:
            raise ValueError("Q3-HARD-003: placement requires a retained encoding, a supplied circuit and no duplicates")
        circuit, physical_id = supplied[encoding]
        placement = HardwarePlacement(candidate_id, sites)
        placement.validate_for(profile, circuit.dimensions)
        identifier = placement.identifier(profile_id, physical_id)
        identity = wire.write_json(dict(schema="q3hash.hardware-placement-key", schema_version=1,
            profile_id=profile_id, candidate_id=candidate_id, physical_id=physical_id, site_indices=list(sites)))
        register(identifier, identity)
        placements.append(placement)
        seen.add(candidate_id)
    return tuple(placements)


def _exit_code(report):
    if report.source_report.status_counts["fail"]:
        return 1
    if report.front_is_partial:
        return 3
    if not report.front_ids:
        return 4 if report.front_reason == "no-supported-placements" else 3
    return 0


def _range(value):
    return "unknown" if value is None else f"[{value.lower_ps},{value.upper_ps}] ps"


def _summary(report):
    source, profile, context = report.source_report, report.profile, report.context
    generation, provenance = source.generation, profile.provenance
    constraints = generation.constraints
    status = {0: "complete", 1: "verification-failed", 3: "partial-or-inconclusive", 4: "target-infeasible"}[_exit_code(report)]
    rejected = generation.dimension_rejections
    lines = ["Q3# conditional hardware assessment", f"Run status: {status}",
        f"Generation: {generation.completion} | stop: {generation.stop_reason or 'none'}",
        f"Dimensions: {generation.dimension_tuples_seen} considered | candidates: {generation.emitted_candidates}",
        f"Mappings: {generation.mapping_attempts} attempted | duplicates: {generation.duplicate_mappings}",
        f"Rejected dimensions: capacity={rejected.insufficient_capacity} size={rejected.physical_size_limit}",
        f"Rejected partitions: {generation.partition_rejections} | unavailable families: {generation.family_unavailable}",
        "Source statuses: " + " ".join(f"{name}={count}" for name, count in source.status_counts.items()),
        "Hardware statuses: " + " ".join(f"{name}={count}" for name, count in report.status_counts.items()),
        f"Verifier calls: {source.verification_calls}/{constraints.max_verifications}",
        f"Gate-column steps: {source.gate_column_steps}/{constraints.max_gate_column_steps}",
        f"Hardware gate checks: {report.gate_checks}/{context.max_gate_checks}",
        f"Verification limits: dimension={source.max_dimension} operations/program={constraints.max_operations_per_program}",
        f"Tolerance: {source.tolerance} | evidence: q3hash-circuit | software gate model",
        f"Profile: {profile.name} | SHA-256: {report.profile_id}",
        f"Provenance: {provenance.kind} | provider: {provenance.provider} | device: {provenance.device_id}",
        f"Snapshot: {provenance.snapshot_id} | source URI: {provenance.source_uri}",
        f"Retrieved: {provenance.retrieved_at} | calibrated: {provenance.calibrated_at}",
        f"As of: {context.as_of} | maximum calibration age: {context.max_calibration_age_seconds} s",
        f"Freshness: {report.freshness} | context SHA-256: {report.context_id}",
        "Objectives: " + ", ".join(context.objectives), f"Ranking scope: {report.ranking_scope}",
        f"Schedule scope: {report.schedule_scope}", f"Partial front: {'yes' if report.front_is_partial else 'no'}",
        f"Front reason: {report.front_reason} | front placements: {len(report.front_ids)}",
        f"Logical SHA-256: {source.logical_id} | source report SHA-256: {report.source_id}",
        f"Engine: {report.engine_version} | verifier: {source.verifier_version}",
        "Coverage is limited to the declared families, seeds, supplied circuits and placements under this profile.",
        "Timing ranges are conditional model inputs, not measured execution times or confidence bounds.",
        "Error ranges retain their declared metric; circuit error: unknown (no-noise-composition-model).",
        "No hardware execution, global optimality, fidelity or quantum advantage is established.", "Candidates:"]
    front = set(report.front_ids)
    for upstream, row in zip(source.evaluations, report.evaluations):
        lines.append(f"  {row.candidate_id} | source={upstream.status} ({upstream.reason_code}) | hardware={row.status} ({row.reason_code})")
        lines.append(f"    placement={row.placement_id or 'none'} | gate checks={row.gate_checks} | front={'yes' if row.placement_id in front else 'no'}")
        if upstream.verification is not None:
            v = upstream.verification
            lines.append(f"    phase={v.global_phase} residual={v.subspace_residual} leakage={v.leakage_norm} "
                         f"logical-unitarity={v.logical_unitarity_error} physical-unitarity={v.physical_unitarity_error}")
        for rejection in row.rejections:
            lines.append(f"    rejection={rejection.code} operation={rejection.operation_index} axis={rejection.axis_index} sites={rejection.sites}")
        if row.costs is not None:
            costs = row.costs
            lines.append(f"    active_sites={costs.active_sites} native_operations={costs.native_operations} two_site_operations={costs.two_site_operations}")
            lines.append(f"    critical_path_ps={_range(costs.critical_path_ps)} serial_duration_ps={_range(costs.serial_duration_ps)} | timing={costs.timing_reason}")
            for used in costs.used_errors:
                error = used.error
                diagnostic = "unknown" if error is None else f"{error.metric} [{error.lower},{error.upper}]"
                lines.append(f"    error diagnostic: {used.kind.value} {used.sites} occurrences={used.occurrences} {diagnostic}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Q3# fresh verification and conditional hardware assessment of explicitly supplied circuits")
    parser.add_argument("logical", type=Path, help="logical Q3# source with explicit dimensions")
    parser.add_argument("--profile", type=Path, required=True, help="strict hardware-profile JSON v1")
    parser.add_argument("--context", type=Path, required=True, help="strict hardware-context JSON v1 with explicit as-of, age, work and objectives")
    parser.add_argument("--constraints", type=Path, help="strict search-constraints JSON v1; otherwise SearchConstraints defaults")
    parser.add_argument("--seed", type=Path, action="append", default=[], help="explicit encoding JSON v1; repeat in seed order")
    parser.add_argument("--implementation", type=Path, nargs=2, action="append", default=[],
                        metavar=("ENCODING_JSON", "PHYSICAL_Q3"), help="bind a retained encoding to a supplied physical circuit")
    parser.add_argument("--placement", nargs=2, action="append", default=[],
                        metavar=("ENCODING_JSON", "SITE_INDICES_JSON"), help="place physical axes on sites, e.g. encoding.json '[1,2]'; repeat as needed")
    parser.add_argument("--tolerance", type=float, default=1e-10)
    parser.add_argument("--max-dimension", type=int, default=64, help="dense source-verifier limit (1–64)")
    parser.add_argument("--json", action="store_true", help="emit only canonical hardware-report JSON v1")
    parser.add_argument("--version", action="version", version=f"q3hash {__version__}")
    args = parser.parse_args(argv)
    try:
        if any(len(items) > 4096 for items in (args.seed, args.implementation, args.placement)):
            raise ValueError("Q3-CLI-001: at most 4096 seeds, implementations and placements per category")
        logical = logical_from_source(_read_input(args.logical))
        profile = HardwareProfile.from_json(_read_input(args.profile))
        context = HardwareContext.from_json(_read_input(args.context))
        constraints = SearchConstraints() if args.constraints is None else SearchConstraints.from_json(_read_input(args.constraints))
        seeds = tuple(BasisEncoding.from_json(_read_input(path)) for path in args.seed)
        implementations = tuple(CircuitImplementation(BasisEncoding.from_json(_read_input(encoding)),
            logical_from_source(_read_input(physical)).ir) for encoding, physical in args.implementation)
        raw_placements = tuple((BasisEncoding.from_json(_read_input(Path(encoding))), _wire_tuple(wire.read_json(sites), int))
                               for encoding, sites in args.placement)
        generation = generate_encodings(logical.dimensions, constraints, seed_encodings=seeds)
        placements = _preflight(logical, generation, implementations, profile, context, raw_placements,
                                args.tolerance, args.max_dimension)
        source = evaluate_candidates(logical, generation, implementations, tolerance=args.tolerance, max_dimension=args.max_dimension)
        report = assess_hardware(source, profile, placements, context)
        # Enforce the report transport contract before either output mode writes.
        canonical = report.to_json()
        output = canonical if args.json else _summary(report)
    except (OSError, TypeError, ValueError) as error:
        parser.error(str(error))
    sys.stdout.write(output)
    raise SystemExit(_exit_code(report))


if __name__ == "__main__":
    main()
