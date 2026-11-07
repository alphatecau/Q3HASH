"""Small independent, standard-library-only full-matrix oracle for the v0.6 fixture.

Deliberately does NOT import q3hash. Checks complete operators (not just |0>),
independent gate timing DAG arithmetic and adversarial negative controls.
"""

import cmath
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_source(path):
    return parse_program(path.read_text(encoding="utf-8"))


def parse_program(source):
    registers, operations = [], []
    for original in source.splitlines():
        words = original.split("#", 1)[0].split()
        if not words:
            continue
        if words[0] in ("qubit", "qutrit"):
            assert len(words) == 2
            registers.append((words[1], 2 if words[0] == "qubit" else 3))
        elif words[0] == "qudit":
            assert len(words) == 3
            registers.append((words[2], int(words[1])))
        else:
            assert words[0] in ("shift", "sum"), words
            assert len(words) == (2 if words[0] == "shift" else 3)
            operations.append(tuple(words))
    dimensions = tuple(d for _, d in registers)
    assert len(set(name for name, _ in registers)) == len(registers)
    names = {name: i for i, (name, _) in enumerate(registers)}
    assert all(word in names for op in operations for word in op[1:])
    return dimensions, tuple((op[0], *(names[word] for word in op[1:])) for op in operations)


def digits(index, dimensions):
    result = []
    for dimension in reversed(dimensions):
        result.insert(0, index % dimension)
        index //= dimension
    assert index == 0
    return result


def flat_index(digits_, dimensions):
    out = 0
    for digit, base in zip(digits_, dimensions):
        out = out * base + digit
    return out


def matrix_for(dimensions, operations):
    size = math.prod(dimensions)
    rows = [[0j] * size for _ in range(size)]
    for column in range(size):
        label = digits(column, dimensions)
        for op in operations:
            if op[0] == "shift":
                target = op[1]
                label[target] = (label[target] + 1) % dimensions[target]
            elif op[0] == "sum":
                control, target = op[1:]
                label[target] = (label[target] + label[control]) % dimensions[target]
            else:
                raise AssertionError(op)
        rows[flat_index(label, dimensions)][column] = 1 + 0j
    return tuple(tuple(row) for row in rows)


def unitarity_error(matrix):
    size = len(matrix)
    return math.hypot(*(abs(sum(matrix[k][i].conjugate() * matrix[k][j]
                               for k in range(size)) - int(i == j))
                        for i in range(size) for j in range(size)))


def compare(logical, physical, mapping):
    logical_size, physical_size = len(logical), len(physical)
    assert len(mapping) == logical_size and len(set(mapping)) == logical_size
    assert all(0 <= index < physical_size for index in mapping)
    positions = {physical_idx: logical_idx for logical_idx, physical_idx in enumerate(mapping)}
    left = [[physical[r][mapping[c]] for c in range(logical_size)] for r in range(physical_size)]
    right = [[logical[positions[r]][c] if r in positions else 0j
              for c in range(logical_size)] for r in range(physical_size)]
    inner = sum(right[r][c].conjugate() * left[r][c]
                for r in range(physical_size) for c in range(logical_size))
    phase = inner / abs(inner) if abs(inner) else 1 + 0j
    residual = math.hypot(*(abs(left[r][c] - phase * right[r][c])
                             for r in range(physical_size) for c in range(logical_size)))
    leakage = math.hypot(*(abs(left[r][c]) for r in range(physical_size) if r not in positions
                            for c in range(logical_size)))
    return (residual, leakage, unitarity_error(logical), unitarity_error(physical))


def independent_resources(dimensions, operations, logical_size):
    layers = [0] * len(dimensions)
    two_site = 0
    for op in operations:
        if op[0] == "sum":
            axes = (op[1], op[2])
            two_site += 1
        else:
            axes = (op[1],)
        layer = 1 + max(layers[a] for a in axes)
        for a in axes:
            layers[a] = layer
    return [len(dimensions), max(dimensions), math.prod(dimensions) - logical_size,
            len(operations), two_site, max(layers)]


