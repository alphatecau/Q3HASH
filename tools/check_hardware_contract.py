"""Tiny v0.5 design oracle; no production hardware API or device measurements."""

from copy import deepcopy
from datetime import datetime, timezone
import itertools
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

from q3hash import BasisEncoding, logical_from_source, verify_equivalence


OBJECTIVES = ("active_sites", "native_operations", "two_site_operations", "critical_path_ps", "serial_duration_ps")
KINDS = ("shift", "fourier", "sum")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def valid(condition, message):
    if not condition:
        raise ValueError("Invalid reference input: " + message)


def instant(value):
    valid(type(value) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value), "UTC timestamp")
    result = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    valid(result.year >= 1970, "timestamp year")
    return result


def bounded_time(value, *, binding=False):
    valid(type(value) is dict and set(value) == {"lower_ps", "upper_ps"}, "time fields")
    lo, hi = value["lower_ps"], value["upper_ps"]
    valid(type(lo) is int and type(hi) is int, "integer picoseconds")
    valid(0 <= lo <= hi <= (1 if binding else 16384) * 10**15, "time range")
    return [lo, hi]


def profile_check(profile):
    """Validate the finite wire fixtures, not a proposed public model constructor."""
    valid(set(profile) == {"schema", "schema_version", "name", "site_dimensions", "couplings", "bindings", "provenance"}, "profile fields")
    valid(profile["schema"] == "q3hash.hardware-profile" and type(profile["schema_version"]) is int and profile["schema_version"] == 1, "profile schema")
    valid(type(profile["name"]) is str and 0 < len(profile["name"]) <= 128, "profile name")
    dimensions = profile["site_dimensions"]
    valid(type(dimensions) is list and 1 <= len(dimensions) <= 64 and all(type(d) is int and 2 <= d <= 32 for d in dimensions), "site dimensions")
    edges = profile["couplings"]
    valid(type(edges) is list and len(edges) <= 4032, "coupling array")
    for edge in edges:
        valid(type(edge) is list and len(edge) == 2 and all(type(i) is int and 0 <= i < len(dimensions) for i in edge) and edge[0] != edge[1], "edge indices")
    valid(edges == sorted(edges) and len(set(map(tuple, edges))) == len(edges), "coupling order/duplicates")
    bindings = profile["bindings"]
    valid(type(bindings) is list and len(bindings) <= 8192, "binding array")
    keys = []
    for binding in bindings:
        valid(type(binding) is dict and set(binding) == {"kind", "sites", "duration", "error"}, "binding fields")
        kind, sites = binding["kind"], binding["sites"]
        valid(type(kind) is str and kind in KINDS, "gate kind")
        valid(type(sites) is list and len(sites) == (2 if kind == "sum" else 1) and
              all(type(i) is int and 0 <= i < len(dimensions) for i in sites) and len(set(sites)) == len(sites), "binding sites")
        valid(kind != "sum" or sites in edges, "binding without edge")
        keys.append((KINDS.index(kind), tuple(sites)))
        if binding["duration"] is not None:
            bounded_time(binding["duration"], binding=True)
        error = binding["error"]
        if error is not None:
            valid(type(error) is dict and set(error) == {"metric", "lower", "upper"}, "error fields")
            valid(error["metric"] in ("average-gate-infidelity", "process-infidelity", "reported-unspecified-error"), "error definition")
            values = (error["lower"], error["upper"])
            valid(all(type(x) in (int, float) and math.isfinite(x) for x in values) and 0 <= values[0] <= values[1] <= 1, "error range")
    valid(keys == sorted(keys) and len(set(keys)) == len(keys), "binding order/duplicates")
    provenance = profile["provenance"]
    valid(set(provenance) == {"kind", "provider", "device_id", "snapshot_id", "source_uri", "retrieved_at", "calibrated_at", "notes"}, "provenance fields")
    valid(provenance["kind"] in ("synthetic", "reported-device"), "provenance kind")
    for name in ("provider", "device_id", "snapshot_id"):
        valid(type(provenance[name]) is str and 0 < len(provenance[name]) <= 128, "provenance identifier")
    valid(type(provenance["notes"]) is str and len(provenance["notes"]) <= 4096, "provenance notes")
    uri = provenance["source_uri"]
    valid(type(uri) is str and 0 < len(uri) <= 2048, "source URI")
    parsed = urlsplit(uri)
    valid((parsed.scheme == "https" and bool(parsed.netloc) and parsed.username is None and parsed.password is None) or
          (provenance["kind"] == "synthetic" and uri.startswith("urn:q3hash:synthetic:") and len(uri) > len("urn:q3hash:synthetic:")), "source URI form")
    retrieved = instant(provenance["retrieved_at"])
    calibrated = provenance["calibrated_at"]
    if provenance["kind"] == "synthetic":
        valid(calibrated is None, "synthetic calibration")
    elif calibrated is not None:
        valid(instant(calibrated) <= retrieved, "calibration after retrieval")


