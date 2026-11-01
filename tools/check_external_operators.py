"""Cirq-composed full-operator baseline; custom qudit gates imply no native support."""

import cmath
import hashlib
from importlib.metadata import version
import itertools
import json
import math
from pathlib import Path
import platform
import random

try:
    import cirq
    import numpy as np
except ImportError as error:
    raise SystemExit("External validation unavailable; install .[external-validation] on Python 3.11+. " + str(error)) from error

from q3hash import (BasisEncoding, ReferenceOperator, __version__, apply_state,
                    logical_from_source, verify_equivalence)


PIN = "1.7.0"
SEED = 20261101
TOLERANCE = 1e-11


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def local_gate(kind, dimensions):
    """Construct local matrices from tensor labels, without Q3# helpers."""
    if kind == "shift" and dimensions == (2,):
        return cirq.X, "builtin"
    if kind == "fourier" and dimensions == (2,):
        return cirq.H, "builtin"
    if kind == "sum" and dimensions == (2, 2):
        return cirq.CNOT, "builtin"
    labels = list(itertools.product(*(range(d) for d in dimensions)))
    matrix = np.zeros((len(labels), len(labels)), dtype=np.complex128)
    if kind == "fourier":
        d, = dimensions
        for row, column in itertools.product(range(d), repeat=2):
            matrix[row, column] = cmath.exp(2j * math.pi * row * column / d) / math.sqrt(d)
    else:
        for column, label in enumerate(labels):
            if kind == "shift":
                output = ((label[0] + 1) % dimensions[0],)
            elif kind == "sum":
                output = (label[0], (label[1] + label[0]) % dimensions[1])
            else:
                raise ValueError("Unknown reference gate: " + kind)
            matrix[labels.index(output), column] = 1
    return cirq.MatrixGate(matrix, qid_shape=dimensions), "custom-qudit-matrix"


def reference(source):
    """Read the fixed declaration/gate subset independently of the Q3# parser."""
    names, qids, dimensions, operations = {}, [], [], []
    counts = dict(builtin=0, custom_qudit_matrix=0)
    for line in source.splitlines():
        words = line.split()
        if not words:
            continue
        kind = words[0]
        if kind in ("qubit", "qutrit", "qudit"):
            require(not operations, "Reference declarations must precede operations")
            require(len(words) == (3 if kind == "qudit" else 2), "Reference declaration arity")
            dimension = int(words[1]) if kind == "qudit" else (2 if kind == "qubit" else 3)
            name = words[-1]
            require(name not in names and 2 <= dimension <= 32, "Reference declaration value")
            names[name] = len(qids)
            # Deliberately reverse lexical names: explicit order must control the basis.
            qids.append(cirq.NamedQid(f"site-{99 - len(qids):02}", dimension=dimension))
            dimensions.append(dimension)
        else:
            require(kind in ("shift", "fourier", "sum"), "Unsupported reference instruction")
            require(len(words) == (3 if kind == "sum" else 2), "Reference operation arity")
            axes = tuple(names[name] for name in words[1:])
            require(len(set(axes)) == len(axes), "Repeated reference operands")
            gate, category = local_gate(kind, tuple(dimensions[axis] for axis in axes))
            operations.append(gate.on(*(qids[axis] for axis in axes)))
            counts[category.replace("-", "_")] += 1
    require(bool(qids) and math.prod(dimensions) <= 64, "Reference full-operator budget")
    circuit = cirq.Circuit(operations, strategy=cirq.InsertStrategy.NEW)
    matrix = circuit.unitary(qubit_order=qids, qubits_that_should_be_present=qids,
                             ignore_terminal_measurements=False, dtype=np.complex128)
    require(matrix.shape == (math.prod(dimensions),) * 2 and matrix.dtype == np.complex128, "Reference basis shape/dtype")
    return tuple(dimensions), matrix, counts


