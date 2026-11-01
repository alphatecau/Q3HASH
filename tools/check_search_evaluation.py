"""Independent remaining-budget ledger and all-pairs front audit of actual runs."""

from dataclasses import replace
import itertools
import json

from q3hash import (BasisEncoding, CircuitImplementation, SearchConstraints, SearchReport,
                    evaluate_candidates, generate_encodings, logical_from_source)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def structural(ir, logical_size):
    # All-predecessor DAG, independent of production's per-axis resource counter.
    layers = []
    touched = []
    for operation in ir.operations:
        axes = {operation.target} | (set() if operation.control is None else {operation.control})
        layers.append(1 + max((layer for used, layer in zip(touched, layers) if axes & used), default=0))
        touched.append(axes)
    capacity = len(list(itertools.product(*(range(d) for d in ir.dimensions))))
    return dict(zip(("physical_registers", "max_register_dimension", "unused_basis_states", "gate_count",
                     "two_register_gate_count", "dependency_depth"),
                    (len(ir.dimensions), max(ir.dimensions), capacity - logical_size, len(ir.operations),
                     sum(len(axes) == 2 for axes in touched), max(layers, default=0))))


def oracle(logical, candidates, bindings, outcomes, constraints, dense_limit):
    calls_left = constraints.max_verifications
    steps_left = constraints.max_gate_column_steps
    expected = []
    for candidate in candidates:
        encoding = candidate.encoding
        circuit = bindings.get(encoding)
        if circuit is None:
            expected.append(("unimplemented", "no-implementation", None))
            continue
        if max(len(logical.ir.operations), len(circuit.operations)) > constraints.max_operations_per_program:
            expected.append(("unsupported", "operation-limit", None))
            continue
        if circuit.state_size > dense_limit:
            expected.append(("unsupported", "dense-limit", None))
            continue
        # Count explicit (program, input basis column, gate) events instead of
        # using the production arithmetic/work helper.
        events = [(program_index, column, gate) for program_index, program in enumerate((logical.ir, circuit))
                  for column in itertools.product(*(range(d) for d in program.dimensions))
                  for gate in range(len(program.operations))]
        if not calls_left:
            expected.append(("not-evaluated", "verification-call-budget", None))
        elif len(events) > steps_left:
            expected.append(("not-evaluated", "gate-column-budget", None))
        else:
            calls_left -= 1
            steps_left -= len(events)
            status = outcomes[encoding]
            expected.append((status, "verified" if status == "pass" else "equivalence-failed",
                             structural(circuit, logical.state_size) if status == "pass" else None))
    passing = [(candidate.candidate_id, row[2]) for candidate, row in zip(candidates, expected) if row[0] == "pass"]
    front = tuple(identifier for identifier, vector in passing if not any(
        all(other[name] <= vector[name] for name in constraints.objectives) and
        any(other[name] < vector[name] for name in constraints.objectives) for _, other in passing))
    return expected, constraints.max_verifications - calls_left, constraints.max_gate_column_steps - steps_left, front


def audit():
    logical = logical_from_source("qutrit q\nshift q")
    binary = logical_from_source("qubit a\nqubit b\nsum a b\nsum b a\nshift b").ir
    seeds = (BasisEncoding((3,), (2, 2), (0, 1, 2)), BasisEncoding((3,), (3,), (1, 2, 0)),
             BasisEncoding((3,), (4,), (0, 1, 2)), BasisEncoding((3,), (2, 2), (1, 2, 0)))
    native = BasisEncoding((3,), (3,), (0, 1, 2))
    circuits = dict(zip(seeds, (binary, logical.ir, logical_from_source("qudit 4 p\nshift p").ir,
                                logical_from_source("qubit a\nqubit b\nsum a b\nsum b a\nshift b\nshift a\nshift a").ir)))
    outcomes = dict(zip(seeds, ("pass", "pass", "fail", "pass")))
    outcomes[native] = "pass"
    base = SearchConstraints(allowed_dimensions=(2, 3, 4), max_registers=2, max_physical_size=4)
    stats = {"budgeted_runs": 0, "snapshot_replays": 0, "verified_circuits": 0}
    settings = itertools.product((1, 2, 5), (1, 6, 7, 15, 21, 100), (1, 3, 5), (2, 3, 4), (False, True))
    for call_limit, step_limit, operation_limit, dense_limit, supply_native in settings:
        bindings = {**circuits, **({native: logical.ir} if supply_native else {})}
        constraints = replace(base, max_verifications=call_limit, max_gate_column_steps=step_limit,
                              max_operations_per_program=operation_limit,
                              objectives=("gate_count",) if supply_native else base.objectives)
        generation = generate_encodings((3,), constraints, seed_encodings=seeds)
        require(len(generation.candidates) == 5, "Audit fixture candidate coverage changed")
        implementations = tuple(CircuitImplementation(encoding, circuit) for encoding, circuit in reversed(tuple(bindings.items())))
        report = evaluate_candidates(logical, generation, implementations, max_dimension=dense_limit)
        rows, calls, steps, front = oracle(logical, generation.candidates, bindings, outcomes, constraints, dense_limit)
        actual = [(row.status, row.reason_code, None if row.resources is None else row.resources.to_dict())
                  for row in report.evaluations]
        require(actual == rows, f"Candidate state/resource mismatch for {constraints}, dense {dense_limit}")
        require((report.verification_calls, report.gate_column_steps, report.front_ids) == (calls, steps, front),
                "Aggregate ledger or all-pairs front mismatch")
        require(report.status_counts == {name: sum(row[0] == name for row in rows) for name in report.status_counts},
                "Status-count mismatch")
        decoded = SearchReport.from_json(report.to_json())
        require(decoded == report and decoded.evidence_origin == "recorded", "Snapshot replay mismatch")
        require(decoded.to_json() == report.to_json(), "Snapshot canonical bytes changed")
        stats["budgeted_runs"] += 1
        stats["snapshot_replays"] += 1
        stats["verified_circuits"] += calls
    return stats


def main():
    print("Independent aggregate evaluation audit:", json.dumps(audit(), sort_keys=True))
    print("Evidence: bounded supplied-circuit calls, complete status coverage and recorded snapshots; no hardware execution.")


if __name__ == "__main__":
    main()