def freshness(profile, as_of, age):
    valid(type(age) is int and 0 <= age <= 31536000, "calibration age")
    at = instant(as_of)
    data = profile["provenance"]
    valid(at >= instant(data["retrieved_at"]), "future snapshot")
    if data["kind"] == "synthetic":
        return "synthetic"
    if data["calibrated_at"] is None:
        return "unknown"
    elapsed = (at - instant(data["calibrated_at"])).total_seconds()
    valid(elapsed >= 0, "future calibration")
    return "fresh" if elapsed <= age else "stale"


def path_timing(operations):
    """Enumerate all tiny dependency paths, unlike planned per-site DP."""
    valid(len(operations) <= 8, "reference timing domain is at most eight gates")
    if any(op["duration_ps"] is None for op in operations):
        return None, None
    touched = [set(op["sites"]) for op in operations]
    parents = [[j for j in range(i) if touched[i] & touched[j]] for i in range(len(operations))]
    paths = []
    for i, preceding in enumerate(parents):
        paths.append([(i,)] if not preceding else [(*path, i) for j in preceding for path in paths[j]])
    critical = [max((sum(operations[i]["duration_ps"][endpoint] for i in path)
                     for values in paths for path in values), default=0) for endpoint in (0, 1)]
    serial = [sum(op["duration_ps"][endpoint] for op in operations) for endpoint in (0, 1)]
    return critical, serial


def target_reference(ir, profile, sites, context):
    valid(type(sites) is list and len(sites) == len(ir.dimensions) and
          all(type(i) is int and 0 <= i < len(profile["site_dimensions"]) for i in sites) and
          len(set(sites)) == len(sites), "placement")
    mismatch = [axis for axis, site in enumerate(sites) if ir.dimensions[axis] != profile["site_dimensions"][site]]
    if mismatch:
        return dict(status="unsupported", rejections=["site-dimension"] * len(mismatch), gate_checks=0,
                    expected_time_ps=None, timing_reason=None, expected_counts=None)
    edges = {tuple(edge) for edge in profile["couplings"]}
    bindings = {(entry["kind"], tuple(entry["sites"])): entry for entry in profile["bindings"]}
    rejections, used, operations = [], {}, []
    for operation in ir.operations:
        kind = operation.kind.value
        qargs = (sites[operation.target],) if operation.control is None else (sites[operation.control], sites[operation.target])
        if kind == "sum" and qargs not in edges:
            rejections.append("directed-coupling")
        elif (kind, qargs) not in bindings:
            rejections.append("native-gate")
        else:
            binding = bindings[kind, qargs]
            used[kind, qargs] = used.get((kind, qargs), 0) + 1
            operations.append(dict(sites=qargs, duration_ps=None if binding["duration"] is None else bounded_time(binding["duration"], binding=True)))
    if rejections:
        return dict(status="unsupported", rejections=rejections, gate_checks=len(ir.operations),
                    expected_time_ps=None, timing_reason=None, expected_counts=None)
    state = freshness(profile, context["as_of"], context["max_calibration_age_seconds"])
    critical, serial = path_timing(operations)
    reason = "model-range"
    if not operations:
        reason = "empty-circuit"
    elif state in ("stale", "unknown"):
        critical = serial = None
        reason = state + "-calibration"
    elif critical is None:
        reason = "missing-duration"
    # Error entries are retained separately, including unknowns. No arithmetic
    # on gate errors purports to estimate circuit failure or success.
    errors = [dict(kind=b["kind"], sites=b["sites"], occurrences=used[(b["kind"], tuple(b["sites"]))], error=b["error"])
              for b in profile["bindings"] if (b["kind"], tuple(b["sites"])) in used]
    return dict(status="supported", rejections=[], gate_checks=len(ir.operations), expected_time_ps=critical,
                timing_reason=reason, expected_counts=[len(sites), len(ir.operations), sum(op.control is not None for op in ir.operations)],
                serial_duration_ps=serial, used_errors=errors, circuit_error=None, circuit_error_reason="no-noise-composition-model")


