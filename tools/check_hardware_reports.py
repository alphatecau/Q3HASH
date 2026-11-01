"""Independent public-report/front/replay audit with synthetic target profiles."""

from dataclasses import replace
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
from types import SimpleNamespace

from q3hash import (BasisEncoding, CircuitImplementation, HardwareContext, HardwarePlacement,
                    HardwareProfile, HardwareReport, SearchConstraints, assess_hardware,
                    TimeRange, evaluate_candidates, generate_encodings, logical_from_source, __version__)
from q3hash.hardware_report import _interval_front


def require(condition, detail):
    if not condition:
        raise AssertionError(detail)


def audit():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("hardware_report_design_oracle", root / "tools/check_hardware_contract.py")
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    raw = (root / "benchmarks/hardware-cost-v1.json").read_bytes()
    fixture = json.loads(raw)
    logical = logical_from_source("qutrit q\nshift q")
    generation = generate_encodings((3,), SearchConstraints(max_registers=2, max_physical_size=4),
                                    seed_encodings=(BasisEncoding((3,), (3,), (1, 2, 0)),))
    binary = logical_from_source("qubit a\nqubit b\nsum a b\nsum b a\nshift b")
    source = evaluate_candidates(logical, generation, tuple(CircuitImplementation(c.encoding,
        logical.ir if c.encoding.physical_dimensions == (3,) else binary.ir) for c in generation.candidates))
    require(len(source.evaluations) == 3 and all(row.status == "pass" for row in source.evaluations), "Frozen source domain")
    names = ("active_sites", "native_operations", "two_site_operations", "critical_path_ps", "serial_duration_ps")
    subsets = tuple(values for length in range(1, 6) for values in itertools.combinations(names, length))
    stats = dict(actual_reports=0, recorded_replays=0, objective_subsets=len(subsets),
                 source_verifications=source.verification_calls, abstract_front_cases=0, interval_pairs=0)
    def abstract_rows(rows):
        result = []
        for index, row in enumerate(rows):
            values = {name: None for name in names}
            for name, value in row["values"].items():
                if value is not None:
                    values[name] = TimeRange(*value) if name.endswith("_ps") else value[0]
            result.append(SimpleNamespace(status="supported" if row["eligible"] else "ineligible",
                                          placement_id=str(index), costs=SimpleNamespace(**values)))
        return tuple(result)
    for case in fixture["front_cases"]:
        if not case["invalid"]:
            expected = oracle.front(case["rows"], case["objectives"])
            require(_interval_front(abstract_rows(case["rows"]), case["objectives"]) == tuple(map(str, expected)),
                    "Frozen abstract interval front mismatch")
            stats["abstract_front_cases"] += 1
    intervals = [(lo, hi) for lo in range(5) for hi in range(lo, 5)]
    vectors = [dict(active_sites=[count, count], critical_path_ps=interval) for count in (1, 2) for interval in intervals]
    for left, right in itertools.product(vectors, repeat=2):
        rows = [dict(group="one-profile", eligible=True, values=vector) for vector in (left, right)]
        objectives = ("active_sites", "critical_path_ps")
        require(_interval_front(abstract_rows(rows), objectives) == tuple(map(str, oracle.front(rows, objectives))),
                "Exhaustive interval pair disagrees with independent front")
        stats["interval_pairs"] += 1
    for profile_name, limit, coverage, objectives in itertools.product(
            ("hybrid", "one-way", "missing-used", "reported-stale"), (1, 3, 5), ("all", "omit-first", "none"), subsets):
        raw_profile = fixture["profiles"][profile_name]
        profile = HardwareProfile.from_dict(raw_profile)
        context = replace(HardwareContext.from_dict(fixture["context"]), max_gate_checks=limit, objectives=objectives)
        placements, requests, expected_rows, abstract = [], [], [], []
        for index, row in enumerate(source.evaluations):
            placed = coverage == "all" or (coverage == "omit-first" and index != 0)
            sites = ([0] if index == 0 else [3]) if row.candidate.encoding.physical_dimensions == (3,) else [1, 2]
            if placed:
                placements.append(HardwarePlacement(row.candidate_id, tuple(sites)))
            expected = oracle.target_reference(row.implementation.circuit, raw_profile, sites, context.to_dict())
            expected_rows.append(expected)
            requests.append(sites if placed else None)
            abstract.append(dict(source_status=row.status, placed=placed, dimensions_match=True,
                                 operations=len(row.implementation.circuit.operations), supported=expected["status"] == "supported"))
        expected_statuses, expected_checks = oracle.budget_reference(abstract, limit)
        report = assess_hardware(source, profile, tuple(reversed(placements)), context)
        require([row.status for row in report.evaluations] == expected_statuses and report.gate_checks == expected_checks,
                "Public coverage/work differs from independent ledger")
        front_rows = []
        expected_partial = False
        for index, (row, expected, status) in enumerate(zip(report.evaluations, expected_rows, expected_statuses)):
            values = {name: None for name in names}
            if status == "supported":
                a, n, two = expected["expected_counts"]
                values.update(active_sites=(a, a), native_operations=(n, n), two_site_operations=(two, two),
                              critical_path_ps=expected["expected_time_ps"], serial_duration_ps=expected["serial_duration_ps"])
                require([row.costs.active_sites, row.costs.native_operations, row.costs.two_site_operations] == [a, n, two],
                        "Public count mismatch")
                for key in ("critical_path_ps", "serial_duration_ps"):
                    actual = getattr(row.costs, key)
                    require((None if actual is None else [actual.lower_ps, actual.upper_ps]) == values[key], "Public duration mismatch")
                require(row.costs.timing_reason == expected["timing_reason"] and row.costs.circuit_error is None, "Unknown/error policy")
            else:
                require(row.costs is None, "Ineligible row acquired costs")
            expected_partial |= status in ("unplaced", "not-evaluated") or (
                status == "supported" and any(values[name] is None for name in objectives))
            if requests[index] is None:
                require(row.placement_id is None, "Unplaced row acquired an identity")
            else:
                physical_id = hashlib.sha256(row_source_json(source.evaluations[index]).encode()).hexdigest()
                identity = dict(schema="q3hash.hardware-placement-key", schema_version=1, profile_id=profile.profile_id,
                                candidate_id=row.candidate_id, physical_id=physical_id, site_indices=requests[index])
                expected_id = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                require(row.placement_id == expected_id, "Placement key mismatch")
            front_rows.append(dict(group=profile.profile_id, eligible=status == "supported", values=values))
        expected_front = oracle.front(front_rows, objectives)
        require(report.front_ids == tuple(report.evaluations[i].placement_id for i in expected_front), "Public interval front mismatch")
        require(report.front_is_partial == expected_partial, "Partial-coverage flag mismatch")
        before = source.to_json()
        text = report.to_json()
        replay = HardwareReport.from_json(text)
        require(replay == report and replay.to_json() == text and replay.evidence_origin == "recorded" and
                replay.source_report.evidence_origin == "recorded", "Recorded replay mismatch")
        require(source.to_json() == before and source.evidence_origin == "computed", "Source evidence mutated")
        require(assess_hardware(source, profile, tuple(placements), context).to_json() == text, "Canonical repeat mismatch")
        stats["actual_reports"] += 1
        stats["recorded_replays"] += 1
    return dict(result="passed", q3hash=__version__, coverage=stats, fixture_sha256=hashlib.sha256(raw).hexdigest(),
                evidence_scope="Verified supplied circuits under synthetic profiles; recorded replay is not fresh numerical evidence")


def row_source_json(row):
    from q3hash import LogicalProgram
    return LogicalProgram(row.implementation.circuit).to_json()


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, sort_keys=True, allow_nan=False))