def independent_metrics(logical, physical, mapping):
    isometry = np.zeros((physical.shape[0], logical.shape[0]), dtype=np.complex128)
    for column, row in enumerate(mapping):
        isometry[row, column] = 1
    left, right = physical @ isometry, isometry @ logical
    inner = np.vdot(right, left)
    phase = inner / abs(inner) if inner != 0 else 1 + 0j
    unused = [row for row in range(physical.shape[0]) if row not in mapping]
    return dict(subspace_residual=float(np.linalg.norm(left - phase * right)),
                leakage_norm=float(np.linalg.norm(left[unused, :])),
                logical_unitarity_error=float(np.linalg.norm(logical.conj().T @ logical - np.eye(logical.shape[0]))),
                physical_unitarity_error=float(np.linalg.norm(physical.conj().T @ physical - np.eye(physical.shape[0]))))


def source_for(dimensions, gates):
    declarations = [f"qudit {d} r{i}" for i, d in enumerate(dimensions)]
    instructions = [kind + " " + " ".join(f"r{i}" for i in axes) for kind, axes in gates]
    return "\n".join(declarations + instructions)


def audit():
    require(cirq.__version__ == PIN, "Use the pinned Cirq version " + PIN + "; found " + cirq.__version__)
    stats = dict(programs=0, basis_columns=0, arbitrary_states=0, builtin_operations=0,
                 custom_qudit_matrix_operations=0, frozen_workloads=0, circuit_verifications=0,
                 reference_verifications=0, local_gate_programs=0, sum_axis_programs=0,
                 spectator_programs=0, seeded_programs=0, measurement_rejections=0)
    maximum = dict(operator_amplitude_error=0.0, arbitrary_state_error=0.0, metric_difference=0.0)
    rng = np.random.default_rng(SEED)
    cache = {}

    def check(source):
        if source in cache:
            return cache[source]
        dimensions, expected, counts = reference(source)
        program = logical_from_source(source)
        require(program.dimensions == dimensions, "Q3#/Cirq register order mismatch")
        size = expected.shape[0]
        actual = np.column_stack([apply_state(program.ir, tuple(complex(row == column) for row in range(size)))
                                  for column in range(size)])
        error = float(np.max(np.abs(actual - expected)))
        maximum["operator_amplitude_error"] = max(maximum["operator_amplitude_error"], error)
        require(error <= TOLERANCE, "Complete operator mismatch for source: " + source)
        # Unnormalised complex vectors exercise linear application; zero stays zero.
        states = (np.zeros(size, dtype=np.complex128),
                  np.array([complex(i + 1, 0.5 - i) for i in range(size)]),
                  rng.normal(size=size) + 1j * rng.normal(size=size),
                  np.array([complex(0.25 * i, (-1)**i * 2.5) for i in range(size)]))
        for state in states:
            observed = np.asarray(apply_state(program.ir, tuple(complex(x) for x in state)))
            difference = float(np.max(np.abs(observed - expected @ state)))
            maximum["arbitrary_state_error"] = max(maximum["arbitrary_state_error"], difference)
            require(difference <= TOLERANCE, "Arbitrary-state mismatch for source: " + source)
        stats["programs"] += 1
        stats["basis_columns"] += size
        stats["arbitrary_states"] += len(states)
        stats["builtin_operations"] += counts["builtin"]
        stats["custom_qudit_matrix_operations"] += counts["custom_qudit_matrix"]
        cache[source] = (program, expected)
        return cache[source]

    # Full local columns across every supported dimension, with built-in binary gates.
    for dimension, kind in itertools.product(range(2, 33), ("shift", "fourier")):
        check(source_for((dimension,), [(kind, (0,))]))
        stats["local_gate_programs"] += 1
    # Every dimension pair that fits the 64-state full-operator budget, both axes.
    for control, target in itertools.product(range(2, 33), repeat=2):
        if control * target <= 64:
            for dimensions, axes in (((control, target), (0, 1)), ((target, control), (1, 0))):
                check(source_for(dimensions, [("sum", axes)]))
                stats["sum_axis_programs"] += 1
    templates = ((2, 3, 2), (3, 2, 3), (2, 4, 2), (2, 2, 5), (3, 3, 3), (2, 2, 2))
    for dimensions in templates:
        for control, target in itertools.permutations(range(3), 2):
            # The remaining axis is a true spectator, absent from every operation.
            check(source_for(dimensions, [("fourier", (control,)), ("sum", (control, target)),
                                          ("shift", (control,)), ("fourier", (target,))]))
            stats["spectator_programs"] += 1
    choices = random.Random(SEED)
    for _ in range(120):
        dimensions = choices.choice(templates)
        gates = []
        for _ in range(choices.randrange(9)):
            kind = choices.choice(("shift", "fourier", "sum"))
            axes = tuple(choices.sample(range(3), 2 if kind == "sum" else 1))
            gates.append((kind, axes))
        check(source_for(dimensions, gates))
        stats["seeded_programs"] += 1

    path = Path(__file__).resolve().parents[1] / "benchmarks/hardware-cost-v1.json"
    raw = path.read_bytes()
    fixture = json.loads(raw)
    workload_results = []
    for row in fixture["workloads"]:
        logical, logical_matrix = check(row["logical"])
        stats["frozen_workloads"] += 1
        if row["physical"] is None:
            require(row["expected"] == "unimplemented" and row["mapping"] is None, "Missing synthesis must remain missing")
            workload_results.append(dict(id=row["id"], status="unimplemented", physical_evidence="none"))
            continue
        physical, physical_matrix = check(row["physical"])
        encoding = BasisEncoding(logical.dimensions, physical.dimensions, tuple(row["mapping"]))
        report = verify_equivalence(logical, physical.ir, encoding, max_dimension=row["max_dimension"])
        reference_input = ReferenceOperator(physical.dimensions,
            tuple(tuple(complex(x) for x in values) for values in physical_matrix))
        external = verify_equivalence(logical, reference_input, encoding, max_dimension=row["max_dimension"])
        require(report.status == external.status == row["expected"], row["id"] + ": expected evidence status")
        require(report.evidence == "q3hash-circuit" and external.evidence == "reference-only", "Evidence kinds must remain distinct")
        metrics = independent_metrics(logical_matrix, physical_matrix, row["mapping"])
        if row["expected"] != "unsupported":
            require(("pass" if all(x <= report.tolerance for x in metrics.values()) else "fail") == row["expected"], row["id"] + ": independent status")
            for key, expected in metrics.items():
                for comparison in (report, external):
                    difference = abs(getattr(comparison, key) - expected)
                    maximum["metric_difference"] = max(maximum["metric_difference"], difference)
                    require(difference <= TOLERANCE, row["id"] + ": independent " + key)
        stats["circuit_verifications"] += 1
        stats["reference_verifications"] += 1
        workload_results.append(dict(id=row["id"], status=report.status,
                                     physical_evidence="supplied-circuit-and-separate-cirq-reference"))

    q = cirq.NamedQid("measurement-control", dimension=3)
    try:
        cirq.Circuit(cirq.measure(q)).unitary(qubit_order=[q], qubits_that_should_be_present=[q],
                                             ignore_terminal_measurements=False, dtype=np.complex128)
    except ValueError:
        stats["measurement_rejections"] += 1
    require(stats["measurement_rejections"] == 1, "Terminal measurements were silently ignored")
    require(stats["builtin_operations"] > 0 and stats["custom_qudit_matrix_operations"] > 0, "Both reference gate paths must run")
    return dict(result="passed", python=platform.python_version(), platform=platform.system(), q3hash=__version__,
                cirq_core=version("cirq-core"), numpy=np.__version__, scipy=version("scipy"),
                dependency_versions={name: version(name) for name in ("attrs", "duet", "matplotlib", "networkx", "pandas", "sympy", "tqdm")},
                seed=SEED, dtype="complex128", basis_order="explicit-declaration-order-last-axis-fastest",
                max_operator_dimension=64, tolerance=TOLERANCE, fixture_sha256=hashlib.sha256(raw).hexdigest(),
                coverage=stats, maximum_errors=maximum, workloads=workload_results,
                evidence_scope="Cirq composition baseline with independently constructed local qudit matrices; no native-device or hardware-cost claim")


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, sort_keys=True, allow_nan=False))
