"""Strict replay without numerical work, semantic IDs and evidence integrity."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import itertools
import json
import unittest
from unittest.mock import patch

from q3hash import (BasisEncoding, CircuitIR, CircuitImplementation, LogicalProgram, NumericalEnvironment,
                    SearchConstraints, SearchReport, __version__, evaluate_candidates,
                    generate_encodings, logical_from_source)


class SearchReportTests(unittest.TestCase):
    def setUp(self):
        self.logical = logical_from_source("qutrit q\nshift q")
        self.generation = generate_encodings((3,), SearchConstraints(max_registers=2, max_physical_size=4))
        native, binary = self.generation.candidates
        self.bindings = (CircuitImplementation(native.encoding, self.logical.ir),
                         CircuitImplementation(binary.encoding, logical_from_source(
                             "qubit a\nqubit b\nsum a b\nsum b a\nshift b").ir))
        self.report = evaluate_candidates(self.logical, self.generation, self.bindings)

    def reject(self, mutate, prefix="Q3-"):
        value = deepcopy(self.report.to_dict())
        mutate(value)
        with self.assertRaisesRegex((TypeError, ValueError), "^" + prefix):
            SearchReport.from_dict(value)

    def test_canonical_roundtrip_preserves_evidence_and_distinguishes_recorded_origin(self):
        text = self.report.to_json()
        with patch("q3hash.search_verification.verify_equivalence", side_effect=AssertionError("numeric call")), \
                patch("q3hash.verification.verify_equivalence", side_effect=AssertionError("numeric call")):
            decoded = SearchReport.from_json(text)
        self.assertEqual(decoded, self.report)
        self.assertEqual(decoded.to_json(), text)
        self.assertEqual((self.report.evidence_origin, decoded.evidence_origin), ("computed", "recorded"))
        self.assertNotIn("evidence_origin", json.loads(text))

    def test_program_ids_use_existing_canonical_bytes(self):
        expected = hashlib.sha256(self.logical.to_json().encode()).hexdigest()
        self.assertEqual(self.report.logical_id, expected)
        for binding, stored in zip(self.report.implementations, self.report.to_dict()["implementations"]):
            self.assertEqual(stored["physical_id"], hashlib.sha256(
                LogicalProgram(binding.circuit).to_json().encode()).hexdigest())
        self.assertEqual(self.report.engine_version, __version__)
        self.assertEqual(self.report.verifier_version, "q3hash.operator-verification-v1")
        self.assertIsNone(self.report.source_commit)

    def test_immutable_models_and_detached_wire_objects(self):
        with self.assertRaisesRegex(TypeError, "^Q3-SEARCH-005"):
            SearchReport(status="pass")
        with self.assertRaises(FrozenInstanceError):
            self.report.verification_calls = 0
        with self.assertRaises(FrozenInstanceError):
            self.report.numerical_environment.machine = "other"
        value = self.report.to_dict()
        value["evaluations"][0]["resources"]["gate_count"] = 99
        value["numerical_environment"]["system"] = "other"
        counts = self.report.status_counts
        counts["pass"] = 0
        self.assertEqual(self.report.status_counts["pass"], 2)
        self.assertEqual(self.report.evaluations[0].resources.gate_count, 1)

    def test_unknown_missing_fields_and_noninteger_schema_version_are_rejected(self):
        for key in self.report.to_dict():
            self.reject(lambda value, k=key: value.pop(k), "Q3-SER-003")
        self.reject(lambda value: value.update(extra=True), "Q3-SER-003")
        for version in (True, 1.0, 2):
            self.reject(lambda value, v=version: value.update(schema_version=v), "Q3-SER-004")
        self.reject(lambda value: value.update(schema="q3hash.other"), "Q3-SER-004")
        self.reject(lambda value: value["implementations"][0].update(extra=1), "Q3-SER-003")
        self.reject(lambda value: value["evaluations"][0]["verification"].pop("reason"), "Q3-SER-003")
        self.reject(lambda value: value["numerical_environment"].update(hostname="private"), "Q3-SER-003")

    def test_duplicate_json_keys_nonfinite_constants_and_invalid_unicode_are_rejected(self):
        text = self.report.to_json()
        for altered in ('{"schema_version":1,' + text[1:],
                        text.replace('"tolerance":1e-10', '"tolerance":NaN', 1),
                        text.replace('"engine_version":"' + __version__ + '"', '"engine_version":"\\ud800"')):
            with self.assertRaisesRegex(ValueError, "^Q3-SER-00[12]"):
                SearchReport.from_json(altered)
        self.reject(lambda value: value.update(engine_version="\ud800"), "Q3-SER-001")

    def test_tampered_program_ids_and_candidate_ids_are_rejected(self):
        self.reject(lambda value: value.update(logical_id="0" * 64), "Q3-SEARCH-005")
        self.reject(lambda value: value["implementations"][0].update(physical_id="0" * 64), "Q3-SEARCH-005")
        self.reject(lambda value: value["implementations"][0].update(candidate_id="0" * 64), "Q3-SEARCH-003")
        self.reject(lambda value: value["evaluations"][0].update(candidate_id="0" * 64), "Q3-SEARCH-005")
        self.reject(lambda value: value["logical_program"]["operations"].clear(), "Q3-SEARCH-005")
        self.reject(lambda value: value["implementations"][0]["physical_program"]["operations"].clear(), "Q3-SEARCH-005")

    def test_generation_is_replayed_and_nested_schemas_remain_strict(self):
        self.reject(lambda value: value["generation"].update(mapping_attempts=0), "Q3-SEARCH-005")
        self.reject(lambda value: value["generation"]["candidates"].reverse(), "Q3-SEARCH-005")
        self.reject(lambda value: value["generation"]["constraints"].update(schema_version=2), "Q3-SER-004")

    def test_implementation_and_evaluation_order_counts_and_uniqueness_are_checked(self):
        self.reject(lambda value: value["implementations"].reverse(), "Q3-SEARCH-005")
        self.reject(lambda value: value["implementations"].__setitem__(1, deepcopy(value["implementations"][0])),
                    "Q3-SEARCH-003")
        self.reject(lambda value: value["evaluations"].reverse(), "Q3-SEARCH-005")
        self.reject(lambda value: value["evaluations"].pop(), "Q3-SEARCH-005")
        self.reject(lambda value: value["evaluations"].append(deepcopy(value["evaluations"][0])), "Q3-SEARCH-005")

    def test_ledger_types_counts_scope_and_front_order_are_recomputed(self):
        for name in ("verification_calls", "gate_column_steps"):
            for item in (True, 0, 2.0, -1):
                self.reject(lambda value, key=name, v=item: value.update({key: v}), "Q3-SEARCH-005")
        self.reject(lambda value: value.update(ranking_scope="globally-optimal"), "Q3-SEARCH-005")
        self.reject(lambda value: value["front_ids"].reverse(), "Q3-SEARCH-005")
        self.reject(lambda value: value["front_ids"].pop(), "Q3-SEARCH-005")
        self.reject(lambda value: value["front_ids"].append("0" * 64), "Q3-SEARCH-005")
        self.reject(lambda value: value["front_ids"].__setitem__(1, value["front_ids"][0]), "Q3-SEARCH-005")

    def test_fabricated_costs_and_noninteger_count_values_are_rejected(self):
        for item in (False, 1.0, 0, 5):
            self.reject(lambda value, v=item: value["evaluations"][0]["resources"].update(gate_count=v),
                        "Q3-SEARCH-005")
        self.reject(lambda value: value["evaluations"][0].update(resources=None), "Q3-SER-003")
        self.reject(lambda value: value["evaluations"][0]["resources"].update(free_gates=0), "Q3-SER-003")

    def test_pass_requires_circuit_evidence_all_metrics_and_one_normalised_phase(self):
        mutations = [{"status": "fail"}, {"evidence": "reference-only"}, {"tolerance": 1e-9},
                     {"subspace_residual": None}, {"leakage_norm": -1}, {"logical_unitarity_error": True},
                     {"physical_unitarity_error": 1e-3}, {"global_phase": None}, {"global_phase": [2, 0]},
                     {"global_phase": [0]}, {"global_phase": [True, 0]}, {"global_phase": [float("inf"), 0]},
                     {"global_phase": [1.7e308, 1.7e308]}]
        for fields in mutations:
            self.reject(lambda value, f=fields: value["evaluations"][0]["verification"].update(f), "Q3-SEARCH-005")

    def test_outer_status_and_reason_must_agree_with_snapshot(self):
        for fields in ({"status": "fail"}, {"status": ["pass"]}, {"reason_code": "equivalence-failed"},
                       {"reason_code": False}):
            self.reject(lambda value, f=fields: value["evaluations"][0].update(f), "Q3-SEARCH-005")

    def test_failures_roundtrip_without_resources_and_do_not_imply_partial_work(self):
        wrong = CircuitImplementation(self.bindings[0].encoding, logical_from_source("qutrit q").ir)
        report = evaluate_candidates(self.logical, self.generation, (wrong, self.bindings[1]))
        self.assertEqual([row.status for row in report.evaluations], ["fail", "pass"])
        self.assertFalse(report.front_is_partial)
        self.assertEqual(SearchReport.from_json(report.to_json()), report)
        value = report.to_dict()
        value["evaluations"][0]["resources"] = self.report.evaluations[0].resources.to_dict()
        with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-005"):
            SearchReport.from_dict(value)

    def test_nonfinite_failure_snapshot_has_all_null_metrics_and_phase(self):
        good = self.report.evaluations[0].verification
        failed = replace(good, status="fail", reason="nonfinite computed metric", global_phase=None,
                         subspace_residual=None, leakage_norm=None, logical_unitarity_error=None,
                         physical_unitarity_error=None)
        with patch("q3hash.search_verification.verify_equivalence", return_value=failed):
            report = evaluate_candidates(self.logical, self.generation, self.bindings[:1])
        self.assertEqual(report.evaluations[0].reason_code, "nonfinite-metrics")
        self.assertEqual(SearchReport.from_json(report.to_json()), report)
        value = report.to_dict()
        value["evaluations"][0]["verification"]["leakage_norm"] = 0
        with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-005"):
            SearchReport.from_dict(value)

    def test_budget_skips_cannot_smuggle_passes_and_call_plan_is_replayed(self):
        generation = generate_encodings((3,), replace(self.generation.constraints, max_verifications=1))
        report = evaluate_candidates(self.logical, generation, self.bindings)
        self.assertEqual(SearchReport.from_json(report.to_json()), report)
        value = report.to_dict()
        value["evaluations"][1] = self.report.to_dict()["evaluations"][1]
        with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-005"):
            SearchReport.from_dict(value)
        value = self.report.to_dict()
        value["evaluations"][1].update(status="not-evaluated", reason_code="verification-call-budget",
                                         verification=None, resources=None)
        with self.assertRaisesRegex(ValueError, "^Q3-SER-003"):
            SearchReport.from_dict(value)

    def test_no_call_statuses_roundtrip_and_cannot_contain_costs(self):
        missing = evaluate_candidates(self.logical, self.generation)
        unsupported = evaluate_candidates(self.logical, self.generation, self.bindings, max_dimension=2)
        work_generation = generate_encodings((3,), replace(self.generation.constraints, max_gate_column_steps=1))
        skipped = evaluate_candidates(self.logical, work_generation, self.bindings)
        for report in (missing, unsupported, skipped):
            self.assertEqual(SearchReport.from_json(report.to_json()), report)
            value = report.to_dict()
            value["evaluations"][0]["resources"] = self.report.evaluations[0].resources.to_dict()
            with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-005"):
                SearchReport.from_dict(value)

    def test_historical_provenance_is_preserved_without_runtime_substitution(self):
        value = self.report.to_dict()
        value.update(engine_version="historic-engine", verifier_version="historic-verifier", source_commit="a" * 40)
        value["numerical_environment"] = dict(python_implementation="OtherPython", python_version="1.2.3",
                                              system="OtherOS", machine="other-arch", libc=None,
                                              numeric_backend="other-numerics")
        decoded = SearchReport.from_dict(value)
        self.assertEqual(decoded.to_dict(), value)
        self.assertEqual(decoded.evidence_origin, "recorded")
        self.assertIsNone(decoded.numerical_environment.libc)

    def test_provenance_rejects_empty_strings_wrong_types_and_invalid_commit(self):
        for name in ("engine_version", "verifier_version"):
            for item in ("", 1, None, []):
                self.reject(lambda value, k=name, v=item: value.update({k: v}), "Q3-SEARCH-005")
        for item in ("A" * 40, "a" * 39, False, 0):
            self.reject(lambda value, v=item: value.update(source_commit=v), "Q3-SEARCH-005")
        for name in self.report.numerical_environment.to_dict():
            self.reject(lambda value, k=name: value["numerical_environment"].update({k: ""}), "Q3-SEARCH-005")
        with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-005"):
            NumericalEnvironment("Python", "1", "OS", "arch", None, False)

    def test_oversized_logical_and_physical_program_ids_fail_before_verification(self):
        long_ir = CircuitIR(self.logical.ir.registers, self.logical.ir.operations * 30000)
        with patch("q3hash.search_verification.verify_equivalence", side_effect=AssertionError("numeric call")):
            with self.assertRaisesRegex(ValueError, "^Q3-SER-001"):
                evaluate_candidates(LogicalProgram(long_ir), self.generation, self.bindings)
            with self.assertRaisesRegex(ValueError, "^Q3-SER-001"):
                evaluate_candidates(self.logical, self.generation,
                                    (self.bindings[1], CircuitImplementation(self.bindings[0].encoding, long_ir)))

    def test_large_valid_report_hits_wire_limit_without_losing_candidates(self):
        seeds = tuple(BasisEncoding((3,), (2,) * 6, mapping)
                      for mapping in itertools.islice(itertools.permutations(range(64), 3), 2048))
        constraints = SearchConstraints(allowed_dimensions=(2,), max_registers=6, max_physical_size=64,
                                        max_candidates=2048)
        generation = generate_encodings((3,), constraints, seed_encodings=seeds)
        report = evaluate_candidates(self.logical, generation)
        self.assertEqual(len(report.evaluations), 2048)
        with self.assertRaisesRegex(ValueError, "^Q3-SER-001"):
            report.to_json()
        self.assertEqual(report.status_counts["unimplemented"], 2048)

    def test_verified_ties_survive_in_generation_order_in_the_serialized_front(self):
        encoding = BasisEncoding((3,), (3,), (1, 2, 0))
        generation = generate_encodings((3,), self.generation.constraints, seed_encodings=(encoding,))
        binding = CircuitImplementation(encoding, self.logical.ir)
        report = evaluate_candidates(self.logical, generation, self.bindings + (binding,))
        self.assertEqual(len(report.front_ids), 3)
        self.assertEqual(report.front_ids, tuple(candidate.candidate_id for candidate in generation.candidates))
        self.assertEqual(SearchReport.from_json(report.to_json()), report)

    def test_complete_failure_front_is_empty_with_explicit_reason(self):
        wrong = (CircuitImplementation(self.bindings[0].encoding, logical_from_source("qutrit q").ir),
                 CircuitImplementation(self.bindings[1].encoding, logical_from_source("qubit a\nqubit b").ir))
        report = evaluate_candidates(self.logical, self.generation, wrong)
        self.assertEqual(report.front_ids, ())
        self.assertEqual(report.front_reason, "no-passing-supplied-circuits")
        self.assertFalse(report.front_is_partial)
        self.assertEqual(report.status_counts["fail"], 2)
        self.assertEqual(SearchReport.from_json(report.to_json()), report)

    def test_empty_and_operation_unsupported_reports_roundtrip(self):
        logical = logical_from_source("qudit 5 q")
        empty = evaluate_candidates(logical, generate_encodings((5,), self.generation.constraints))
        generation = generate_encodings((3,), replace(self.generation.constraints, max_operations_per_program=1))
        operation = evaluate_candidates(self.logical, generation, self.bindings)
        self.assertEqual(operation.evaluations[1].reason_code, "operation-limit")
        for report in (empty, operation):
            self.assertEqual(SearchReport.from_json(report.to_json()), report)


if __name__ == "__main__":
    unittest.main()
