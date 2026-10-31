"""Validation at source, public model, and lowered IR boundaries."""

from dataclasses import FrozenInstanceError
import unittest

from q3hash import Circuit, CircuitIR, Gate, GateKind, Operation, Register, lower, parse, simulate


class IRTests(unittest.TestCase):
    def test_dimensions_are_bounded_integers(self):
        for value in (True, False, 1, 33, -2, 2.0, "3", None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "dimension"):
                Register("q", value)

    def test_names_follow_the_source_grammar(self):
        for value in ("", "3q", "a-b", "has space", "é", None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "name"):
                Register(value, 3)

    def test_gate_kinds_and_arity_are_validated(self):
        for value in ("measure", "", None, []):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "unsupported gate"):
                Gate(value, "q")
        with self.assertRaisesRegex(ValueError, "control register"):
            Gate("sum", "q")
        with self.assertRaisesRegex(ValueError, "different"):
            Gate("sum", "q", "q")
        with self.assertRaisesRegex(ValueError, "does not accept"):
            Gate("shift", "q", "a")

    def test_programmatic_circuits_validate_register_references(self):
        registers = (Register("q", 3),)
        for gate in (Gate("shift", "missing"), Gate("sum", "q", "missing")):
            with self.subTest(gate=gate), self.assertRaisesRegex(ValueError, "unknown register"):
                Circuit(registers, (gate,))
        with self.assertRaisesRegex(ValueError, "already exists"):
            Circuit((Register("q", 2), Register("q", 3)), ())

    def test_model_sequences_and_element_types_are_checked(self):
        for registers, gates in (((), ()), (None, ()), (("q",), ()), ((Register("q", 2),), ("shift",))):
            with self.subTest(registers=registers, gates=gates), self.assertRaises(ValueError):
                Circuit(registers, gates)
        with self.assertRaisesRegex(ValueError, "operations"):
            CircuitIR((Register("q", 2),), ("shift",))

    def test_models_snapshot_mutable_sequences(self):
        registers = [Register("q", 3)]
        gates = [Gate("fourier", "q")]
        circuit = Circuit(registers, gates)
        operations = [Operation(GateKind.FOURIER, 0)]
        ir = CircuitIR(registers, operations)
        registers.clear()
        gates.clear()
        operations.clear()
        self.assertEqual(len(circuit.registers), 1)
        self.assertEqual(len(circuit.gates), 1)
        self.assertEqual(len(ir.operations), 1)
        with self.assertRaises(FrozenInstanceError):
            ir.operations = ()

    def test_lowering_resolves_axes_without_changing_operand_order(self):
        circuit = parse("qubit a\nqutrit b\nqudit 5 c\nsum c a\nfourier b")
        ir = lower(circuit)
        self.assertEqual(ir.dimensions, (2, 3, 5))
        self.assertEqual(ir.strides, (15, 5, 1))
        self.assertEqual(ir.state_size, 30)
        self.assertEqual(ir.operations, (Operation(GateKind.SUM, 0, 2), Operation(GateKind.FOURIER, 1)))
        self.assertEqual(simulate(ir), simulate(circuit))

    def test_original_single_register_constructor_is_compatible(self):
        gate = Gate("shift", "q")
        self.assertEqual(gate.kind, "shift")
        self.assertIs(gate.kind, GateKind.SHIFT)
        self.assertEqual(simulate(Circuit((Register("q", 3),), (gate,))), (0j, 1 + 0j, 0j))

    def test_lowered_operation_indices_and_arity_are_validated(self):
        cases = [("shift", -1, None), ("shift", True, None), ("shift", 0, 1),
                 ("sum", 0, None), ("sum", 1, False), ("sum", 0, 0), ("bad", 0, None)]
        for kind, target, control in cases:
            with self.subTest(kind=kind, target=target, control=control), self.assertRaises(ValueError):
                Operation(kind, target, control)
        registers = (Register("a", 2), Register("b", 3))
        for operation in (Operation("shift", 2), Operation("sum", 0, 2)):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "out of range"):
                CircuitIR(registers, (operation,))

    def test_sum_source_operands_are_control_then_target(self):
        circuit = parse("qutrit control\nqubit target\nsum control target")
        self.assertEqual(circuit.gates, (Gate("sum", "target", "control"),))

    def test_source_diagnostics_include_the_line(self):
        sources = [
            ("qutrit q\nsum q missing", "line 2: unknown register"),
            ("qutrit q\nsum missing q", "line 2: unknown register"),
            ("qutrit q\nsum q q", "line 2: control and target"),
            ("qutrit q\nsum q later\nqubit later", "line 2: unknown register"),
            ("# comment\nqudit 33 q", "line 2: dimension"),
        ]
        for source, message in sources:
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, message):
                parse(source)

    def test_malformed_gate_syntax_is_rejected(self):
        for line in ("sum q", "sum q t extra", "shift q t", "cnot q t", "sum q bad-name"):
            with self.subTest(line=line), self.assertRaisesRegex(ValueError, "invalid instruction"):
                parse("qubit q\nqubit t\n" + line)

    def test_wrong_api_object_types_are_rejected(self):
        with self.assertRaises(TypeError):
            parse(None)
        with self.assertRaises(TypeError):
            lower("qutrit q")
        with self.assertRaises(TypeError):
            simulate("qutrit q")

    def test_lowering_does_not_allocate_or_bypass_the_simulator_cap(self):
        ir = lower(parse("qudit 32 a\nqudit 32 b\nqudit 32 c\nqudit 3 d\nsum a d"))
        self.assertEqual(ir.state_size, 98304)
        with self.assertRaisesRegex(ValueError, "statevector too large"):
            simulate(ir)


if __name__ == "__main__":
    unittest.main()
