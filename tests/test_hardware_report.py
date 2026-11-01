"""Computed evidence, complete hardware fronts and strict recorded replay."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import itertools
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from q3hash import (BasisEncoding, CircuitImplementation, HardwareContext, HardwareEvaluation, HardwarePlacement,
                    HardwareProfile, HardwareReport, SearchConstraints, SearchReport, TimeRange, assess_hardware,
                    evaluate_candidates, generate_encodings, hardware_front, logical_from_source)
from q3hash._serialization import MAX_JSON_BYTES


FIXTURE = json.loads((Path(__file__).resolve().parents[1] / "benchmarks/hardware-cost-v1.json").read_text())


def source_report(*, missing=False, constraints=None, physical=None, max_dimension=64):
    logical = logical_from_source("qutrit q\nshift q")
    generation = generate_encodings((3,), constraints or SearchConstraints(max_registers=2, max_physical_size=4))
    implementations = []
    for candidate in generation.candidates:
        circuit = logical.ir if candidate.encoding.physical_dimensions == (3,) else logical_from_source(
            "qubit a\nqubit b\nsum a b\nsum b a\nshift b").ir
        if physical is not None:
            circuit = physical
        if not missing:
            implementations.append(CircuitImplementation(candidate.encoding, circuit))
    return evaluate_candidates(logical, generation, tuple(implementations), max_dimension=max_dimension)


def assess(source=None, *, target="hybrid", context=None, placed=True):
    source = source_report() if source is None else source
    profile = HardwareProfile.from_dict(FIXTURE["profiles"][target])
    context = HardwareContext.from_dict(FIXTURE["context"]) if context is None else context
    placements = tuple(HardwarePlacement(row.candidate_id, (0,) if row.candidate.encoding.physical_dimensions == (3,) else (1, 2))
                       for row in source.evaluations if placed and row.implementation is not None)
    return assess_hardware(source, profile, placements, context)


class HardwareReportTests(unittest.TestCase):
    def assert_code(self, kind, code, call):
        with self.assertRaisesRegex(kind, "^" + code):
            call()

    def test_complete_computed_report_derives_front_scope_counts_and_ids(self):
        source = source_report()
        report = assess(source)
        self.assertEqual([r.status for r in report.evaluations], ["supported", "supported"])
        self.assertEqual(report.gate_checks, 4)
        self.assertEqual(report.status_counts["supported"], 2)
        self.assertEqual(report.front_ids, (report.evaluations[0].placement_id,))
        self.assertEqual(hardware_front(report), report.front_ids)
        self.assertEqual(report.ranking_scope, "verified-supplied-placements-under-one-profile")
        self.assertEqual(report.schedule_scope, "exclusive-sites-critical-path-v1")
        self.assertEqual(report.front_reason, report.ranking_scope)
        self.assertFalse(report.front_is_partial)
        self.assertEqual(report.evidence_origin, "computed")
        self.assertIs(report.source_report, source)
        self.assertEqual(report.source_id, hashlib.sha256(source.to_json().encode()).hexdigest())
        self.assertEqual((source.verification_calls, source.gate_column_steps), (2, 21))

    def test_producer_accepts_no_cost_status_or_front_claims(self):
        self.assert_code(TypeError, "Q3-HARD-005", lambda: HardwareReport(front_ids=()))
        self.assert_code(TypeError, "Q3-HARD-005", lambda: HardwareEvaluation(status="supported"))
        self.assert_code(TypeError, "Q3-HARD-001", lambda: hardware_front(()))
        self.assert_code(TypeError, "Q3-HARD-001", lambda: assess_hardware({}, {}, (), {}))

    def test_recorded_source_is_rejected_before_any_cost_or_profile_work(self):
        source = SearchReport.from_json(source_report().to_json())
        with patch("q3hash.hardware_report._evaluate_costs", side_effect=AssertionError("cost work")):
            self.assert_code(ValueError, "Q3-HARD-005", lambda: assess(source))

    def test_source_structural_tampering_is_rejected_before_cost_work(self):
        source = source_report()
        object.__setattr__(source, "gate_column_steps", 0)
        with patch("q3hash.hardware_report._evaluate_costs", side_effect=AssertionError("cost work")):
            with self.assertRaises(ValueError):
                assess(source)

    def test_input_placement_order_is_normalised_to_source_order(self):
        report = assess()
        reversed_report = assess_hardware(report.source_report, report.profile, tuple(reversed(report.placements)), report.context)
        self.assertEqual(reversed_report.to_json(), report.to_json())

    def test_late_invalid_duplicate_unknown_and_unimplemented_placements_fail_preflight(self):
        report = assess()
        first, second = report.placements
        cases = ((first, first), (first, replace(second, site_indices=(0,))),
                 (first, HardwarePlacement("0" * 64, (0,))))
        with patch("q3hash.hardware_report._evaluate_costs", side_effect=AssertionError("cost work")):
            for placements in cases:
                self.assert_code(ValueError, "Q3-HARD-003",
                                 lambda: assess_hardware(report.source_report, report.profile, placements, report.context))
            missing = source_report(missing=True)
            self.assert_code(ValueError, "Q3-HARD-003",
                lambda: assess_hardware(missing, report.profile, (HardwarePlacement(missing.evaluations[0].candidate_id, (0,)),), report.context))
        self.assert_code(TypeError, "Q3-HARD-001",
                         lambda: assess_hardware(report.source_report, report.profile, list(report.placements), report.context))

    def test_placement_identity_collisions_are_rejected_before_costs(self):
        report = assess()
        with patch.object(HardwarePlacement, "identifier", return_value="0" * 64), \
                patch("q3hash.hardware_report._evaluate_costs", side_effect=AssertionError("cost work")):
            self.assert_code(ValueError, "Q3-HARD-004",
                lambda: assess_hardware(report.source_report, report.profile, report.placements, report.context))

    def test_each_missing_source_retains_an_ineligible_row(self):
        report = assess(source_report(missing=True))
        self.assertEqual([r.status for r in report.evaluations], ["ineligible", "ineligible"])
        self.assertTrue(all(r.placement_id is None and r.costs is None for r in report.evaluations))
        self.assertEqual(report.front_reason, "no-verified-supplied-circuits")
        self.assertTrue(report.front_is_partial)
        self.assertEqual(report.gate_checks, 0)

    def test_failed_source_never_gets_hardware_costs_even_if_native_supported(self):
        constraints = SearchConstraints(allowed_dimensions=(3,), max_registers=1, max_physical_size=3)
        report = assess(source_report(constraints=constraints, physical=logical_from_source("qutrit q").ir))
        self.assertEqual(report.evaluations[0].reason_code, "source-fail")
        self.assertIsNone(report.evaluations[0].costs)
        self.assertFalse(report.front_is_partial)

    def test_source_call_and_work_skips_remain_partial_ineligible_evidence(self):
        for changes in (dict(max_verifications=1), dict(max_gate_column_steps=6)):
            source = source_report(constraints=SearchConstraints(max_registers=2, max_physical_size=4, **changes))
            report = assess(source)
            self.assertEqual(report.evaluations[1].reason_code, "source-not-evaluated")
            self.assertTrue(report.front_is_partial)
            self.assertEqual(report.gate_checks, 1)

    def test_source_dense_limit_is_not_upgraded_to_supported_hardware_evidence(self):
        report = assess(source_report(max_dimension=3))
        self.assertEqual(report.evaluations[1].reason_code, "source-unsupported")
        self.assertIsNone(report.evaluations[1].costs)
        self.assertTrue(report.front_is_partial)

    def test_interval_overlap_contact_ties_and_strict_separation(self):
        logical = logical_from_source("qutrit q\nshift q")
        generation = generate_encodings((3,), SearchConstraints(allowed_dimensions=(3,), max_registers=1, max_physical_size=3),
            seed_encodings=(BasisEncoding((3,), (3,), (1, 2, 0)),))
        source = evaluate_candidates(logical, generation,
            tuple(CircuitImplementation(c.encoding, logical.ir) for c in generation.candidates))
        target = HardwareProfile.from_dict(FIXTURE["profiles"]["hybrid"])
        placements = tuple(HardwarePlacement(row.candidate_id, (0,) if i == 0 else (3,)) for i, row in enumerate(source.evaluations))
        context = replace(HardwareContext.from_dict(FIXTURE["context"]), objectives=("critical_path_ps",))
        for duration, indices in ((TimeRange(50000, 70000), (0, 1)), (TimeRange(60000, 70000), (0, 1)),
                                  (TimeRange(40000, 60000), (0, 1)), (TimeRange(60001, 70000), (0,))):
            bindings = tuple(replace(b, duration=duration) if b.kind.value == "shift" and b.sites == (3,) else b
                             for b in target.bindings)
            report = assess_hardware(source, replace(target, bindings=bindings), placements, context)
            self.assertEqual(report.front_ids, tuple(report.evaluations[i].placement_id for i in indices))

    def test_all_objective_subsets_preserve_same_report_comparison_scope(self):
        base = assess()
        names = ("active_sites", "native_operations", "two_site_operations", "critical_path_ps", "serial_duration_ps")
        for length in range(1, 6):
            for objectives in itertools.combinations(names, length):
                report = assess(base.source_report, context=replace(base.context, objectives=objectives))
                self.assertEqual(report.front_ids, (report.evaluations[0].placement_id,))
                self.assertEqual(HardwareReport.from_json(report.to_json()), report)

    def test_unplaced_passes_and_hardware_budget_skips_are_partial(self):
        report = assess(placed=False)
        self.assertEqual(report.front_reason, "no-placed-verified-circuits")
        self.assertTrue(report.front_is_partial)
        report = assess(context=replace(HardwareContext.from_dict(FIXTURE["context"]), max_gate_checks=1))
        self.assertEqual(report.evaluations[1].reason_code, "hardware-operation-budget")
        self.assertTrue(report.front_is_partial)

    def test_known_target_rejections_are_complete_assessments(self):
        report = assess(target="one-way")
        self.assertEqual(report.evaluations[1].status, "unsupported")
        self.assertFalse(report.front_is_partial)
        self.assertEqual(report.gate_checks, 4)

    def test_unknown_selected_timing_excludes_front_but_count_only_retains_diagnostics(self):
        report = assess(target="reported-stale")
        self.assertEqual(report.front_reason, "no-complete-objective-vectors")
        self.assertEqual(report.front_ids, ())
        self.assertTrue(report.front_is_partial)
        report = assess(target="reported-stale", context=replace(report.context, objectives=("native_operations",)))
        self.assertEqual(report.front_ids, (report.evaluations[0].placement_id,))
        self.assertFalse(report.front_is_partial)
        self.assertIsNone(report.evaluations[0].costs.critical_path_ps)
        self.assertEqual(report.evaluations[0].costs.timing_reason, "stale-calibration")

    def test_empty_front_reasons_have_the_required_priority(self):
        source = source_report(constraints=SearchConstraints(allowed_dimensions=(2,), max_registers=1, max_physical_size=2))
        self.assertEqual(assess(source).front_reason, "no-candidates")
        report = assess()
        no_gates = replace(report.profile, bindings=(), couplings=())
        result = assess_hardware(report.source_report, no_gates, report.placements, report.context)
        self.assertEqual(result.front_reason, "no-supported-placements")
        self.assertFalse(result.front_is_partial)

    def test_reports_and_nested_rows_are_immutable_and_dicts_are_fresh(self):
        report = assess()
        for value, name in ((report, "front_ids"), (report.evaluations[0], "status"), (report.evaluations[0].costs, "active_sites")):
            with self.assertRaises(FrozenInstanceError):
                setattr(value, name, None)
        body = report.to_dict()
        body["evaluations"][0]["costs"]["active_sites"] = 999
        body["placements"][0]["site_indices"][0] = 3
        self.assertEqual(report.evaluations[0].costs.active_sites, 1)
        self.assertEqual(report.placements[0].site_indices, (0,))

    def test_round_trip_is_recorded_and_never_calls_numerical_or_clock_capture(self):
        report = assess()
        with patch("q3hash.verification.verify_equivalence", side_effect=AssertionError("numerics")), \
                patch("q3hash.search_verification.verify_equivalence", side_effect=AssertionError("numerics")), \
                patch("q3hash.core.apply_state", side_effect=AssertionError("state")), \
                patch("q3hash.search_report.NumericalEnvironment.capture", side_effect=AssertionError("environment")):
            replay = HardwareReport.from_json(report.to_json())
        self.assertEqual(replay, report)
        self.assertEqual(replay.to_json(), report.to_json())
        self.assertEqual((replay.evidence_origin, replay.source_report.evidence_origin), ("recorded", "recorded"))
        self.assert_code(ValueError, "Q3-HARD-005", lambda: assess(replay.source_report))

    def test_producer_cost_analysis_itself_does_not_repeat_source_verification(self):
        source = source_report()
        with patch("q3hash.verification.verify_equivalence", side_effect=AssertionError("numerics")), \
                patch("q3hash.search_verification.verify_equivalence", side_effect=AssertionError("numerics")):
            self.assertEqual(assess(source).source_report.verification_calls, 2)

    def test_recorded_historical_engine_and_environment_are_preserved(self):
        body = assess().to_dict()
        body["engine_version"] = "historical-hardware-engine"
        source = body["source_report"]
        source["engine_version"] = "historical-core-engine"
        source["numerical_environment"]["machine"] = "historical-machine"
        body["source_id"] = hashlib.sha256(SearchReport.from_dict(source).to_json().encode()).hexdigest()
        replay = HardwareReport.from_dict(body)
        self.assertEqual(replay.engine_version, "historical-hardware-engine")
        self.assertEqual(replay.source_report.engine_version, "historical-core-engine")
        self.assertEqual(replay.source_report.numerical_environment.machine, "historical-machine")

    def test_input_fingerprints_and_recorded_placement_order_fail_before_cost_work(self):
        body = assess().to_dict()
        with patch("q3hash.hardware_report._evaluate_costs", side_effect=AssertionError("cost work")):
            for name in ("source_id", "profile_id", "context_id"):
                changed = {**body, name: "0" * 64}
                self.assert_code(ValueError, "Q3-HARD-005", lambda: HardwareReport.from_dict(changed))
            changed = {**body, "placements": list(reversed(body["placements"]))}
            self.assert_code(ValueError, "Q3-HARD-005", lambda: HardwareReport.from_dict(changed))

    def test_derived_identity_scope_work_and_front_tampering_fail_closed(self):
        body = assess().to_dict()
        for name, value in (("freshness", "fresh"), ("gate_checks", 0), ("gate_checks", True),
                            ("front_ids", []), ("ranking_scope", "global-optimum"), ("schedule_scope", "measured"),
                            ("engine_version", ""), ("engine_version", 1)):
            with self.subTest(field=name):
                self.assert_code(ValueError, "Q3-HARD-005", lambda: HardwareReport.from_dict({**body, name: value}))

    def test_row_cost_status_error_and_time_tampering_fail_closed(self):
        changes = [
            lambda x: x.update(status="ineligible"), lambda x: x.update(reason_code="forged"),
            lambda x: x.update(placement_id="0" * 64), lambda x: x.update(gate_checks=0),
            lambda x: x["costs"].update(active_sites=2), lambda x: x["costs"].update(circuit_error=0.0),
            lambda x: x["costs"].update(timing_reason="measured"), lambda x: x["costs"].update(critical_path_ps=None),
            lambda x: x["costs"]["serial_duration_ps"].update(upper_ps=99999),
            lambda x: x["costs"]["used_errors"][0].update(occurrences=2),
            lambda x: x["costs"]["used_errors"][0]["error"].update(metric="process-infidelity"),
        ]
        for change in changes:
            body = assess().to_dict()
            change(body["evaluations"][0])
            self.assert_code(ValueError, "Q3-HARD-005", lambda: HardwareReport.from_dict(body))

    def test_rejection_order_axes_and_operation_indices_are_checked(self):
        body = assess(target="one-way").to_dict()
        for field, value in (("code", "native-gate"), ("operation_index", 0), ("axis_index", 0), ("sites", [1, 2])):
            changed = deepcopy(body)
            changed["evaluations"][1]["rejections"][0][field] = value
            self.assert_code(ValueError, "Q3-HARD-005", lambda: HardwareReport.from_dict(changed))

    def test_unknown_fields_nested_types_bool_counts_and_float_ticks_are_rejected(self):
        for mutation in (
            lambda b: b.update(extra=1), lambda b: b["evaluations"][0].update(extra=1),
            lambda b: b["evaluations"][0]["costs"].update(extra=1),
            lambda b: b["evaluations"][0]["costs"]["used_errors"][0].update(extra=1),
            lambda b: b["evaluations"][0].update(gate_checks=True),
            lambda b: b["evaluations"][0]["costs"].update(active_sites=True),
            lambda b: b["evaluations"][0]["costs"]["critical_path_ps"].update(lower_ps=40000.0),
            lambda b: b.update(evaluations=[None]),
        ):
            body = assess().to_dict()
            mutation(body)
            with self.assertRaisesRegex(ValueError, "^Q3-(SER|HARD)-"):
                HardwareReport.from_dict(body)

    def test_json_duplicates_nonfinite_unicode_and_symmetric_wire_limit(self):
        report = assess()
        for text, code in (('{"x":1,"x":2}', "Q3-SER-002"), ('{"x":NaN}', "Q3-SER-001"),
                           ('{"x":1e999}', "Q3-SER-001"), ('"\\ud800"', "Q3-SER-001"),
                           (" " * (MAX_JSON_BYTES + 1), "Q3-SER-001")):
            self.assert_code(ValueError, code, lambda: HardwareReport.from_json(text))
        text = report.to_json()
        padded = text + " " * (MAX_JSON_BYTES - len(text.encode()))
        self.assertEqual(HardwareReport.from_json(padded), report)
        self.assert_code(ValueError, "Q3-SER-001", lambda: HardwareReport.from_json(padded + " "))
        with patch("q3hash._serialization.MAX_JSON_BYTES", len(text.encode()) - 1):
            self.assert_code(ValueError, "Q3-SER-001", report.to_json)
        self.assert_code(TypeError, "Q3-SER-001", lambda: HardwareReport.from_json(b"{}"))

    def test_canonical_repeated_reports_and_cross_report_input_rejection(self):
        source = source_report()
        self.assertEqual(assess(source).to_json(), assess(source).to_json())
        self.assert_code(TypeError, "Q3-HARD-001", lambda: hardware_front((assess(source), assess(source, target="one-way"))))


if __name__ == "__main__":
    unittest.main()