def dominates(left, right, objectives):
    return (all(left[key][1] <= right[key][0] for key in objectives) and
            any(left[key][1] < right[key][0] for key in objectives))


def front(rows, objectives):
    valid(bool(objectives) and len(set(objectives)) == len(objectives) and all(key in OBJECTIVES for key in objectives), "objectives")
    valid(not rows or len({row["group"] for row in rows}) == 1, "comparison group")
    eligible = [i for i, row in enumerate(rows) if row["eligible"] and all(row["values"][key] is not None for key in objectives)]
    return [i for i in eligible if not any(dominates(rows[j]["values"], rows[i]["values"], objectives) for j in eligible)]


def budget_reference(rows, limit):
    remaining = limit
    outcomes = []
    for row in rows:
        if row["source_status"] != "pass":
            status = "ineligible"
        elif not row["placed"]:
            status = "unplaced"
        elif not row["dimensions_match"]:
            status = "unsupported"
        elif row["operations"] > remaining:
            status = "not-evaluated"
        else:
            remaining -= row["operations"]
            status = "supported" if row["supported"] else "unsupported"
        outcomes.append(status)
    return outcomes, limit - remaining


def rejected(call):
    try:
        call()
    except (TypeError, ValueError):
        return
    raise AssertionError("Invalid vector unexpectedly accepted by reference preflight")


