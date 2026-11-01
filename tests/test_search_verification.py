"""Whole-run preflight, budget precedence and complete candidate coverage."""

from dataclasses import replace
import importlib.util
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from q3hash import (BasisEncoding, CircuitImplementation, SearchConstraints, evaluate_candidates,
                    generate_encodings, logical_from_source)


LOGICAL = "qutrit q\nshift q"
BINARY = "qubit a\nqubit b\nsum a b\nsum b a\nshift b"


class SearchVerificationTests(unittest.TestCase):
    def setUp(self):
        self.logical = logical_from_source(LOGICAL)
        self.constraints = SearchConstraints(max_registers=2, max_physical_size=4)
        self.generation = generate_encodings((3,), self.constraints)
        self.native, self.binary = self.generation.candidates
        self.bindings = (
            CircuitImplementation(self.native.encoding, self.logical.ir),
            CircuitImplementation(self.binary.encoding, logical_from_source(BINARY).ir),
        )

    def run_search(self, **constraints):
        generation = generate_encodings((3,), replace(self.constraints, **constraints))
        return evaluate_candidates(self.logical, generation, self.bindings)

    def test_native_and_binary_whole_run_front_and_exact_ledger(self):
        report = self.run_search()
        self.assertEqual(tuple(row.status for row in report.evaluations), ("pass", "pass"))
        self.assertEqual((report.verification_calls, report.gate_column_steps), (2, 21))
        self.assertEqual(report.front_ids, tuple(c.candidate_id for c in self.generation.candidates))
        self.assertFalse(report.front_is_partial)
        self.assertEqual(report.front_reason, "passing-supplied-circuits-only")
        self.assertEqual(report.status_counts, {"unimplemented": 0, "pass": 2, "fail": 0,
                                              "unsupported": 0, "not-evaluated": 0})

    def test_bindings_are_matched_by_encoding_and_normalised_before_work(self):
        report = evaluate_candidates(self.logical, self.generation, tuple(reversed(self.bindings)))
        self.assertEqual(report.implementations, self.bindings)
        self.assertEqual(report.to_json(), self.run_search().to_json())

    def test_missing_circuits_never_allocate_or_gain_resources(self):
        with patch("q3hash.search_verification.verify_equivalence", side_effect=AssertionError("numeric call")):
            report = evaluate_candidates(self.logical, self.generation, max_dimension=1)
        self.assertEqual(tuple(row.status for row in report.evaluations), ("unimplemented",) * 2)
        self.assertEqual((report.verification_calls, report.gate_column_steps, report.front_ids), (0, 0, ()))
        self.assertTrue(report.front_is_partial)
        self.assertEqual(report.front_reason, "no-passing-supplied-circuits")
        self.assertTrue(all(row.verification is row.resources is None for row in report.evaluations))

    def test_empty_domain_has_explicit_reason_and_still_validates_options(self):
        logical = logical_from_source("qudit 5 q")
        generation = generate_encodings((5,), self.constraints)
        report = evaluate_candidates(logical, generation)
        self.assertEqual(report.front_reason, "no-candidates")
        self.assertEqual((report.evaluations, report.front_ids), ((), ()))
        self.assertFalse(report.front_is_partial)
        for options, error in (({"tolerance": 0}, ValueError), ({"tolerance": True}, TypeError),
                               ({"max_dimension": 0}, ValueError), ({"max_dimension": True}, TypeError)):
            with self.assertRaises(error):
                evaluate_candidates(logical, generation, **options)

    def test_call_budget_skips_later_rows_and_failure_still_consumes_a_call(self):
        report = self.run_search(max_verifications=1)
        self.assertEqual([row.reason_code for row in report.evaluations],
                         ["verified", "verification-call-budget"])
        wrong = CircuitImplementation(self.native.encoding, logical_from_source("qutrit q").ir)
        report = evaluate_candidates(self.logical, report.generation, (wrong, self.bindings[1]))
        self.assertEqual([row.status for row in report.evaluations], ["fail", "not-evaluated"])
        self.assertEqual((report.verification_calls, report.gate_column_steps), (1, 3))
        self.assertEqual(report.front_ids, ())

    def test_skipped_large_call_does_not_charge_and_later_small_call_fits(self):
        generation = generate_encodings((3,), replace(self.constraints, max_gate_column_steps=6),
                                         seed_encodings=(self.binary.encoding,))
        report = evaluate_candidates(self.logical, generation, self.bindings)
        self.assertEqual([row.reason_code for row in report.evaluations], ["gate-column-budget", "verified"])
        self.assertEqual((report.verification_calls, report.gate_column_steps), (1, 6))
        self.assertEqual(report.front_ids, (self.native.candidate_id,))

    def test_exact_work_limit_passes_and_call_limit_precedes_work_limit(self):
        exact = self.run_search(max_gate_column_steps=21)
        self.assertEqual(exact.verification_calls, 2)
        limited = self.run_search(max_gate_column_steps=6, max_verifications=1)
        self.assertEqual(limited.evaluations[1].reason_code, "verification-call-budget")
        self.assertEqual(limited.gate_column_steps, 6)

    def test_identity_work_is_zero_but_each_verification_consumes_a_call(self):
        logical = logical_from_source("qutrit q")
        bindings = (CircuitImplementation(self.native.encoding, logical.ir),
                    CircuitImplementation(self.binary.encoding, logical_from_source("qubit a\nqubit b").ir))
        generation = generate_encodings((3,), replace(self.constraints, max_verifications=1,
                                                     max_gate_column_steps=1))
        report = evaluate_candidates(logical, generation, bindings)
        self.assertEqual([row.status for row in report.evaluations], ["pass", "not-evaluated"])
        self.assertEqual((report.verification_calls, report.gate_column_steps), (1, 0))

    def test_operation_then_dense_limits_precede_global_budgets(self):
        generation = generate_encodings((3,), replace(self.constraints, max_verifications=1,
                                                     max_gate_column_steps=1, max_operations_per_program=1))
        report = evaluate_candidates(self.logical, generation, self.bindings, max_dimension=2)
        self.assertEqual([row.reason_code for row in report.evaluations], ["dense-limit", "operation-limit"])
        self.assertEqual((report.verification_calls, report.gate_column_steps), (0, 0))
        long_logical = logical_from_source(LOGICAL + "\nshift q")
        report = evaluate_candidates(long_logical, generation, self.bindings, max_dimension=1)
        self.assertEqual([row.reason_code for row in report.evaluations], ["operation-limit"] * 2)

    def test_every_binding_is_validated_before_first_call(self):
        foreign = BasisEncoding((3,), (3,), (2, 1, 0))
        invalid_cases = ((self.bindings[0], None), (self.bindings[0], self.bindings[0]),
                         (self.bindings[0], CircuitImplementation(foreign, self.logical.ir)))
        with patch("q3hash.search_verification.verify_equivalence", side_effect=AssertionError("numeric call")):
            for bindings in invalid_cases:
                with self.assertRaisesRegex((TypeError, ValueError), "^Q3-SEARCH-00[13]"):
                    evaluate_candidates(self.logical, self.generation, bindings)

    def test_incompatible_logical_input_and_mutable_public_containers_are_rejected(self):
        for logical, generation, bindings in ((None, self.generation, ()),
                                              (self.logical, None, ()),
                                              (self.logical, self.generation, list(self.bindings))):
            with self.assertRaisesRegex(TypeError, "^Q3-SEARCH-001"):
                evaluate_candidates(logical, generation, bindings)
        with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-003"):
            evaluate_candidates(logical_from_source("qubit q"), self.generation, self.bindings)

    def test_option_errors_are_not_hidden_by_missing_implementations(self):
        for value in (0, -1, math.inf, math.nan, 10**1000):
            with self.assertRaisesRegex(ValueError, "^Q3-VERIFY-001"):
                evaluate_candidates(self.logical, self.generation, tolerance=value)
        for value in (True, "1", None):
            with self.assertRaisesRegex(TypeError, "^Q3-VERIFY-001"):
                evaluate_candidates(self.logical, self.generation, tolerance=value)

    def test_generation_truncation_and_missing_circuits_remain_visible(self):
        generation = generate_encodings((3,), replace(self.constraints, max_candidates=1))
        report = evaluate_candidates(self.logical, generation, self.bindings[:1])
        self.assertEqual(generation.completion, "truncated")
        self.assertEqual(report.status_counts["pass"], 1)
        self.assertTrue(report.front_is_partial)
        missing = evaluate_candidates(self.logical, self.generation, self.bindings[:1])
        self.assertEqual(missing.status_counts["unimplemented"], 1)
        self.assertTrue(missing.front_is_partial)

    def test_objective_subset_changes_front_without_changing_evidence_or_costs(self):
        report = self.run_search(objectives=("physical_registers", "gate_count"))
        self.assertEqual(report.front_ids, (self.native.candidate_id,))
        self.assertEqual(report.verification_calls, 2)

    def test_unexpected_verifier_exception_propagates(self):
        with patch("q3hash.search_verification.verify_equivalence", side_effect=RuntimeError("bug")):
            with self.assertRaisesRegex(RuntimeError, "bug"):
                self.run_search()

    def test_independent_remaining_budget_and_front_oracle(self):
        path = Path(__file__).resolve().parents[1] / "tools/check_search_evaluation.py"
        spec = importlib.util.spec_from_file_location("search_evaluation_audit", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stats = module.audit()
        self.assertEqual(stats["budgeted_runs"], 324)
        self.assertEqual(stats["snapshot_replays"], 324)
        self.assertGreater(stats["verified_circuits"], 100)

    def test_entangling_qutrit_workload_uses_the_complete_nine_state_operator(self):
        logical = logical_from_source("qutrit a\nqutrit b\nfourier a\nsum a b")
        generation = generate_encodings((3, 3), replace(self.constraints, max_physical_size=9))
        self.assertEqual(len(generation.candidates), 1)
        binding = CircuitImplementation(generation.candidates[0].encoding, logical.ir)
        report = evaluate_candidates(logical, generation, (binding,))
        self.assertEqual(report.status_counts["pass"], 1)
        self.assertEqual((report.verification_calls, report.gate_column_steps), (1, 36))
        self.assertEqual(report.evaluations[0].verification.logical_size, 9)
        self.assertEqual(report.evaluations[0].resources.as_tuple(), (2, 3, 0, 2, 1, 2))

    def test_mixed_workload_reordered_physical_axes_requires_the_explicit_seed(self):
        logical = logical_from_source("qubit a\nqutrit b\nfourier a\nsum a b")
        physical = logical_from_source("qutrit b\nqubit a\nfourier a\nsum a b").ir
        encoding = BasisEncoding((2, 3), (3, 2), (0, 2, 4, 1, 3, 5))
        generation = generate_encodings((2, 3), replace(self.constraints, max_physical_size=9),
                                         seed_encodings=(encoding,))
        report = evaluate_candidates(logical, generation, (CircuitImplementation(encoding, physical),))
        self.assertEqual(report.evaluations[0].status, "pass")
        self.assertEqual(report.front_ids, (generation.candidates[0].candidate_id,))
        self.assertEqual(report.gate_column_steps, 24)
        self.assertTrue(report.front_is_partial)


if __name__ == "__main__":
    unittest.main()