def independent_timing(dimensions, operations, placement, profile):
    assert tuple(profile["site_dimensions"][index] for index in placement) == dimensions
    bindings = {(b["kind"], tuple(b["sites"])): b["duration"] for b in profile["bindings"]}
    edges = {tuple(pair) for pair in profile["couplings"]}
    finish_low, finish_high = [0] * len(profile["site_dimensions"]), [0] * len(profile["site_dimensions"])
    for operation in operations:
        sites = (placement[operation[1]], placement[operation[2]]) if operation[0] == "sum" else (placement[operation[1]],)
        if operation[0] == "sum":
            assert sites in edges
        timing = bindings[(operation[0], sites)]
        assert timing is not None
        low = max(finish_low[index] for index in sites) + timing["lower_ps"]
        high = max(finish_high[index] for index in sites) + timing["upper_ps"]
        for index in sites:
            finish_low[index] = low
            finish_high[index] = high
    return [max(finish_low), max(finish_high)]


def run():
    fixture = json.loads((ROOT / "benchmarks/three-way-qutrit-shift-v1.json").read_text(encoding="utf-8"))
    constraints = json.loads((ROOT / fixture["constraints"]).read_text(encoding="utf-8"))
    assert constraints["max_physical_size"] == 6, constraints
    profile = json.loads((ROOT / fixture["hardware_profile"]).read_text(encoding="utf-8"))
    assert profile["provenance"]["kind"] == "synthetic", profile["provenance"]
    logical_dim, logical_ops = parse_source(ROOT / fixture["logical_source"])
    assert logical_dim == (3,) and logical_ops == (("shift", 0),)
    logical = matrix_for(logical_dim, logical_ops)
    assert unitarity_error(logical) == 0

    for case in fixture["cases"]:
        dimensions, operations = parse_source(ROOT / case["physical_source"])
        encoding = json.loads((ROOT / case["encoding"]).read_text(encoding="utf-8"))
        assert list(dimensions) == case["dimensions"] == encoding["physical_dimensions"]
        assert encoding["logical_dimensions"] == [3]
        physical = matrix_for(dimensions, operations)
        metrics = compare(logical, physical, tuple(encoding["physical_basis_indices"]))
        assert all(math.isfinite(x) and x <= fixture["tolerance"] for x in metrics), (case["id"], metrics)
        resource = independent_resources(dimensions, operations, logical_size=3)
        assert resource == case["resources"], (case["id"], resource)
        critical = independent_timing(dimensions, operations, tuple(case["placement"]), profile)
        assert critical == case["critical_path_ps"], (case["id"], critical)
        print(f"ORACLE PASS {case['id']}: complete-operator metrics={metrics}, resource={resource}, synthetic timing={critical} ps")

    # Adversarial negative controls, computed independently of package verifier.
    four = matrix_for((4,), (("shift", 0),))
    leak = compare(logical, four, (0, 1, 2))
    assert leak[1] == 1 and leak[0] > 1, leak
    qubit_id = ((1 + 0j, 0j), (0j, 1 + 0j))
    relative_phase = ((1 + 0j, 0j), (0j, -1 + 0j))
    phase_error = compare(qubit_id, relative_phase, (0, 1))
    assert phase_error[0] > 1 and phase_error[2:] == (0, 0), phase_error
    identity3 = matrix_for((3,), ())
    nonunitary = tuple(tuple(complex(i == j and i < 3) for j in range(4)) for i in range(4))
    complement = compare(identity3, nonunitary, (0, 1, 2))
    assert complement[:2] == (0, 0) and complement[3] == 1, complement
    phase = cmath.exp(0.7j)
    accepted = compare(qubit_id, ((phase, 0j), (0j, phase)), (0, 1))
    assert all(x < 1e-10 for x in accepted), accepted
    print("ORACLE PASS negative controls: leakage, relative phase, nonunitary complement; positive global phase")
    print("ORACLE PASS: all three exact matrices; no Q3HASH dependency; durations are fictitious")


if __name__ == "__main__":
    run()