def audit():
    path = Path(__file__).resolve().parents[1] / "benchmarks/hardware-cost-v1.json"
    require(path.stat().st_size <= 1048576, "Fixture exceeds the wire budget")
    fixture = json.loads(path.read_text(encoding="utf-8"))
    require(fixture["schema"] == "q3hash.hardware-contract-vectors" and fixture["schema_version"] == 1 and
            fixture["evidence_scope"] == "synthetic-contract-fixtures-no-device-data", "Unexpected fixture scope")
    stats = dict(operator_workloads=0, target_cases=0, timing_cases=0, freshness_cases=0, front_cases=0,
                 budget_cases=0, interval_pairs=0, invalid_inputs=0, profile_fixtures=0)
    for profile in fixture["profiles"].values():
        profile_check(profile)
        stats["profile_fixtures"] += 1
    programs = {}
    for case in fixture["workloads"]:
        logical = logical_from_source(case["logical"])
        if case["physical"] is None:
            require(case["expected"] == "unimplemented" and case["mapping"] is None, "Missing implementation must remain missing")
        else:
            physical = logical_from_source(case["physical"])
            encoding = BasisEncoding(logical.dimensions, physical.dimensions, tuple(case["mapping"]))
            report = verify_equivalence(logical, physical.ir, encoding, max_dimension=case["max_dimension"])
            require(report.status == case["expected"], case["id"] + ": operator status")
            programs[case["id"]] = (physical.ir, report.status)
        stats["operator_workloads"] += 1
    for case in fixture["target_cases"]:
        ir, status = programs[case["workload"]]
        require(status == "pass", "Target vectors must use verified supplied circuits")
        actual = target_reference(ir, fixture["profiles"][case["profile"]], case["site_indices"], fixture["context"])
        for key in ("status", "rejections", "gate_checks", "expected_time_ps", "timing_reason", "expected_counts"):
            require(actual[key] == case[key], case["id"] + ": " + key)
        if actual["status"] == "supported":
            require(actual["circuit_error"] is None and actual["circuit_error_reason"] == "no-noise-composition-model", "Circuit error cannot be fabricated")
            require(sum(item["occurrences"] for item in actual["used_errors"]) == len(ir.operations), "Used error accounting")
        stats["target_cases"] += 1
    for case in fixture["timing_cases"]:
        require(path_timing(case["operations"]) == (case["critical"], case["serial"]), case["id"] + ": path timing")
        stats["timing_cases"] += 1
    for case in fixture["freshness_cases"]:
        operation = lambda: freshness(fixture["profiles"][case["profile"]], case["as_of"], case["max_age"])
        if case["expected"] == "invalid":
            rejected(operation)
        else:
            require(operation() == case["expected"], case["id"] + ": freshness")
        stats["freshness_cases"] += 1
    for case in fixture["front_cases"]:
        operation = lambda: front(case["rows"], case["objectives"])
        if case["invalid"]:
            rejected(operation)
        else:
            require(operation() == case["front_indices"], case["id"] + ": interval front")
        stats["front_cases"] += 1
    for case in fixture["budget_cases"]:
        require(budget_reference(case["rows"], case["limit"]) == (case["statuses"], case["gate_checks"]), case["id"] + ": gate-check ledger")
        stats["budget_cases"] += 1
    intervals = [(lo, hi) for lo in range(5) for hi in range(lo, 5)]
    vectors = [dict(active_sites=(count, count), critical_path_ps=interval) for count in (1, 2) for interval in intervals]
    for left, right in itertools.product(vectors, repeat=2):
        # Exhaust all integer realisations, independent of endpoint comparison.
        all_pairs = [(a, b) for a in range(left["critical_path_ps"][0], left["critical_path_ps"][1] + 1)
                     for b in range(right["critical_path_ps"][0], right["critical_path_ps"][1] + 1)]
        x, y = left["active_sites"][0], right["active_sites"][0]
        expected = all(x <= y and a <= b and (x < y or a < b) for a, b in all_pairs)
        require(dominates(left, right, ("active_sites", "critical_path_ps")) == expected, "Endpoint rule disagrees with exhaustive realisations")
        stats["interval_pairs"] += 1
    mutations = [
        lambda p: p["site_dimensions"].__setitem__(0, True),
        lambda p: p["bindings"][0]["duration"].update(lower_ps=True),
        lambda p: p["bindings"][0]["duration"].update(upper_ps=60000.0),
        lambda p: p["bindings"][0]["duration"].update(lower_ps=-1),
        lambda p: p["bindings"][0]["duration"].update(upper_ps=10**15 + 1),
        lambda p: p["bindings"][0]["error"].update(metric="success-probability"),
        lambda p: p["bindings"][0]["error"].update(upper=1.1),
        lambda p: p["bindings"][0]["error"].update(lower=True),
        lambda p: p["bindings"].append(deepcopy(p["bindings"][0])),
        lambda p: p["couplings"].reverse(),
        lambda p: p["couplings"].remove([0, 3]),
        lambda p: p["provenance"].update(retrieved_at="2026-11-01T00:00:00+00:00"),
    ]
    for mutation in mutations:
        value = deepcopy(fixture["profiles"]["hybrid"])
        mutation(value)
        rejected(lambda: profile_check(value))
        stats["invalid_inputs"] += 1
    rejected(lambda: front(fixture["front_cases"][0]["rows"], ["circuit_error"]))
    stats["invalid_inputs"] += 1
    return stats


def main():
    print("v0.5 hardware contract reference audit:", json.dumps(audit(), sort_keys=True))
    print("Design vectors only: synthetic target data, existing software verification and tiny mathematical oracles.")
    print("Inputs, costs, verified reports/fronts/replay and Cirq have separate checks; the hardware CLI remains pending.")


if __name__ == "__main__":
    main()
