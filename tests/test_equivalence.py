"""Complete operator checks catch relative-phase, leakage and zero-state false positives."""

import cmath
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from q3hash import (BasisEncoding, CircuitIR, ReferenceOperator, Register, logical_from_source,
                    lower, parse, simulate, verify_equivalence)


ROOT = Path(__file__).resolve().parents[1]


class EquivalenceTests(unittest.TestCase):
    def test_qutrit_shift_has_a_real_three_gate_qubit_implementation(self):
        logical = logical_from_source("qutrit q\nshift q")
        physical = lower(parse("qubit a\nqubit b\nsum a b\nsum b a\nshift b"))
        report = verify_equivalence(logical, physical, BasisEncoding((3,), (2, 2), (0, 1, 2)))
        self.assertEqual(report.status, "pass")
        self.assertEqual(report.evidence, "q3hash-circuit")
        self.assertEqual((report.subspace_residual, report.leakage_norm), (0, 0))

    def test_dimension_four_shift_is_a_zero_input_false_positive_with_leakage(self):
        logical = logical_from_source("qutrit q\nshift q")
        physical = lower(parse("qudit 4 q\nshift q"))
        encoding = BasisEncoding((3,), (4,), (0, 1, 2))
        self.assertEqual(encoding.encode_vector(simulate(logical.ir)), simulate(physical))
        report = verify_equivalence(logical, physical, encoding)
        self.assertEqual(report.status, "fail")
        self.assertAlmostEqual(report.leakage_norm, 1)

    def test_relative_phase_is_not_treated_as_per_column_global_phase(self):
        logical = logical_from_source("qubit q")
        physical = lower(parse("qubit q\nfourier q\nshift q\nfourier q"))
        self.assertLess(max(abs(a - b) for a, b in zip(simulate(logical.ir), simulate(physical))), 1e-12)
        report = verify_equivalence(logical, physical, BasisEncoding((2,), (2,), (0, 1)))
        self.assertEqual(report.status, "fail")
        self.assertGreater(report.subspace_residual, 1)
        self.assertLess(report.physical_unitarity_error, 1e-12)

    def test_one_global_phase_is_accepted_and_references_are_labelled(self):
        logical = logical_from_source("qubit q")
        phase = cmath.exp(0.7j)
        physical = ReferenceOperator((2,), ((phase, 0), (0, phase)))
        report = verify_equivalence(logical, physical, BasisEncoding((2,), (2,), (0, 1)))
        self.assertEqual(report.status, "pass")
        self.assertEqual(report.evidence, "reference-only")
        self.assertAlmostEqual(abs(report.global_phase - phase), 0)

    def test_unused_complement_must_be_unitary_too(self):
        logical = logical_from_source("qutrit q")
        matrix = tuple(tuple(int(row == column and row < 3) for column in range(4)) for row in range(4))
        report = verify_equivalence(logical, ReferenceOperator((4,), matrix), BasisEncoding((3,), (4,), (0, 1, 2)))
        self.assertEqual(report.status, "fail")
        self.assertEqual(report.subspace_residual, 0)
        self.assertEqual(report.leakage_norm, 0)
        self.assertEqual(report.physical_unitarity_error, 1)

    def test_fourier_reference_and_permuted_mixed_identity(self):
        logical = logical_from_source("qutrit q\nfourier q")
        matrix = tuple(tuple(cmath.exp(2j * math.pi * row * column / 3) / math.sqrt(3)
                             if row < 3 and column < 3 else complex(row == column)
                             for column in range(4)) for row in range(4))
        self.assertEqual(verify_equivalence(logical, ReferenceOperator((2, 2), matrix),
                                           BasisEncoding((3,), (2, 2), (0, 1, 2))).status, "pass")
        mixed = logical_from_source("qubit a\nqutrit b")
        physical = lower(parse("qutrit p\nqubit r"))
        encoding = BasisEncoding((2, 3), (3, 2), (5, 0, 4, 1, 3, 2))
        self.assertEqual(verify_equivalence(mixed, physical, encoding).status, "pass")

    def test_unsupported_is_valid_and_allocates_no_operator(self):
        logical = logical_from_source("qubit q")
        physical = CircuitIR(tuple(Register(f"q{i}", 2) for i in range(7)), ())
        encoding = BasisEncoding((2,), (2,) * 7, (0, 1))
        with patch("q3hash.verification.operator_matrix", side_effect=AssertionError("must not allocate")):
            report = verify_equivalence(logical, physical, encoding)
        self.assertEqual(report.status, "unsupported")
        self.assertIsNone(report.subspace_residual)
        self.assertIsNone(report.global_phase)
        large_encoding = BasisEncoding((3,), (32, 32, 32, 32), (0, 1, 2))
        large_physical = CircuitIR(tuple(Register(f"p{i}", 32) for i in range(4)), ())
        with patch("q3hash.verification.operator_matrix", side_effect=AssertionError("must not allocate")):
            large = verify_equivalence(logical_from_source("qutrit q"), large_physical, large_encoding)
        self.assertEqual(large.status, "unsupported")
        with self.assertRaisesRegex(ValueError, "Q3-COMP-001"):
            verify_equivalence(logical, lower(parse("qubit q")), encoding)

    def test_preflight_types_tolerances_and_dense_budgets(self):
        logical = logical_from_source("qubit q")
        physical = logical.ir
        encoding = BasisEncoding((2,), (2,), (0, 1))
        for args in ((None, physical, encoding), (logical, None, encoding), (logical, physical, None)):
            with self.subTest(args=args), self.assertRaisesRegex(TypeError, "Q3-COMP-001"):
                verify_equivalence(*args)
        for tolerance in (True, None, "1e-10"):
            with self.subTest(tolerance=tolerance), self.assertRaisesRegex(TypeError, "Q3-VERIFY-001"):
                verify_equivalence(logical, physical, encoding, tolerance=tolerance)
        for tolerance in (0, -1, float("nan"), float("inf"), 10 ** 1000):
            with self.subTest(tolerance=tolerance), self.assertRaisesRegex(ValueError, "Q3-VERIFY-001"):
                verify_equivalence(logical, physical, encoding, tolerance=tolerance)
        for limit in (0, 65):
            with self.assertRaisesRegex(ValueError, "Q3-VERIFY-002"):
                verify_equivalence(logical, physical, encoding, max_dimension=limit)

    def test_reference_validation_and_nonfinite_computations_cannot_pass(self):
        with self.assertRaisesRegex(TypeError, "Q3-REF-001"):
            ReferenceOperator([2], ((1, 0), (0, 1)))
        with self.assertRaisesRegex(ValueError, "Q3-REF-001"):
            ReferenceOperator((2,), ((1,), (0,)))
        for value in (True, "1", float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Q3-REF-002"):
                ReferenceOperator((2,), ((value, 0), (0, 1)))
        with self.assertRaisesRegex(ValueError, "Q3-REF-003"):
            ReferenceOperator((17, 17), ())
        huge = ReferenceOperator((2,), ((1.7e308, 1.7e308), (1.7e308, 1.7e308)))
        result = verify_equivalence(logical_from_source("qubit q"), huge, BasisEncoding((2,), (2,), (0, 1)))
        self.assertEqual(result.status, "fail")
        self.assertIsNone(result.subspace_residual)


class VerificationCLITests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run([sys.executable, "-m", "q3hash.verify_cli", *map(str, arguments)],
                              cwd=ROOT, capture_output=True, text=True, timeout=15)

    def test_published_reference_example_and_identifiers(self):
        result = self.run_cli("examples/logical-qutrit-shift.q3", "examples/physical-qutrit-shift-binary.q3",
                              "--encoding", "examples/qutrit-binary.encoding.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("verification: pass", result.stdout)
        self.assertIn("q3hash-circuit", result.stdout)
        self.assertEqual(result.stdout.count("semantic SHA-256:"), 3)

    def test_fail_invalid_and_unsupported_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logical = root / "logical.q3"
            physical = root / "physical.q3"
            encoding = root / "encoding.json"
            logical.write_text("qutrit q\nshift q", encoding="utf-8")
            physical.write_text("qudit 4 q\nshift q", encoding="utf-8")
            encoding.write_text(BasisEncoding((3,), (4,), (0, 1, 2)).to_json(), encoding="utf-8")
            failed = self.run_cli(logical, physical, "--encoding", encoding)
            self.assertEqual(failed.returncode, 1, failed.stderr)
            encoding.write_text('{"schema":1,"schema":2}', encoding="utf-8")
            invalid = self.run_cli(logical, physical, "--encoding", encoding)
            self.assertEqual(invalid.returncode, 2)
            self.assertIn("Q3-SER-002", invalid.stderr)
            logical.write_text("qubit q", encoding="utf-8")
            physical.write_text("\n".join(f"qubit q{i}" for i in range(7)), encoding="utf-8")
            encoding.write_text(BasisEncoding((2,), (2,) * 7, (0, 1)).to_json(), encoding="utf-8")
            unsupported = self.run_cli(logical, physical, "--encoding", encoding)
            self.assertEqual(unsupported.returncode, 3, unsupported.stderr)
            self.assertIn("unsupported", unsupported.stdout)
            self.assertNotIn("Traceback", failed.stderr + invalid.stderr + unsupported.stderr)


if __name__ == "__main__":
    unittest.main()
