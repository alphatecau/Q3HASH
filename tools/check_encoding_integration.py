"""Run fixed Q3HASH encoding benchmarks against an independent full-matrix oracle."""

import argparse
from hashlib import sha256
import json
from math import isclose
from pathlib import Path
import sys

from q3hash import BasisEncoding, count_resources, logical_from_source, verify_equivalence
from q3hash.equivalence import operator_matrix

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))  # Keep the independent oracle available in Python isolated mode.
from check_three_way_oracle import compare, independent_resources, matrix_for, parse_program

SUITE = ROOT / "benchmarks/encoding-integration-v1.json"
THREE_WAY = ROOT / "benchmarks/three-way-qutrit-shift-v1.json"
METRICS = ("subspace_residual", "leakage_norm", "logical_unitarity_error", "physical_unitarity_error")


def qutrit_workload():
    """Reuse the pinned three-way circuits and maps without copying them."""
    spec = json.loads(THREE_WAY.read_bytes())
    candidates = []
    for row in spec["cases"]:
        encoding = json.loads((ROOT / row["encoding"]).read_bytes())
        candidates.append(dict(id=row["id"], dimensions=row["dimensions"],
                               source=(ROOT / row["physical_source"]).read_text(encoding="utf-8"),
                               basis_indices=encoding["physical_basis_indices"]))
    for dimensions in spec["expected_unimplemented_dimension_tuples"]:
        candidates.append(dict(id="unimplemented-" + "x".join(map(str, dimensions)), dimensions=dimensions,
                               source=None, basis_indices=None))
    return dict(id="qutrit-shift", logical_source=(ROOT / spec["logical_source"]).read_text(encoding="utf-8"),
                expected_status="partial", candidates=candidates)


def checked_program(source, dense_limit):
    program = logical_from_source(source)
    dimensions, operations = parse_program(source)
    assert program.dimensions == dimensions
    oracle = matrix_for(dimensions, operations)
    assert operator_matrix(program.ir, max_dimension=dense_limit) == oracle
    return program, operations, oracle


def evaluate(logical, logical_matrix, candidate, tolerance, dense_limit):
    dims, indices, source = candidate["dimensions"], candidate["basis_indices"], candidate["source"]
    row = dict(id=candidate["id"], dimensions=dims, basis_indices=indices)
    if source is None:
        assert indices is None
        return dict(row, status="unsupported", reason="no-supplied-circuit", metrics=None, resources=None,
                    physical_source_sha256=None)

    physical, operations, physical_matrix = checked_program(source, dense_limit)
    assert physical.dimensions == tuple(dims)
    encoding = BasisEncoding(logical.dimensions, physical.dimensions, tuple(indices))
    assert BasisEncoding.from_json(encoding.to_json()) == encoding
    result = verify_equivalence(logical, physical.ir, encoding, tolerance=tolerance, max_dimension=dense_limit)
    oracle_metrics = compare(logical_matrix, physical_matrix, tuple(indices))
    metrics = [getattr(result, name) for name in METRICS]
    assert all(isclose(actual, expected, rel_tol=0, abs_tol=1e-13)
               for actual, expected in zip(metrics, oracle_metrics)), candidate["id"]
    expected_status = "pass" if all(metric <= tolerance for metric in oracle_metrics) else "fail"
    assert result.status == expected_status, candidate["id"]
    resources = list(count_resources(physical.ir, logical_size=logical.state_size).as_tuple())
    assert resources == independent_resources(physical.dimensions, operations, logical.state_size), candidate["id"]
    return dict(row, status=result.status, reason=result.reason,
                metrics={name: round(value, 12) for name, value in zip(METRICS, metrics)}, resources=resources,
                physical_source_sha256=sha256(source.encode()).hexdigest())


def aggregate(rows):
    statuses = {row["status"] for row in rows}
    assert statuses and statuses <= {"pass", "fail", "unsupported"}
    if "fail" in statuses:
        return "fail"
    return statuses.pop() if len(statuses) == 1 else "partial"


def run():
    fixture = json.loads(SUITE.read_bytes())
    assert (fixture["schema"], fixture["schema_version"]) == ("q3hash.encoding-integration-benchmarks", 1)
    tolerance, dense_limit = fixture["tolerance"], fixture["dense_limit"]
    workloads, programs = [], {}
    for spec in [*fixture["workloads"], qutrit_workload()]:
        name, source = spec["id"], spec["logical_source"]
        logical, _, matrix = checked_program(source, dense_limit)
        programs[name] = logical, matrix
        rows = [evaluate(logical, matrix, item, tolerance, dense_limit) for item in spec["candidates"]]
        status = aggregate(rows)
        assert status == spec["expected_status"], name
        workloads.append(dict(id=name, status=status, logical_dimensions=list(logical.dimensions),
                              logical_source_sha256=sha256(source.encode()).hexdigest(), candidates=rows))

    controls = []
    for spec in fixture["negative_controls"]:
        logical, matrix = programs[spec["workload"]]
        row = evaluate(logical, matrix, spec, tolerance, dense_limit)
        assert row["status"] == "fail", row["id"]
        controls.append(dict(row, workload=spec["workload"]))
    return dict(schema="q3hash.encoding-integration-report", schema_version=1, tolerance=tolerance,
                dense_limit=dense_limit, basis_order="last-register-fastest", workloads=workloads,
                negative_controls=controls, fixture_sha256={file.name: sha256(file.read_bytes()).hexdigest()
                                                           for file in (SUITE, THREE_WAY)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit a deterministic JSON evidence report")
    args = parser.parse_args()
    report = run()
    if args.json:
        print(json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False))
        return
    for workload in report["workloads"]:
        counts = ", ".join(f"{row['id']}={row['status'].upper()}" for row in workload["candidates"])
        print(f"{workload['id']}: {workload['status'].upper()} ({counts})")
    for row in report["negative_controls"]:
        print(f"Negative control {row['id']}: {row['status'].upper()} as expected")


if __name__ == "__main__":
    main()
