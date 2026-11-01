"""Structural count invariants, exact depth and allocation-free IR analysis."""

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import unittest

from q3hash import (CircuitIR, GateKind, Operation, Register, RESOURCE_OBJECTIVES,
                    ResourceCounts, SearchConstraints, count_resources, logical_from_source)


class ResourceTests(unittest.TestCase):
    def test_golden_resource_and_supplied_circuit_vectors(self):
        vectors = json.loads((Path(__file__).resolve().parents[1] /
                              "benchmarks/encoding-search-v1.json").read_text())
        for case in vectors["resource_cases"]:
            ir = logical_from_source(case["source"]).ir
            self.assertEqual(list(count_resources(ir, logical_size=case["logical_size"]).as_tuple()),
                             case["resources"], case["id"])
        for case in vectors["operator_cases"]:
            if "resources" in case:
                logical = logical_from_source(case["logical"])
                physical = logical_from_source(case["physical"]).ir
                self.assertEqual(list(count_resources(physical, logical_size=logical.state_size).as_tuple()),
                                 case["resources"], case["id"])

    def test_control_and_target_dependencies_are_both_respected(self):
        ir = logical_from_source("qubit a\nqubit b\nqubit c\nshift a\nsum a c\nshift c\n"
                                 "shift b\nsum c b\n").ir
        self.assertEqual(count_resources(ir, logical_size=8).as_tuple(), (3, 2, 0, 5, 2, 4))
        reverse = logical_from_source("qubit a\nqubit b\nsum a b\nsum b a\n").ir
        self.assertEqual(count_resources(reverse, logical_size=3).as_tuple(), (2, 2, 1, 2, 2, 2))

    def test_large_ir_counts_do_not_allocate_a_statevector(self):
        registers = tuple(Register(f"q{i}", 2) for i in range(257))
        ir = CircuitIR(registers, (Operation(GateKind.SHIFT, 0), Operation(GateKind.FOURIER, 256)))
        counts = count_resources(ir, logical_size=2)
        self.assertEqual(counts.as_tuple(), (257, 2, 2**257 - 2, 2, 0, 1))

    def test_counter_inputs_are_strict_and_capacity_checked(self):
        ir = logical_from_source("qubit q").ir
        for value in (True, 2.0, "2", None):
            with self.assertRaisesRegex(TypeError, "^Q3-SEARCH-001"):
                count_resources(ir, logical_size=value)
        for value in (-1, 0, 1, 3):
            with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-001"):
                count_resources(ir, logical_size=value)
        with self.assertRaisesRegex(TypeError, "^Q3-SEARCH-001"):
            count_resources("qubit q", logical_size=2)

    def test_count_vector_types_and_basic_consistency(self):
        good = (2, 2, 1, 3, 2, 3)
        for index in range(6):
            for value in (True, 1.0, "1", None):
                row = list(good)
                row[index] = value
                with self.assertRaisesRegex(TypeError, "^Q3-SEARCH-005"):
                    ResourceCounts(*row)
        for row in ((0, 2, 0, 0, 0, 0), (1, 1, 0, 0, 0, 0), (1, 33, 0, 0, 0, 0),
                    (1, 2, -1, 0, 0, 0), (2, 2, 0, 1, 2, 1), (1, 2, 0, 1, 1, 1),
                    (2, 2, 0, 0, 0, 1), (2, 2, 0, 1, 0, 0), (2, 2, 0, 1, 0, 2)):
            with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-005"):
                ResourceCounts(*row)

    def test_counts_are_immutable_fresh_and_keep_objective_order(self):
        counts = ResourceCounts(2, 2, 1, 3, 2, 3)
        with self.assertRaises(FrozenInstanceError):
            counts.gate_count = 1
        body = counts.to_dict()
        body["gate_count"] = 0
        self.assertEqual(counts.gate_count, 3)
        self.assertEqual(counts.as_tuple(("gate_count", "unused_basis_states")), (3, 1))
        self.assertEqual(RESOURCE_OBJECTIVES, SearchConstraints().objectives)

    def test_objective_names_and_containers_are_strict(self):
        counts = ResourceCounts(1, 3, 0, 1, 0, 1)
        with self.assertRaisesRegex(TypeError, "^Q3-SEARCH-001"):
            counts.as_tuple(["gate_count"])
        for names in ((), ("unknown",), ("gate_count", "gate_count"), (True,)):
            with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-001"):
                counts.as_tuple(names)


if __name__ == "__main__":
    unittest.main()
