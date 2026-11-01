"""Independent tiny path/ledger audit of the internal hardware-cost kernel."""

from dataclasses import replace
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path

from q3hash import (BasisEncoding, CircuitIR, GateKind, HardwareContext, HardwarePlacement,
                    HardwareProfile, NativeBinding, Operation, ProfileProvenance, Register,
                    TimeRange, __version__, logical_from_source, verify_equivalence)
from q3hash.hardware_costs import _CostInput, _evaluate_costs, _freshness


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def key(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def time_pair(value):
    return None if value is None else [value.lower_ps, value.upper_ps]


def request(index, circuit, sites, status="pass"):
    candidate_id = key(index)
    return _CostInput(candidate_id, status, circuit,
                      None if sites is None else HardwarePlacement(candidate_id, tuple(sites)))


def make_profile(dimensions, bindings, name="cost-audit"):
    kinds = ("shift", "fourier", "sum")
    bindings = tuple(sorted(bindings, key=lambda b: (kinds.index(b.kind.value), b.sites)))
    edges = tuple(sorted(b.sites for b in bindings if b.kind is GateKind.SUM))
    return HardwareProfile(name, dimensions, edges, bindings,
        ProfileProvenance("synthetic", "Q3# audit", name, "v1", "urn:q3hash:synthetic:" + name,
                          "2026-11-01T00:00:00Z", None, "Synthetic mathematical cases; no device data."))


def rejection_oracle(circuit, profile, sites):
    """Enumerate raw tensor-site labels independently of the kernel's lookup."""
    mismatches = [dict(code="site-dimension", operation_index=None, axis_index=i, sites=[site])
                  for i, site in enumerate(sites) if circuit.dimensions[i] != profile["site_dimensions"][site]]
    if mismatches:
        return mismatches
    available = [(b["kind"], b["sites"]) for b in profile["bindings"]]
    results = []
    for index, gate in enumerate(circuit.operations):
        operands = [sites[gate.target]] if gate.control is None else [sites[gate.control], sites[gate.target]]
        reason = None
        if gate.control is not None and operands not in profile["couplings"]:
            reason = "directed-coupling"
        elif (gate.kind.value, operands) not in available:
            reason = "native-gate"
        if reason:
            results.append(dict(code=reason, operation_index=index, axis_index=None, sites=operands))
    return results


def compare(row, expected, circuit, profile, sites):
    require(row.status == expected["status"] and row.gate_checks == expected["gate_checks"], "Status/work disagreement")
    require([r.code for r in row.rejections] == expected["rejections"], "Rejection code disagreement")
    actual_rejections = [dict(code=r.code, operation_index=r.operation_index, axis_index=r.axis_index, sites=list(r.sites))
                         for r in row.rejections]
    require(actual_rejections == rejection_oracle(circuit, profile, sites), "Detailed rejection disagreement")
    if expected["status"] != "supported":
        require(row.costs is None, "Unsupported circuit acquired costs")
        return
    costs = row.costs
    require([costs.active_sites, costs.native_operations, costs.two_site_operations] == expected["expected_counts"],
            "Native count disagreement")
    require(time_pair(costs.critical_path_ps) == expected["expected_time_ps"] and
            time_pair(costs.serial_duration_ps) == expected["serial_duration_ps"], "Timing disagreement")
    require(costs.timing_reason == expected["timing_reason"], "Timing reason disagreement")
    errors = [dict(kind=e.kind.value, sites=list(e.sites), occurrences=e.occurrences,
                   error=None if e.error is None else e.error.to_dict()) for e in costs.used_errors]
    require(errors == expected["used_errors"], "Error records changed or were reordered")
    require(costs.circuit_error is None and costs.circuit_error_reason == "no-noise-composition-model",
            "Circuit error cannot be inferred from gate infidelities")


def fixed_timing_input(operations):
    """Represent the fixed path cases with distinct available IR gate bindings."""
    count = 1 + max((site for op in operations for site in op["sites"]), default=0)
    bindings, gates = {}, []
    for entry in operations:
        sites = tuple(entry["sites"])
        duration = None if entry["duration_ps"] is None else TimeRange(*entry["duration_ps"])
        choices = (GateKind.SUM,) if len(sites) == 2 else (GateKind.SHIFT, GateKind.FOURIER)
        for kind in choices:
            existing = bindings.get((kind, sites))
            if existing is None or existing.duration == duration:
                bindings[kind, sites] = NativeBinding(kind, sites, duration, None)
                gates.append(Operation(kind, sites[-1], sites[0] if len(sites) == 2 else None))
                break
        else:
            raise AssertionError("Fixed path requires a new gate-duration contract")
    circuit = CircuitIR(tuple(Register(f"q{i}", 3) for i in range(count)), tuple(gates))
    return circuit, make_profile((3,) * count, tuple(bindings.values()))


def budget_inputs(rows):
    values = []
    for index, row in enumerate(rows):
        status = row["source_status"]
        count = row["operations"]
        if status == "unimplemented":
            circuit = None
        else:
            gates = (Operation(GateKind.SHIFT, 0),) * count
            if not row["supported"]:
                require(count > 0, "An empty circuit cannot lack native gates")
                gates = (Operation(GateKind.FOURIER, 0), *gates[1:])
            circuit = CircuitIR((Register("q", 3 if row["dimensions_match"] else 2),), gates)
        values.append(request(index, circuit, (0,) if row["placed"] else None, status))
    return tuple(values)


def audit():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("q3hash_hardware_design_oracle", root / "tools/check_hardware_contract.py")
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    raw = (root / "benchmarks/hardware-cost-v1.json").read_bytes()
    fixture = json.loads(raw)
    stats = dict(frozen_workloads=0, frozen_targets=0, frozen_timing_dags=0, freshness_cases=0,
                 exhaustive_timing_circuits=0, exhaustive_feasibility_circuits=0,
                 fixed_budget_ledgers=0, exhaustive_budget_ledgers=0)
    context = HardwareContext.from_dict(fixture["context"])
    programs = {}
    for row in fixture["workloads"]:
        if row["physical"] is not None:
            logical, physical = logical_from_source(row["logical"]), logical_from_source(row["physical"])
            encoding = BasisEncoding(logical.dimensions, physical.dimensions, tuple(row["mapping"]))
            verified = verify_equivalence(logical, physical.ir, encoding, max_dimension=row["max_dimension"])
            require(verified.status == row["expected"], row["id"] + ": source evidence changed")
            programs[row["id"]] = physical.ir, verified.status
        else:
            require(row["expected"] == "unimplemented", "Missing source implementation changed")
        stats["frozen_workloads"] += 1
    for row in fixture["target_cases"]:
        circuit, status = programs[row["workload"]]
        require(status == "pass", "Fixed target requires an actually passing source")
        raw_profile = fixture["profiles"][row["profile"]]
        target = HardwareProfile.from_dict(raw_profile)
        expected = oracle.target_reference(circuit, raw_profile, row["site_indices"], fixture["context"])
        for name in ("status", "rejections", "gate_checks", "expected_time_ps", "timing_reason", "expected_counts"):
            require(expected[name] == row[name], row["id"] + ": reference disagrees with frozen vector")
        result = _evaluate_costs((request(0, circuit, row["site_indices"]),), target, context)
        compare(result.evaluations[0], expected, circuit, raw_profile, row["site_indices"])
        require(result.gate_checks == expected["gate_checks"], "Fixed batch ledger mismatch")
        stats["frozen_targets"] += 1
    for row in fixture["timing_cases"]:
        circuit, target = fixed_timing_input(row["operations"])
        expected = oracle.path_timing(row["operations"])
        require(expected == (row["critical"], row["serial"]), row["id"] + ": frozen timing disagreement")
        actual = _evaluate_costs((request(0, circuit, tuple(range(len(circuit.registers)))),), target, context)
        costs = actual.evaluations[0].costs
        require((time_pair(costs.critical_path_ps), time_pair(costs.serial_duration_ps)) == expected,
                row["id"] + ": production timing mismatch")
        stats["frozen_timing_dags"] += 1
    for row in fixture["freshness_cases"]:
        target = HardwareProfile.from_dict(fixture["profiles"][row["profile"]])
        selected = replace(context, as_of=row["as_of"], max_calibration_age_seconds=row["max_age"])
        if row["expected"] == "invalid":
            oracle.rejected(lambda: _freshness(target, selected))
        else:
            require(_freshness(target, selected) == row["expected"] ==
                    oracle.freshness(fixture["profiles"][row["profile"]], row["as_of"], row["max_age"]), "Freshness disagreement")
        stats["freshness_cases"] += 1

    dimensions = (2, 3, 2)
    sites = ((0,), (1,), (2,), (0, 1), (1, 2), (2, 0))
    kinds = (GateKind.SHIFT,) * 3 + (GateKind.SUM,) * 3
    sequences = tuple(sequence for length in range(5) for sequence in itertools.product(range(6), repeat=length))
    circuits = tuple(CircuitIR(tuple(Register(f"q{i}", d) for i, d in enumerate(dimensions)),
                    tuple(Operation(kinds[i], sites[i][-1], sites[i][0] if len(sites[i]) == 2 else None) for i in sequence))
                     for sequence in sequences)
    # These abstract flags exercise arithmetic only; they are private kernel
    # inputs, not newly generated public verification evidence.
    for missing in (False, True):
        durations = ((0, 0), (2, 4), None if missing else (10**15 - 1, 10**15), (5, 8), (3, 3), (1, 7))
        target = make_profile(dimensions, tuple(NativeBinding(kind, axes, None if duration is None else TimeRange(*duration), None)
                              for kind, axes, duration in zip(kinds, sites, durations)))
        inputs = tuple(request(i, circuit, (0, 1, 2)) for i, circuit in enumerate(circuits))
        result = _evaluate_costs(inputs, target, context)
        for sequence, row in zip(sequences, result.evaluations):
            operations = [dict(sites=list(sites[i]), duration_ps=durations[i]) for i in sequence]
            expected = oracle.path_timing(operations)
            require(row.status == "supported", "Available abstract circuit rejected")
            require((time_pair(row.costs.critical_path_ps), time_pair(row.costs.serial_duration_ps)) == expected,
                    "Exhaustive path enumeration disagrees with per-site fold")
            stats["exhaustive_timing_circuits"] += 1
        require(result.gate_checks == sum(map(len, sequences)), "Exhaustive timing ledger mismatch")

    short_sequences = tuple(sequence for length in range(3) for sequence in itertools.product(range(6), repeat=length))
    short_circuits = circuits[:len(short_sequences)]
    for mask in range(64):
        available = tuple(NativeBinding(kinds[i], sites[i], TimeRange(i, i + 2), None)
                          for i in range(6) if mask & (1 << i))
        target = make_profile(dimensions, available, "subset-" + str(mask))
        raw_profile = target.to_dict()
        result = _evaluate_costs(tuple(request(i, c, (0, 1, 2)) for i, c in enumerate(short_circuits)), target, context)
        for circuit, row in zip(short_circuits, result.evaluations):
            expected = oracle.target_reference(circuit, raw_profile, [0, 1, 2], fixture["context"])
            compare(row, expected, circuit, raw_profile, [0, 1, 2])
            stats["exhaustive_feasibility_circuits"] += 1
        require(result.gate_checks == sum(len(c.operations) for c in short_circuits), "Rejected operations escaped charging")

    target = make_profile((3,), (NativeBinding(GateKind.SHIFT, (0,), TimeRange(2, 4), None),))
    for row in fixture["budget_cases"]:
        expected = oracle.budget_reference(row["rows"], row["limit"])
        require(expected == (row["statuses"], row["gate_checks"]), "Frozen budget oracle changed")
        result = _evaluate_costs(budget_inputs(row["rows"]), target, replace(context, max_gate_checks=row["limit"]))
        require(([r.status for r in result.evaluations], result.gate_checks) == expected, row["id"] + ": budget mismatch")
        stats["fixed_budget_ledgers"] += 1
    patterns = [
        dict(source_status="pass", placed=True, dimensions_match=True, operations=n, supported=True) for n in (0, 1, 3)
    ] + [
        dict(source_status="pass", placed=True, dimensions_match=True, operations=2, supported=False),
        dict(source_status="pass", placed=True, dimensions_match=False, operations=3, supported=True),
        dict(source_status="pass", placed=False, dimensions_match=True, operations=3, supported=True),
        *[dict(source_status=s, placed=True, dimensions_match=True, operations=3, supported=True)
          for s in ("fail", "unsupported", "not-evaluated")],
        dict(source_status="unimplemented", placed=False, dimensions_match=True, operations=0, supported=True),
    ]
    for rows in itertools.product(patterns, repeat=3):
        inputs = budget_inputs(rows)
        for limit in (1, 2, 3, 4, 6):
            expected = oracle.budget_reference(rows, limit)
            result = _evaluate_costs(inputs, target, replace(context, max_gate_checks=limit))
            require(([r.status for r in result.evaluations], result.gate_checks) == expected, "Cumulative/remaining ledger mismatch")
            require(sum(r.gate_checks for r in result.evaluations) == result.gate_checks <= limit, "Work accounting mismatch")
            stats["exhaustive_budget_ledgers"] += 1
    return dict(result="passed", q3hash=__version__, coverage=stats, fixture_sha256=hashlib.sha256(raw).hexdigest(),
                evidence_scope="Internal model arithmetic against synthetic paths/ledgers; public verified reports and hardware execution remain pending")


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, sort_keys=True, allow_nan=False))
