"""Small dense-matrix oracle, independent of the production stride algorithm."""

from itertools import product
import math
from pathlib import Path
import random
import unittest

from q3hash import Circuit, Gate, Register, parse, simulate


def dense_gate(dimensions, kind, target, control=None):
    """Construct the full matrix using explicit tensor basis labels, never strides."""
    labels = tuple(product(*(range(dimension) for dimension in dimensions)))
    positions = {label: index for index, label in enumerate(labels)}
    matrix = [[0j for _ in labels] for _ in labels]
    for column, before in enumerate(labels):
        if kind == "sum":
            after = list(before)
            after[target] = (before[target] + before[control]) % dimensions[target]
            matrix[positions[tuple(after)]][column] = 1
            continue
        for row, after in enumerate(labels):
            if any(after[axis] != before[axis] for axis in range(len(dimensions)) if axis != target):
                continue
            if kind == "shift":
                matrix[row][column] = int(after[target] == (before[target] + 1) % dimensions[target])
            elif kind == "fourier":
                angle = 2 * math.pi * after[target] * before[target] / dimensions[target]
                matrix[row][column] = complex(math.cos(angle), math.sin(angle)) / math.sqrt(dimensions[target])
            else:
                raise AssertionError("unknown oracle gate")
    return matrix


def dense_state(dimensions, operations):
    state = [1 + 0j] + [0j] * (math.prod(dimensions) - 1)
    for kind, target, control in operations:
        matrix = dense_gate(dimensions, kind, target, control)
        state = [sum(value * amplitude for value, amplitude in zip(row, state)) for row in matrix]
    return state


def purity_left(state, left_dimension, right_dimension):
    # Partial trace over the right register, followed by Tr(rho_left**2).
    density = [
        [sum(state[row * right_dimension + k] * state[column * right_dimension + k].conjugate()
             for k in range(right_dimension)) for column in range(left_dimension)]
        for row in range(left_dimension)
    ]
    purity = sum(density[row][column] * density[column][row]
                 for row in range(left_dimension) for column in range(left_dimension))
    return purity.real


