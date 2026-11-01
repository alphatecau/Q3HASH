"""Bounded encoding generation and explicit supplied-circuit comparison CLI."""

import argparse
from pathlib import Path
import sys

from . import _serialization as wire
from ._version import __version__
from .encoding import BasisEncoding
from .evaluation import CircuitImplementation
from .logical_ir import logical_from_source
from .search import SearchConstraints, generate_encodings
from .search_verification import evaluate_candidates


def _read_input(path):
    # Bound bytes before decoding or allocating a source/JSON syntax tree.
    with path.open("rb") as stream:
        data = stream.read(wire.MAX_JSON_BYTES + 1)
    if len(data) > wire.MAX_JSON_BYTES:
        raise ValueError("Q3-CLI-001: input exceeds the 1 MiB UTF-8 transport limit")
    return data.decode("utf-8")


def _exit_code(report):
    if report.status_counts["fail"]:
        return 1
    if not report.front_ids or report.front_is_partial:
        return 3
    return 0


def _summary(report):
    generation = report.generation
    constraints = generation.constraints
    status = "verification-failed" if report.status_counts["fail"] else (
        "partial" if report.front_is_partial else "complete" if report.front_ids else "no-candidates")
    rejected = generation.dimension_rejections
    lines = ["Q3# bounded encoding search", f"Run status: {status}",
             f"Generation: {generation.completion} | stop: {generation.stop_reason or 'none'}",
             f"Dimensions: {generation.dimension_tuples_seen} considered | candidates: {generation.emitted_candidates}",
             f"Mappings: {generation.mapping_attempts} attempted | duplicates: {generation.duplicate_mappings}",
             f"Rejected dimensions: capacity={rejected.insufficient_capacity} size={rejected.physical_size_limit}",
             f"Rejected partitions: {generation.partition_rejections} | unavailable families: {generation.family_unavailable}",
             "Statuses: " + " ".join(f"{name}={count}" for name, count in report.status_counts.items()),
             f"Verifier calls: {report.verification_calls}/{constraints.max_verifications}",
             f"Gate-column steps: {report.gate_column_steps}/{constraints.max_gate_column_steps}",
             f"Verification limits: dimension={report.max_dimension} operations/program={constraints.max_operations_per_program}",
             f"Tolerance: {report.tolerance}", "Evidence: q3hash-circuit | software gate model",
             f"Ranking scope: {report.ranking_scope}", f"Partial front: {'yes' if report.front_is_partial else 'no'}",
             f"Front reason: {report.front_reason}", f"Front candidates: {len(report.front_ids)}",
             "Coverage is limited to the declared map families, seeds and supplied circuits.",
             "Logical semantic SHA-256: " + report.logical_id,
             f"Engine: {report.engine_version} | verifier: {report.verifier_version}", "Candidates:"]
    front = set(report.front_ids)
    for row in report.evaluations:
        lines.append(f"  {row.candidate_id} | {row.candidate.encoding.physical_dimensions} | {row.status} | {row.reason_code}")
        if row.verification is not None:
            verification = row.verification
            lines.append(f"    phase={verification.global_phase} residual={verification.subspace_residual} "
                         f"leakage={verification.leakage_norm} logical-unitarity={verification.logical_unitarity_error} "
                         f"physical-unitarity={verification.physical_unitarity_error}")
        if row.resources is not None:
            lines.append("    " + " ".join(f"{name}={getattr(row.resources, name)}" for name in constraints.objectives) +
                         f" | front={'yes' if row.candidate_id in front else 'no'}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Q3# bounded encoding search over explicitly supplied circuits")
    parser.add_argument("logical", type=Path, help="logical Q3# source with explicit dimensions")
    parser.add_argument("--constraints", type=Path, help="strict search-constraints JSON v1 (defaults to SearchConstraints)")
    parser.add_argument("--seed", type=Path, action="append", default=[], help="explicit encoding JSON v1; repeat in seed order")
    parser.add_argument("--implementation", type=Path, nargs=2, action="append", default=[],
                        metavar=("ENCODING_JSON", "PHYSICAL_Q3"), help="bind a retained encoding to a physical circuit; repeat as needed")
    parser.add_argument("--tolerance", type=float, default=1e-10)
    parser.add_argument("--max-dimension", type=int, default=64, help="dense verifier dimension limit (1–64)")
    parser.add_argument("--json", action="store_true", help="emit only canonical search-report JSON v1")
    parser.add_argument("--version", action="version", version=f"q3hash {__version__}")
    args = parser.parse_args(argv)
    try:
        if len(args.seed) > 4096 or len(args.implementation) > 4096:
            raise ValueError("Q3-CLI-001: at most 4096 seeds and 4096 implementation pairs are accepted")
        logical = logical_from_source(_read_input(args.logical))
        constraints = (SearchConstraints() if args.constraints is None else
                       SearchConstraints.from_json(_read_input(args.constraints)))
        seeds = tuple(BasisEncoding.from_json(_read_input(path)) for path in args.seed)
        implementations = tuple(CircuitImplementation(BasisEncoding.from_json(_read_input(encoding_path)),
                                logical_from_source(_read_input(physical_path)).ir)
                                for encoding_path, physical_path in args.implementation)
        generation = generate_encodings(logical.dimensions, constraints, seed_encodings=seeds)
        report = evaluate_candidates(logical, generation, implementations,
                                     tolerance=args.tolerance, max_dimension=args.max_dimension)
        output = report.to_json() if args.json else _summary(report)
    except (OSError, TypeError, ValueError) as error:
        parser.error(str(error))
    sys.stdout.write(output)
    raise SystemExit(_exit_code(report))


if __name__ == "__main__":
    main()
