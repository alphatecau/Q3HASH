"""Verified-circuit eligibility, strict dominance and reproducible Pareto fronts."""

from dataclasses import FrozenInstanceError, replace
import importlib.util
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from q3hash import (BasisEncoding, CandidateEvaluation, CircuitImplementation, EncodingCandidate,
                    ReferenceOperator, RESOURCE_OBJECTIVES, ResourceCounts, VerificationReport,
                    dominates, evaluate_candidate, logical_from_source, pareto_front)


LOGICAL = "qutrit q\nshift q\n"
BINARY = "qubit a\nqubit b\nsum a b\nsum b a\nshift b\n"


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.logical = logical_from_source(LOGICAL)
        self.native = EncodingCandidate(BasisEncoding((3,), (3,), (0, 1, 2)), "flat-prefix")
        self.binary = EncodingCandidate(BasisEncoding((3,), (2, 2), (0, 1, 2)), "flat-prefix")
        self.binary_ir = logical_from_source(BINARY).ir

    def native_result(self, **options):
        return evaluate_candidate(self.logical, self.native,
                                  CircuitImplementation(self.native.encoding, self.logical.ir), **options)

    def binary_result(self, **options):
        return evaluate_candidate(self.logical, self.binary,
                                  CircuitImplementation(self.binary.encoding, self.binary_ir), **options)

    def test_native_and_binary_shift_have_a_real_default_tradeoff(self):
        a, b = self.native_result(), self.binary_result()
        self.assertEqual(a.resources.as_tuple(), (1, 3, 0, 1, 0, 1))
        self.assertEqual(b.resources.as_tuple(), (2, 2, 1, 3, 2, 3))
        self.assertEqual(pareto_front((a, b), RESOURCE_OBJECTIVES), (a.candidate_id, b.candidate_id))
        subset = tuple(name for name in RESOURCE_OBJECTIVES if name != "max_register_dimension")
        self.assertEqual(pareto_front((a, b), subset), (a.candidate_id,))
        self.assertEqual(pareto_front((b, a), RESOURCE_OBJECTIVES), (b.candidate_id, a.candidate_id))

    def test_ties_survive_and_later_dominance_removes_only_dominated_rows(self):
        a = self.native_result()
        seed = EncodingCandidate(BasisEncoding((3,), (3,), (1, 2, 0)), "seed", seed_index=0)
        tie = evaluate_candidate(self.logical, seed, CircuitImplementation(seed.encoding, self.logical.ir))
        dominated = EncodingCandidate(BasisEncoding((3,), (2, 2), (1, 2, 0)), "seed", seed_index=1)
        padded = logical_from_source(BINARY + "shift a\nshift a\n").ir
        c = evaluate_candidate(self.logical, dominated, CircuitImplementation(dominated.encoding, padded))
        b = self.binary_result()
        self.assertEqual(c.status, "pass")
        self.assertEqual(pareto_front((c, a, tie, b), RESOURCE_OBJECTIVES),
                         (a.candidate_id, tie.candidate_id, b.candidate_id))
        self.assertFalse(dominates(a.resources, tie.resources, RESOURCE_OBJECTIVES))

    def test_nonpassing_rows_have_no_costs_and_never_enter_the_front(self):
        missing = evaluate_candidate(self.logical, self.native)
        bad = EncodingCandidate(BasisEncoding((3,), (4,), (0, 1, 2)), "flat-prefix")
        wrong = evaluate_candidate(self.logical, bad,
            CircuitImplementation(bad.encoding, logical_from_source("qudit 4 p\nshift p").ir))
        unsupported = self.binary_result(max_dimension=3)
        self.assertEqual((missing.status, wrong.status, unsupported.status),
                         ("unimplemented", "fail", "unsupported"))
        self.assertTrue(all(value.resources is None for value in (missing, wrong, unsupported)))
        self.assertEqual(pareto_front((missing, wrong), RESOURCE_OBJECTIVES), ())
        self.assertEqual(pareto_front((unsupported,), RESOURCE_OBJECTIVES), ())
        self.assertEqual(pareto_front((), RESOURCE_OBJECTIVES), ())

    def test_relative_phase_error_remains_a_failure(self):
        logical = logical_from_source("qubit q")
        candidate = EncodingCandidate(BasisEncoding((2,), (2,), (0, 1)), "flat-prefix")
        physical = logical_from_source("qubit p\nfourier p\nshift p\nfourier p").ir
        value = evaluate_candidate(logical, candidate, CircuitImplementation(candidate.encoding, physical))
        self.assertEqual(value.status, "fail")
        self.assertEqual(value.reason_code, "equivalence-failed")
        self.assertIsNone(value.resources)

    def test_operation_limit_precedes_dense_limit_without_any_verifier_call(self):
        with patch("q3hash.search_verification.verify_equivalence", side_effect=AssertionError("numeric call")):
            operation = self.binary_result(max_dimension=2, max_operations_per_program=1)
            dense = self.binary_result(max_dimension=3)
            missing = evaluate_candidate(self.logical, self.binary, max_dimension=2,
                                         max_operations_per_program=1)
        self.assertEqual(operation.reason_code, "operation-limit")
        self.assertEqual(dense.reason_code, "dense-limit")
        self.assertEqual(missing.reason_code, "no-implementation")
        self.assertTrue(all(value.verification_calls == value.gate_column_steps == 0
                            for value in (operation, dense, missing)))

    def test_logical_operation_limit_is_checked_too(self):
        logical = logical_from_source(LOGICAL + "shift q\nshift q\n")
        with patch("q3hash.search_verification.verify_equivalence", side_effect=AssertionError("numeric call")):
            value = evaluate_candidate(logical, self.native,
                CircuitImplementation(self.native.encoding, self.logical.ir), max_operations_per_program=2)
        self.assertEqual(value.reason_code, "operation-limit")

    def test_inputs_and_implementation_compatibility_are_checked_first(self):
        with self.assertRaisesRegex(TypeError, "^Q3-SEARCH-003"):
            CircuitImplementation(self.native.encoding, "qutrit q")
        with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-003"):
            CircuitImplementation(self.native.encoding, self.binary_ir)
        with self.assertRaisesRegex(TypeError, "^Q3-SEARCH-001"):
            evaluate_candidate(None, self.native)
        with self.assertRaisesRegex(TypeError, "^Q3-SEARCH-001"):
            evaluate_candidate(self.logical, self.native, self.logical.ir)
        with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-003"):
            evaluate_candidate(logical_from_source("qubit q"), self.native)
        with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-003"):
            evaluate_candidate(self.logical, self.native, CircuitImplementation(self.binary.encoding, self.binary_ir))

    def test_verifier_options_and_operation_limits_are_strict(self):
        for value in (True, "1", None):
            with self.assertRaisesRegex(TypeError, "^Q3-VERIFY-001"):
                self.native_result(tolerance=value)
        for value in (0, -1, math.inf, math.nan, 10**1000):
            with self.assertRaisesRegex(ValueError, "^Q3-VERIFY-001"):
                self.native_result(tolerance=value)
        for value in (True, 2.0, "2"):
            with self.assertRaisesRegex(TypeError, "^Q3-VERIFY-002"):
                self.native_result(max_dimension=value)
        for value in (0, 65):
            with self.assertRaisesRegex(ValueError, "^Q3-VERIFY-002"):
                self.native_result(max_dimension=value)
        for value in (True, 1.0, "1"):
            with self.assertRaisesRegex(TypeError, "^Q3-SEARCH-001"):
                self.native_result(max_operations_per_program=value)
        for value in (0, 16385):
            with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-001"):
                self.native_result(max_operations_per_program=value)

    def test_result_is_immutable_and_cannot_accept_pass_or_cost_claims(self):
        with self.assertRaisesRegex(TypeError, "^Q3-SEARCH-005"):
            CandidateEvaluation(status="pass", resources=ResourceCounts(1, 3, 0, 0, 0, 0))
        value = self.native_result()
        with self.assertRaises(FrozenInstanceError):
            value.status = "fail"
        with self.assertRaises(TypeError):
            self.native_result(resources=ResourceCounts(1, 3, 0, 0, 0, 0))
        snapshot = value.to_dict()
        self.assertEqual(set(snapshot), {"candidate_id", "status", "reason_code", "verification", "resources"})
        snapshot["resources"]["gate_count"] = 0
        snapshot["verification"]["global_phase"][0] = 0
        self.assertEqual(value.resources.gate_count, 1)
        self.assertEqual(value.verification.global_phase, 1 + 0j)
        self.assertEqual((value.verification_calls, value.gate_column_steps), (1, 6))
        self.assertEqual(self.binary_result().gate_column_steps, 15)

    def test_comparison_rejects_mixed_workloads_and_settings(self):
        native = self.native_result()
        identity = logical_from_source("qutrit q")
        other = evaluate_candidate(identity, self.binary,
                    CircuitImplementation(self.binary.encoding, logical_from_source("qubit a\nqubit b").ir))
        with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-003"):
            pareto_front((native, other), RESOURCE_OBJECTIVES)
        for options in ({"tolerance": 1e-9}, {"max_dimension": 4}, {"max_operations_per_program": 8}):
            with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-001"):
                pareto_front((native, self.binary_result(**options)), RESOURCE_OBJECTIVES)

    def test_duplicate_ids_and_invalid_later_items_are_rejected_before_filtering(self):
        native = self.native_result()
        missing = evaluate_candidate(self.logical, self.native)
        with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-003"):
            pareto_front((native, native), RESOURCE_OBJECTIVES)
        with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-003"):
            pareto_front((native, missing), RESOURCE_OBJECTIVES)
        with self.assertRaisesRegex(TypeError, "^Q3-SEARCH-001"):
            pareto_front((native, None), RESOURCE_OBJECTIVES)
        with self.assertRaisesRegex(TypeError, "^Q3-SEARCH-001"):
            pareto_front([native], RESOURCE_OBJECTIVES)
        with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-001"):
            pareto_front((native,) * 4097, RESOURCE_OBJECTIVES)

    def test_collision_is_not_treated_as_a_duplicate(self):
        with patch("q3hash.search._encoding_id", return_value="0" * 64):
            a = EncodingCandidate(self.native.encoding, "flat-prefix")
            b = EncodingCandidate(self.binary.encoding, "flat-prefix")
        av = evaluate_candidate(self.logical, a, CircuitImplementation(a.encoding, self.logical.ir))
        bv = evaluate_candidate(self.logical, b, CircuitImplementation(b.encoding, self.binary_ir))
        with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-004"):
            pareto_front((av, bv), RESOURCE_OBJECTIVES)

    def test_reference_matrices_cannot_enter_the_executable_comparison(self):
        reference = ReferenceOperator((3,), ((1, 0, 0), (0, 1, 0), (0, 0, 1)))
        with self.assertRaisesRegex(TypeError, "^Q3-SEARCH-003"):
            CircuitImplementation(self.native.encoding, reference)
        with self.assertRaisesRegex(TypeError, "^Q3-SEARCH-001"):
            evaluate_candidate(self.logical, self.native, reference)

    def test_corrupt_or_nonfinite_verifier_output_cannot_become_a_pass(self):
        valid = self.native_result().verification
        for report in (replace(valid, evidence="reference-only"), replace(valid, subspace_residual=math.nan),
                       replace(valid, subspace_residual=-1), replace(valid, global_phase=2 + 0j),
                       replace(valid, logical_size=2), replace(valid, logical_size=3.0),
                       replace(valid, subspace_residual=10**1000),
                       replace(valid, global_phase=complex(1.7e308, 1.7e308)),
                       replace(valid, status="unsupported"),
                       replace(valid, status="fail"), replace(valid, tolerance=1e-9)):
            with patch("q3hash.search_verification.verify_equivalence", return_value=report):
                with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-005"):
                    self.native_result()
        nonfinite = VerificationReport("fail", "Nonfinite numerical calculation", "q3hash-circuit", 3, 3, 1e-10)
        with patch("q3hash.search_verification.verify_equivalence", return_value=nonfinite):
            value = self.native_result()
        self.assertEqual(value.reason_code, "nonfinite-metrics")
        self.assertIsNone(value.resources)
        self.assertEqual(pareto_front((value,), RESOURCE_OBJECTIVES), ())

    def test_unexpected_verifier_exceptions_are_not_reclassified(self):
        with patch("q3hash.search_verification.verify_equivalence", side_effect=RuntimeError("defect")):
            with self.assertRaisesRegex(RuntimeError, "defect"):
                self.native_result()

    def test_raw_dominance_uses_only_exact_selected_integer_counts(self):
        a, b = ResourceCounts(1, 3, 0, 1, 0, 1), ResourceCounts(2, 2, 1, 3, 2, 3)
        self.assertFalse(dominates(a, b, RESOURCE_OBJECTIVES))
        self.assertTrue(dominates(a, b, ("gate_count",)))
        self.assertFalse(dominates(a, a, RESOURCE_OBJECTIVES))
        with self.assertRaisesRegex(TypeError, "^Q3-SEARCH-001"):
            dominates(a, {}, RESOURCE_OBJECTIVES)
        for names in ((), ("unknown",), ("gate_count", "gate_count"), (True,)):
            with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-001"):
                pareto_front((), names)

    def test_independent_resource_and_pareto_audit(self):
        path = Path(__file__).resolve().parents[1] / "tools/check_resources_comparison.py"
        spec = importlib.util.spec_from_file_location("resource_comparison_oracle", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stats = module.audit()
        self.assertEqual(stats, {"resource_circuits": 2433, "verified_fronts": 189,
                                "integer_dominance_pairs": 1008})


if __name__ == "__main__":
    unittest.main()