class SemanticsTests(unittest.TestCase):
    def assert_state(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for index, (got, wanted) in enumerate(zip(actual, expected)):
            self.assertAlmostEqual(got.real, wanted.real, places=11, msg=f"real amplitude {index}")
            self.assertAlmostEqual(got.imag, wanted.imag, places=11, msg=f"imaginary amplitude {index}")

    def test_fourier_complex_phase_convention(self):
        norm = math.sqrt(3)
        expected = (1 / norm, complex(-0.5, math.sqrt(3) / 2) / norm,
                    complex(-0.5, -math.sqrt(3) / 2) / norm)
        self.assert_state(simulate(parse("qutrit q\nshift q\nfourier q")), expected)

    def test_bell_and_qutrit_states_are_entangled(self):
        root = Path(__file__).resolve().parents[1] / "examples"
        for filename, dimension in (("bell.q3", 2), ("qutrit-entangled.q3", 3)):
            with self.subTest(filename=filename):
                state = simulate(parse((root / filename).read_text()))
                expected = [1 / math.sqrt(dimension) if index // dimension == index % dimension else 0j
                            for index in range(dimension ** 2)]
                self.assert_state(state, expected)
                self.assertAlmostEqual(sum(abs(amplitude) ** 2 for amplitude in state), 1)
                self.assertAlmostEqual(purity_left(state, dimension, dimension), 1 / dimension)

    def test_mixed_dimension_entanglement_in_both_operand_orders(self):
        for left, right, expected_purity in ((2, 3, 0.5), (3, 2, 5 / 9)):
            with self.subTest(dimensions=(left, right)):
                source = f"qudit {left} c\nqudit {right} t\nfourier c\nsum c t"
                state = simulate(parse(source))
                self.assert_state(state, dense_state((left, right), [("fourier", 0, None), ("sum", 1, 0)]))
                self.assertAlmostEqual(sum(abs(amplitude) ** 2 for amplitude in state), 1)
                self.assertAlmostEqual(purity_left(state, left, right), expected_purity)

    def test_sum_full_unitaries_on_all_axes_with_spectators(self):
        for dimensions in ((2, 2), (3, 3), (2, 3), (3, 2), (2, 3, 4)):
            registers = tuple(Register(f"q{index}", dimension) for index, dimension in enumerate(dimensions))
            labels = tuple(product(*(range(dimension) for dimension in dimensions)))
            for control in range(len(dimensions)):
                for target in range(len(dimensions)):
                    if control == target:
                        continue
                    with self.subTest(dimensions=dimensions, control=control, target=target):
                        oracle = dense_gate(dimensions, "sum", target, control)
                        columns = []
                        for column, basis in enumerate(labels):
                            preparation = tuple(Gate("shift", f"q{axis}")
                                                for axis, value in enumerate(basis) for _ in range(value))
                            state = simulate(Circuit(registers, preparation + (Gate("sum", f"q{target}", f"q{control}"),)))
                            self.assert_state(state, [row[column] for row in oracle])
                            columns.append(state)
                        for first, column in enumerate(columns):
                            for second, other in enumerate(columns):
                                overlap = sum(a.conjugate() * b for a, b in zip(column, other))
                                self.assertAlmostEqual(overlap.real, int(first == second))
                                self.assertAlmostEqual(overlap.imag, 0)

    def test_fourier_and_shift_full_matrices_on_each_tensor_axis(self):
        for dimensions in ((3,), (4,), (2, 3), (3, 2, 2)):
            registers = tuple(Register(f"q{index}", dimension) for index, dimension in enumerate(dimensions))
            labels = tuple(product(*(range(dimension) for dimension in dimensions)))
            for kind in ("shift", "fourier"):
                for target in range(len(dimensions)):
                    with self.subTest(dimensions=dimensions, kind=kind, target=target):
                        oracle = dense_gate(dimensions, kind, target)
                        for column, basis in enumerate(labels):
                            preparation = tuple(Gate("shift", f"q{axis}")
                                                for axis, value in enumerate(basis) for _ in range(value))
                            state = simulate(Circuit(registers, preparation + (Gate(kind, f"q{target}"),)))
                            self.assert_state(state, [row[column] for row in oracle])

    def test_composed_circuits_match_independent_dense_matrices(self):
        generator = random.Random(20261031)
        for dimensions in ((2, 3), (3, 2), (3, 3), (2, 3, 2), (3, 2, 4)):
            for trial in range(4):
                operations = [("fourier", 0, None)]
                for _ in range(8):
                    kind = generator.choice(("shift", "fourier", "sum"))
                    target = generator.randrange(len(dimensions))
                    control = generator.choice([axis for axis in range(len(dimensions)) if axis != target]) if kind == "sum" else None
                    operations.append((kind, target, control))
                lines = [f"qudit {dimension} q{index}" for index, dimension in enumerate(dimensions)]
                lines += [f"sum q{control} q{target}" if kind == "sum" else f"{kind} q{target}"
                          for kind, target, control in operations]
                with self.subTest(dimensions=dimensions, trial=trial):
                    state = simulate(parse("\n".join(lines)))
                    self.assert_state(state, dense_state(dimensions, operations))
                    self.assertAlmostEqual(sum(abs(amplitude) ** 2 for amplitude in state), 1, places=11)

    def test_repeated_sum_is_identity_after_target_dimension_applications(self):
        for left, right in ((2, 3), (3, 2), (3, 3), (4, 5)):
            prefix = f"qudit {left} c\nqudit {right} t\nshift c\nfourier c\nshift t\nfourier t\n"
            with self.subTest(dimensions=(left, right)):
                self.assert_state(simulate(parse(prefix + "sum c t\n" * right)), simulate(parse(prefix)))

    def test_mixed_entanglement_example_has_the_documented_state(self):
        path = Path(__file__).resolve().parents[1] / "examples/mixed-entangled.q3"
        self.assert_state(simulate(parse(path.read_text())), (1 / math.sqrt(2), 0j, 0j, 0j, 1 / math.sqrt(2), 0j))


if __name__ == "__main__":
    unittest.main()
