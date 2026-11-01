"""Independent dependency-DAG counts and all-pairs integer Pareto audit."""

import itertools
import json
from pathlib import Path

from q3hash import (BasisEncoding, CircuitIR, CircuitImplementation, EncodingCandidate,
                    GateKind, Operation, Register, RESOURCE_OBJECTIVES, ResourceCounts,
                    count_resources, dominates, evaluate_candidate, logical_from_source, pareto_front)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def oracle_counts(ir, logical_size):
    labels = list(itertools.product(*(range(register.dimension) for register in ir.registers)))
    touches, depths = [], []
    for operation in ir.operations:
        axes = {operation.target}
        if operation.control is not None:
            axes.add(operation.control)
        # All preceding intersecting instruction sets form an independent DAG.
        parents = [depth for used, depth in zip(touches, depths) if used.intersection(axes)]
        depths.append(1 + max(parents, default=0))
        touches.append(axes)
    return (len(ir.registers), max(register.dimension for register in ir.registers),
            len(labels) - logical_size, len(touches),
            sum(len(used) == 2 for used in touches), max(depths, default=0))


def objective_subsets():
    return [tuple(indices) for count in range(1, len(RESOURCE_OBJECTIVES) + 1)
            for indices in itertools.combinations(range(len(RESOURCE_OBJECTIVES)), count)]


def oracle_dominates(left, right, indices):
    differences = [left[index] - right[index] for index in indices]
    return max(differences) <= 0 and min(differences) < 0


def evaluations():
    logical = logical_from_source("qutrit q\nshift q\n")
    binary = "qubit a\nqubit b\nsum a b\nsum b a\nshift b\n"
    definitions = [
        ((3,), (0, 1, 2), "qutrit p\nshift p\n", None),
        ((3,), (1, 2, 0), "qutrit p\nshift p\n", 0),
        ((2, 2), (0, 1, 2), binary, None),
        ((2, 2), (1, 2, 0), binary + "shift a\nshift a\n", 1),
        ((2, 3), (0, 1, 2), None, None),
        ((4,), (0, 1, 2), "qudit 4 p\nshift p\n", None),
        ((2, 2), (2, 0, 1), binary + "shift a\n" * 6, 2),
    ]
    result = []
    for physical, mapping, source, seed_index in definitions:
        encoding = BasisEncoding((3,), physical, mapping)
        candidate = EncodingCandidate(encoding, "flat-prefix" if seed_index is None else "seed",
                                      seed_index=seed_index)
        implementation = None if source is None else CircuitImplementation(encoding, logical_from_source(source).ir)
        result.append(evaluate_candidate(logical, candidate, implementation, max_operations_per_program=8))
    require(tuple(value.status for value in result) ==
            ("pass", "pass", "pass", "pass", "unimplemented", "fail", "unsupported"),
            "Supplied-circuit eligibility outcomes disagree")
    return tuple(result)


def audit():
    stats = {"resource_circuits": 0, "verified_fronts": 0, "integer_dominance_pairs": 0}
    for dimensions in ((2,), (3,), (2, 3), (3, 2), (2, 2, 2)):
        registers = tuple(Register(f"q{i}", d) for i, d in enumerate(dimensions))
        primitives = [Operation(kind, axis) for axis in range(len(dimensions))
                      for kind in (GateKind.SHIFT, GateKind.FOURIER)]
        primitives += [Operation(GateKind.SUM, target, control) for target in range(len(dimensions))
                       for control in range(len(dimensions)) if target != control]
        for count in range(4):
            for operations in itertools.product(primitives, repeat=count):
                ir = CircuitIR(registers, operations)
                require(count_resources(ir, logical_size=2).as_tuple() == oracle_counts(ir, 2),
                        f"Dependency/count mismatch: {dimensions}, {operations}")
                stats["resource_circuits"] += 1

    vectors = json.loads((Path(__file__).resolve().parents[1] /
                         "benchmarks/encoding-search-v1.json").read_text())
    rows = vectors["pareto_cases"][0]["rows"]
    for indices in objective_subsets():
        names = tuple(RESOURCE_OBJECTIVES[index] for index in indices)
        for left, right in itertools.product(rows, repeat=2):
            require(dominates(ResourceCounts(*left), ResourceCounts(*right), names) ==
                    oracle_dominates(left, right, indices), "Abstract integer dominance mismatch")
            stats["integer_dominance_pairs"] += 1

    values = evaluations()
    orders = (values, tuple(reversed(values)), values[2:] + values[:2])
    for ordered, indices in itertools.product(orders, objective_subsets()):
        names = tuple(RESOURCE_OBJECTIVES[index] for index in indices)
        valid = [(value.candidate_id, oracle_counts(value.implementation.circuit, value.logical.state_size))
                 for value in ordered if value.status == "pass"]
        expected = tuple(identifier for identifier, row in valid if not any(
            oracle_dominates(other, row, indices) for _, other in valid))
        require(pareto_front(ordered, names) == expected, "Verified-circuit Pareto front mismatch")
        stats["verified_fronts"] += 1
    return stats


def main():
    stats = audit()
    print("Independent resource/comparison audit:", json.dumps(stats, sort_keys=True))
    print("Evidence: exact structural counts and passing supplied circuits; no hardware cost or synthesis claim.")


if __name__ == "__main__":
    main()
