"""Feasibility precedence, exact timing, freshness and bounded cost work."""

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import PropertyMock, patch

from q3hash import (CircuitIR, ErrorRange, GateKind, HardwareContext, HardwarePlacement,
                    HardwareProfile, NativeBinding, Operation, ProfileProvenance, Register,
                    TimeRange, logical_from_source)
from q3hash.hardware_costs import _CostInput, _evaluate_costs, _freshness


AT = "2026-11-01T01:00:00Z"


def key(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def profile(*, dimensions=(3, 2, 3), bindings=None, couplings=((0, 1), (0, 2), (1, 0), (2, 0))):
    if bindings is None:
        bindings = (NativeBinding(GateKind.SHIFT, (0,), TimeRange(2, 4), ErrorRange("average-gate-infidelity", 0.1, 0.2)),
                    NativeBinding(GateKind.SHIFT, (1,), TimeRange(5, 6), None),
                    NativeBinding(GateKind.SHIFT, (2,), TimeRange(7, 9), ErrorRange("process-infidelity", 0.3, 0.4)),
                    NativeBinding(GateKind.FOURIER, (0,), TimeRange(11, 13), None),
                    NativeBinding(GateKind.SUM, (0, 1), TimeRange(17, 19), None),
                    NativeBinding(GateKind.SUM, (0, 2), TimeRange(23, 29), None),
                    NativeBinding(GateKind.SUM, (1, 0), TimeRange(31, 37), None),
                    NativeBinding(GateKind.SUM, (2, 0), TimeRange(41, 43), None))
    provenance = ProfileProvenance("synthetic", "Q3# tests", "tiny", "v1", "urn:q3hash:synthetic:tiny",
                                   "2026-11-01T00:00:00Z", None, "No measured device data.")
    return HardwareProfile("tiny", dimensions, couplings, bindings, provenance)


def request(source="qutrit a\nshift a", sites=(0,), *, source_status="pass", number=0):
    circuit = None if source is None else logical_from_source(source).ir
    return _CostInput(key(number), source_status, circuit,
                      None if sites is None else HardwarePlacement(key(number), sites))


def run_one(item=None, target=None, context=None):
    return _evaluate_costs((request() if item is None else item,), profile() if target is None else target,
                           HardwareContext(AT, 3600) if context is None else context)


class HardwareCostTests(unittest.TestCase):
    def assert_code(self, kind, code, callback):
        with self.assertRaisesRegex(kind, "^" + code):
            callback()

    def test_exact_native_support_counts_and_nonaggregated_error_records(self):
        result = run_one()
        self.assertEqual(result.freshness, "synthetic")
        self.assertEqual(result.gate_checks, 1)
        row, = result.evaluations
        self.assertEqual((row.status, row.reason_code, row.gate_checks), ("supported", "native-model-supported", 1))
        costs = row.costs
        self.assertEqual((costs.active_sites, costs.native_operations, costs.two_site_operations), (1, 1, 0))
        self.assertEqual(costs.critical_path_ps, TimeRange(2, 4))
        self.assertEqual(costs.serial_duration_ps, TimeRange(2, 4))
        self.assertEqual(costs.timing_reason, "model-range")
        self.assertIsNone(costs.circuit_error)
        self.assertEqual(costs.circuit_error_reason, "no-noise-composition-model")
        self.assertEqual(costs.used_errors[0].error, profile().bindings[0].error)

    def test_every_dimension_mismatch_is_retained_before_work_or_native_checks(self):
        item = request("qubit a\nqutrit b\nsum a b", (0, 1))
        with patch("q3hash.hardware_costs._inspect_circuit", side_effect=AssertionError("gate work")):
            row, = run_one(item, context=HardwareContext(AT, 0, max_gate_checks=1)).evaluations
        self.assertEqual((row.status, row.reason_code, row.gate_checks, row.costs), ("unsupported", "site-dimension", 0, None))
        self.assertEqual([(r.code, r.axis_index, r.operation_index, r.sites) for r in row.rejections],
                         [("site-dimension", 0, None, (0,)), ("site-dimension", 1, None, (1,))])

    def test_ordered_sum_edges_and_native_bindings_are_separate_requirements(self):
        item = request("qubit a\nqutrit b\nsum a b", (1, 2))
        row, = run_one(item).evaluations
        self.assertEqual([(r.code, r.operation_index, r.sites) for r in row.rejections], [("directed-coupling", 0, (1, 2))])
        target = replace(profile(), couplings=tuple(sorted((*profile().couplings, (1, 2)))))
        row, = run_one(item, target).evaluations
        self.assertEqual([(r.code, r.operation_index, r.sites) for r in row.rejections], [("native-gate", 0, (1, 2))])
        self.assertEqual(row.gate_checks, 1)
        self.assertIsNone(row.costs)

    def test_reverse_sum_uses_its_own_directed_duration(self):
        forward = request("qutrit a\nqubit b\nsum a b", (0, 1))
        reverse = request("qutrit a\nqubit b\nsum b a", (0, 1))
        self.assertEqual(run_one(forward).evaluations[0].costs.critical_path_ps, TimeRange(17, 19))
        self.assertEqual(run_one(reverse).evaluations[0].costs.critical_path_ps, TimeRange(31, 37))

    def test_all_failed_operations_are_reported_and_the_full_row_is_charged(self):
        item = request("qubit a\nqutrit b\nfourier a\nsum a b\nfourier b\nshift a", (1, 2))
        row, = run_one(item).evaluations
        self.assertEqual(row.status, "unsupported")
        self.assertEqual(row.gate_checks, 4)
        self.assertEqual([(r.code, r.operation_index, r.axis_index, r.sites) for r in row.rejections],
                         [("native-gate", 0, None, (1,)), ("directed-coupling", 1, None, (1, 2)),
                          ("native-gate", 2, None, (2,))])
        self.assertIsNone(row.costs)

    def test_source_statuses_precede_placement_dimensions_and_all_work(self):
        items = tuple(request("qubit a\nshift a", None if i % 2 else (0,), source_status=status, number=i)
                      for i, status in enumerate(("fail", "unsupported", "not-evaluated")))
        items += (request(None, None, source_status="unimplemented", number=3),)
        with patch("q3hash.hardware_costs._inspect_circuit", side_effect=AssertionError("gate work")):
            result = _evaluate_costs(items, profile(), HardwareContext(AT, 0))
        self.assertEqual([row.status for row in result.evaluations], ["ineligible"] * 4)
        self.assertEqual([row.reason_code for row in result.evaluations],
                         ["source-fail", "source-unsupported", "source-not-evaluated", "source-unimplemented"])
        self.assertEqual(result.gate_checks, 0)
        self.assertTrue(all(row.costs is None and row.rejections == () for row in result.evaluations))

    def test_unplaced_pass_is_uncharged_and_has_no_costs(self):
        row, = run_one(request(sites=None)).evaluations
        self.assertEqual((row.status, row.reason_code, row.gate_checks, row.costs), ("unplaced", "no-placement", 0, None))

    def test_whole_row_budget_exactness_and_later_smaller_fit(self):
        items = (request("qutrit a\nshift a\nshift a\nshift a", number=0),
                 request(number=1), request(number=2), request("qutrit a", number=3))
        result = _evaluate_costs(items, profile(), HardwareContext(AT, 0, max_gate_checks=2))
        self.assertEqual([row.status for row in result.evaluations], ["not-evaluated", "supported", "supported", "supported"])
        self.assertEqual([row.gate_checks for row in result.evaluations], [0, 1, 1, 0])
        self.assertEqual(result.evaluations[0].reason_code, "hardware-operation-budget")
        self.assertEqual(result.gate_checks, 2)
        self.assertEqual(result.evaluations[-1].costs.critical_path_ps, TimeRange(0, 0))

    def test_budget_precedes_target_checks_but_dimension_rejections_are_free(self):
        items = (request("qubit a\nfourier a\nfourier a", (0,), number=0),
                 request("qutrit a\nfourier a\nfourier a", number=1), request(number=2))
        result = _evaluate_costs(items, profile(), HardwareContext(AT, 0, max_gate_checks=1))
        self.assertEqual([row.reason_code for row in result.evaluations],
                         ["site-dimension", "hardware-operation-budget", "native-model-supported"])
        self.assertEqual([row.gate_checks for row in result.evaluations], [0, 0, 1])
        self.assertEqual(result.gate_checks, 1)

    def test_rejected_row_consumes_work_and_can_exhaust_later_rows(self):
        items = (request("qubit a\nfourier a\nshift a", (1,), number=0), request(number=1))
        result = _evaluate_costs(items, profile(), HardwareContext(AT, 0, max_gate_checks=2))
        self.assertEqual([row.status for row in result.evaluations], ["unsupported", "not-evaluated"])
        self.assertEqual([row.gate_checks for row in result.evaluations], [2, 0])
        self.assertEqual(result.gate_checks, 2)

    def test_serial_disjoint_and_joining_paths_use_control_and_target_dependencies(self):
        item = request("qutrit a\nqubit b\nqutrit c\nshift a\nshift b\nsum a b\nshift c\nsum c a", (0, 1, 2))
        costs = run_one(item).evaluations[0].costs
        self.assertEqual(costs.critical_path_ps, TimeRange(63, 68))
        self.assertEqual(costs.serial_duration_ps, TimeRange(72, 81))
        self.assertEqual((costs.active_sites, costs.native_operations, costs.two_site_operations), (3, 5, 2))

    def test_reordered_physical_axes_and_nonadjacent_sites_preserve_timing(self):
        left = request("qutrit a\nqutrit b\nfourier a\nsum a b", (0, 2))
        right = request("qutrit b\nqutrit a\nfourier a\nsum a b", (2, 0))
        self.assertEqual(run_one(left).evaluations[0].costs, run_one(right).evaluations[0].costs)
        self.assertEqual(run_one(left).evaluations[0].costs.critical_path_ps, TimeRange(34, 42))

    def test_used_missing_duration_invalidates_both_aggregates_but_unused_does_not(self):
        target = profile()
        target = replace(target, bindings=(replace(target.bindings[0], duration=None), *target.bindings[1:]))
        row, = run_one(target=target).evaluations
        self.assertIsNone(row.costs.critical_path_ps)
        self.assertIsNone(row.costs.serial_duration_ps)
        self.assertEqual(row.costs.timing_reason, "missing-duration")
        unaffected = request("qubit a\nshift a", (1,))
        self.assertEqual(run_one(unaffected, target).evaluations[0].costs.critical_path_ps, TimeRange(5, 6))

    def test_explicit_zero_duration_and_empty_circuits_have_known_zero_time(self):
        target = profile()
        target = replace(target, bindings=(replace(target.bindings[0], duration=TimeRange(0, 0)), *target.bindings[1:]))
        for item, reason in ((request(), "model-range"), (request("qutrit a"), "empty-circuit")):
            costs = run_one(item, target).evaluations[0].costs
            self.assertEqual((costs.critical_path_ps, costs.serial_duration_ps), (TimeRange(0, 0), TimeRange(0, 0)))
            self.assertEqual(costs.timing_reason, reason)

    def test_freshness_uses_exact_inclusive_boundaries_and_missing_calibration(self):
        target = profile()
        target = replace(target, provenance=replace(target.provenance, kind="reported-device",
                         source_uri="https://example.invalid/snapshot", calibrated_at="2026-11-01T00:00:00Z"))
        self.assertEqual(_freshness(target, HardwareContext(AT, 3600)), "fresh")
        self.assertEqual(_freshness(target, HardwareContext("2026-11-01T01:00:01Z", 3600)), "stale")
        self.assertEqual(_freshness(target, HardwareContext("2026-11-01T00:00:00Z", 0)), "fresh")
        self.assertEqual(_freshness(replace(target, provenance=replace(target.provenance, calibrated_at=None)),
                                    HardwareContext(AT, 3600)), "unknown")
        self.assert_code(ValueError, "Q3-HARD-001",
                         lambda: _freshness(target, HardwareContext("2026-10-31T23:59:59Z", 3600)))

    def test_stale_and_unknown_calibration_override_missing_duration_and_keep_counts(self):
        base = profile()
        base = replace(base, bindings=(replace(base.bindings[0], duration=None), *base.bindings[1:]))
        for calibrated, reason in (("2026-10-31T23:00:00Z", "stale-calibration"), (None, "unknown-calibration")):
            target = replace(base, provenance=replace(base.provenance, kind="reported-device",
                             source_uri="https://example.invalid/snapshot", calibrated_at=calibrated))
            costs = run_one(target=target).evaluations[0].costs
            self.assertEqual((costs.native_operations, costs.timing_reason), (1, reason))
            self.assertIsNone(costs.critical_path_ps)
            self.assertIsNone(costs.serial_duration_ps)
            self.assertEqual(costs.used_errors[0].error, base.bindings[0].error)
            identity = run_one(request("qutrit a"), target).evaluations[0].costs
            self.assertEqual(identity.critical_path_ps, TimeRange(0, 0))
            self.assertEqual(identity.timing_reason, "empty-circuit")

    def test_error_records_keep_profile_order_occurrences_nulls_and_metric_definitions(self):
        item = request("qutrit a\nqubit b\nqutrit c\nshift c\nshift a\nshift a\nshift b\nsum a b", (0, 1, 2))
        costs = run_one(item).evaluations[0].costs
        self.assertEqual([(x.kind.value, x.sites, x.occurrences) for x in costs.used_errors],
                         [("shift", (0,), 2), ("shift", (1,), 1), ("shift", (2,), 1), ("sum", (0, 1), 1)])
        self.assertEqual([None if x.error is None else x.error.metric for x in costs.used_errors],
                         ["average-gate-infidelity", None, "process-infidelity", None])
        self.assertIsNone(costs.circuit_error)
        self.assertEqual(run_one(request("qutrit a")).evaluations[0].costs.used_errors, ())

    def test_maximum_operation_domain_keeps_integer_totals_exact(self):
        target = profile()
        target = replace(target, bindings=(replace(target.bindings[0], duration=TimeRange(10**15 - 1, 10**15)), *target.bindings[1:]))
        circuit = CircuitIR((Register("a", 3),), (Operation(GateKind.SHIFT, 0),) * 16384)
        item = replace(request(), circuit=circuit)
        result = run_one(item, target)
        self.assertEqual(result.gate_checks, 16384)
        costs = result.evaluations[0].costs
        self.assertEqual(costs.critical_path_ps, TimeRange(16384 * (10**15 - 1), 16384 * 10**15))
        self.assertEqual(costs.serial_duration_ps, costs.critical_path_ps)
        self.assertIs(type(costs.critical_path_ps.lower_ps), int)
        self.assertEqual(costs.used_errors[0].occurrences, 16384)
        self.assert_code(ValueError, "Q3-HARD-005",
                         lambda: run_one(replace(item, circuit=replace(circuit, operations=circuit.operations + (Operation(GateKind.SHIFT, 0),))), target))

    def test_ineligible_oversized_circuit_is_preserved_without_gate_work(self):
        item = request(source_status="unsupported")
        item = replace(item, circuit=replace(item.circuit, operations=item.circuit.operations * 16385))
        with patch("q3hash.hardware_costs._inspect_circuit", side_effect=AssertionError("gate work")):
            result = run_one(item)
        self.assertEqual((result.evaluations[0].status, result.gate_checks), ("ineligible", 0))

    def test_entire_batch_preflight_rejects_late_bad_placement_before_any_gate_work(self):
        good = request(number=0)
        invalid = request(sites=(3,), number=1)
        with patch("q3hash.hardware_costs._inspect_circuit", side_effect=AssertionError("gate work")):
            self.assert_code(ValueError, "Q3-HARD-003",
                             lambda: _evaluate_costs((good, invalid), profile(), HardwareContext(AT, 0)))
            self.assert_code(ValueError, "Q3-HARD-003",
                             lambda: _evaluate_costs((good, replace(invalid, placement=HardwarePlacement(key(0), (0,)))),
                                                     profile(), HardwareContext(AT, 0)))

    def test_input_types_status_consistency_duplicates_and_batch_limit_fail_closed(self):
        for inputs, target, context in (([], profile(), HardwareContext(AT, 0)), ((None,), profile(), HardwareContext(AT, 0)),
                                        ((), {}, HardwareContext(AT, 0)), ((), profile(), {})):
            self.assert_code(TypeError, "Q3-HARD-001", lambda: _evaluate_costs(inputs, target, context))
        for item in (replace(request(), source_status="bogus"), replace(request(), circuit=None),
                     replace(request(), source_status="unimplemented")):
            self.assert_code(ValueError, "Q3-HARD-005", lambda: run_one(item))
        self.assert_code(ValueError, "Q3-HARD-003",
                         lambda: run_one(request(None, (0,), source_status="unimplemented")))
        self.assert_code(ValueError, "Q3-HARD-003",
                         lambda: _evaluate_costs((request(), request()), profile(), HardwareContext(AT, 0)))
        self.assert_code(ValueError, "Q3-HARD-001",
                         lambda: _evaluate_costs((request(),) * 4097, profile(), HardwareContext(AT, 0)))

    def test_empty_and_maximum_candidate_batches_keep_order_and_zero_identity_work(self):
        target, context = profile(), HardwareContext(AT, 0, max_gate_checks=1)
        result = _evaluate_costs((), target, context)
        self.assertEqual((result.evaluations, result.gate_checks), ((), 0))
        items = tuple(request("qutrit a", number=i) for i in range(4096))
        result = _evaluate_costs(items, target, context)
        self.assertEqual(tuple(row.candidate_id for row in result.evaluations), tuple(item.candidate_id for item in items))
        self.assertEqual(result.gate_checks, 0)
        self.assertTrue(all(row.costs.critical_path_ps == TimeRange(0, 0) for row in result.evaluations))

    def test_fingerprints_preflight_and_unexpected_runtime_errors_remain_visible(self):
        with (patch.object(HardwareProfile, "to_json", side_effect=ValueError("Q3-SER-001: oversized")),
              patch("q3hash.hardware_costs._inspect_circuit", side_effect=AssertionError("gate work"))):
            self.assert_code(ValueError, "Q3-SER-001", run_one)
        with patch("q3hash.hardware_costs._inspect_circuit", side_effect=RuntimeError("unexpected defect")):
            with self.assertRaisesRegex(RuntimeError, "unexpected defect"):
                run_one()

    def test_costs_are_matrix_free_with_large_dimensions_and_no_numerical_calls(self):
        target = profile(dimensions=(32,) * 64, bindings=(NativeBinding(GateKind.SHIFT, (63,), TimeRange(1, 2), None),),
                         couplings=())
        circuit = CircuitIR(tuple(Register(f"q{i}", 32) for i in range(64)), (Operation(GateKind.SHIFT, 63),))
        item = _CostInput(key(0), "pass", circuit, HardwarePlacement(key(0), tuple(range(64))))
        with patch.object(CircuitIR, "state_size", new_callable=PropertyMock, side_effect=AssertionError("state allocation")), \
                patch("q3hash.core.apply_state", side_effect=AssertionError("numerical work")), \
                patch("q3hash.verification.verify_equivalence", side_effect=AssertionError("numerical verification")):
            costs = run_one(item, target).evaluations[0].costs
        self.assertEqual((costs.active_sites, costs.critical_path_ps), (64, TimeRange(1, 2)))

    def test_result_records_are_immutable_and_repeated_complete_inputs_are_identical(self):
        result = run_one()
        self.assertEqual(run_one(), result)
        for item, attribute in ((result, "gate_checks"), (result.evaluations[0], "status"),
                                (result.evaluations[0].costs, "timing_reason"),
                                (result.evaluations[0].costs.used_errors[0], "occurrences")):
            with self.assertRaises(FrozenInstanceError):
                setattr(item, attribute, None)
        self.assertEqual((result.profile_id, result.context_id), (profile().profile_id, HardwareContext(AT, 3600).context_id))

    def test_all_frozen_target_vectors_match_expected_cost_and_work_outcomes(self):
        fixture = json.loads((Path(__file__).resolve().parents[1] / "benchmarks/hardware-cost-v1.json").read_text())
        workloads = {item["id"]: item for item in fixture["workloads"]}
        for row in fixture["target_cases"]:
            target = HardwareProfile.from_dict(fixture["profiles"][row["profile"]])
            context = HardwareContext.from_dict(fixture["context"])
            item = request(workloads[row["workload"]]["physical"], tuple(row["site_indices"]))
            actual = run_one(item, target, context).evaluations[0]
            with self.subTest(vector=row["id"]):
                self.assertEqual((actual.status, actual.gate_checks), (row["status"], row["gate_checks"]))
                self.assertEqual([r.code for r in actual.rejections], row["rejections"])
                if row["expected_counts"] is None:
                    self.assertIsNone(actual.costs)
                else:
                    self.assertEqual([actual.costs.active_sites, actual.costs.native_operations, actual.costs.two_site_operations],
                                     row["expected_counts"])
                    self.assertEqual(None if actual.costs.critical_path_ps is None else
                                     [actual.costs.critical_path_ps.lower_ps, actual.costs.critical_path_ps.upper_ps],
                                     row["expected_time_ps"])
                    self.assertEqual(actual.costs.timing_reason, row["timing_reason"])


if __name__ == "__main__":
    unittest.main()
