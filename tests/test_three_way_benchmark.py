"""v0.6 same-logical-workload regression against the public package API."""

import cmath
import json
from pathlib import Path
import unittest

from q3hash import (
    BasisEncoding, CircuitImplementation, HardwareContext, HardwarePlacement,
    HardwareProfile, ReferenceOperator, SearchConstraints, assess_hardware,
    count_resources, evaluate_candidates, generate_encodings, logical_from_source,
    verify_equivalence,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "benchmarks/three-way-qutrit-shift-v1.json").read_text(encoding="utf-8"))


def load(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


class ThreeWayQutritShiftAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.logical = logical_from_source(load(DATA["logical_source"]))
        cls.rows = []
        for item in DATA["cases"]:
            encoding = BasisEncoding.from_json(load(item["encoding"]))
            physical = logical_from_source(load(item["physical_source"])).ir
            cls.rows.append((item, encoding, physical))

    def test_full_operators_subspace_leakage_unitarity_and_counts(self):
        self.assertEqual(self.logical.dimensions, (3,))
        self.assertEqual({item["id"] for item, _, _ in self.rows}, {"native", "binary", "mixed"})
        for item, encoding, physical in self.rows:
            with self.subTest(case=item["id"]):
                self.assertEqual(encoding.physical_basis_indices, (0, 1, 2))
                self.assertEqual(physical.dimensions, encoding.physical_dimensions)
                report = verify_equivalence(self.logical, physical, encoding, tolerance=1e-10)
                self.assertEqual(report.status, "pass")
                self.assertEqual(report.evidence, "q3hash-circuit")
                for attr in ("subspace_residual", "leakage_norm", "logical_unitarity_error", "physical_unitarity_error"):
                    self.assertLessEqual(getattr(report, attr), 1e-10, (item["id"], attr))
                self.assertEqual(list(count_resources(physical, logical_size=3).as_tuple()), item["resources"])

    def test_negative_controls_reject_false_positive_cases(self):
        leaky = logical_from_source("qudit 4 q\nshift q").ir
        report = verify_equivalence(self.logical, leaky, BasisEncoding((3,), (4,), (0, 1, 2)))
        self.assertEqual(report.status, "fail")
        self.assertAlmostEqual(report.leakage_norm, 1)
        identity = logical_from_source("qutrit q")
        bad_matrix = tuple(tuple(int(r == c and r < 3) for c in range(4)) for r in range(4))
        report = verify_equivalence(identity, ReferenceOperator((2, 2), bad_matrix),
                                    BasisEncoding((3,), (2, 2), (0, 1, 2)))
        self.assertEqual((report.status, report.physical_unitarity_error), ("fail", 1))
        qubit = logical_from_source("qubit q")
        wrong_relative_phase = logical_from_source("qubit q\nfourier q\nshift q\nfourier q")
        report = verify_equivalence(qubit, wrong_relative_phase.ir, BasisEncoding((2,), (2,), (0, 1)))
        self.assertEqual(report.status, "fail")
        self.assertGreater(report.subspace_residual, 1)
        phase = cmath.exp(0.7j)
        report = verify_equivalence(qubit, ReferenceOperator((2,), ((phase, 0), (0, phase))),
                                    BasisEncoding((2,), (2,), (0, 1)))
        self.assertEqual(report.status, "pass")
        for mapping in ((0, 0, 2), (0, 1, 6)):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                BasisEncoding((3,), (2, 3), mapping)

    def test_synthetic_costs_and_partial_front_are_explicit(self):
        constraints = SearchConstraints.from_json(load(DATA["constraints"]))
        self.assertEqual(constraints.max_physical_size, 6)
        generation = generate_encodings(self.logical.dimensions, constraints)
        self.assertEqual(generation.completion, "exhausted")
        self.assertEqual({c.encoding.physical_dimensions for c in generation.candidates},
                         {(3,), (2, 2), (2, 3), (3, 2)})
        implementations = tuple(CircuitImplementation(enc, ir) for _, enc, ir in self.rows)
        source = evaluate_candidates(self.logical, generation, implementations)
        self.assertEqual((source.status_counts["pass"], source.status_counts["unimplemented"]), (3, 1))
        self.assertTrue(source.front_is_partial)
        profile = HardwareProfile.from_json(load(DATA["hardware_profile"]))
        context = HardwareContext.from_json(load(DATA["hardware_context"]))
        self.assertEqual(profile.provenance.kind, "synthetic")
        cases = {enc: item for item, enc, _ in self.rows}
        placements = tuple(HardwarePlacement(row.candidate_id, tuple(cases[row.candidate.encoding]["placement"]))
                           for row in source.evaluations if row.candidate.encoding in cases)
        hardware = assess_hardware(source, profile, placements, context)
        self.assertEqual((hardware.status_counts["supported"], hardware.status_counts["ineligible"]), (3, 1))
        self.assertTrue(hardware.front_is_partial)
        self.assertEqual(hardware.gate_checks, 5)
        front = set()
        for source_row, assessed in zip(source.evaluations, hardware.evaluations):
            spec = cases.get(source_row.candidate.encoding)
            if spec is None:
                self.assertEqual(assessed.status, "ineligible")
                continue
            self.assertEqual(assessed.status, "supported")
            self.assertIsNone(assessed.costs.circuit_error)
            self.assertEqual((assessed.costs.critical_path_ps.lower_ps,
                              assessed.costs.critical_path_ps.upper_ps), tuple(spec["critical_path_ps"]))
            if assessed.placement_id in hardware.front_ids:
                front.add(spec["id"])
        self.assertEqual(front, set(DATA["expected_front"]))


if __name__ == "__main__":
    unittest.main()
