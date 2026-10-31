"""Generation acceptance cases plus input, allocation and collision boundaries."""

from dataclasses import replace
import importlib.util
import itertools
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from q3hash import BasisEncoding, GenerationReport, SearchConstraints, generate_encodings


class SearchGenerationTests(unittest.TestCase):
    def test_golden_generation_and_all_budget_boundaries(self):
        vectors = json.loads((Path(__file__).resolve().parents[1] /
                              "benchmarks/encoding-search-v1.json").read_text())
        case = vectors["generation_cases"][0]
        constraints = SearchConstraints(allowed_dimensions=tuple(case["allowed_dimensions"]),
            max_registers=case["max_registers"], max_physical_size=case["max_physical_size"])
        report = generate_encodings(tuple(case["logical_dimensions"]), constraints)
        actual = [{"physical_dimensions": list(v.encoding.physical_dimensions),
                   "mapping": list(v.encoding.physical_basis_indices)} for v in report.candidates]
        self.assertEqual(actual, case["expected_candidates"])
        self.assertEqual((report.dimension_tuples_seen, report.mapping_attempts,
                          report.duplicate_mappings, report.dimension_rejections.insufficient_capacity),
                         (6, 10, 5, 1))
        for boundary in case["budget_cases"]:
            limited = generate_encodings((3,), replace(constraints, **boundary["limits"]))
            self.assertEqual(limited.completion, boundary["completion"])
            self.assertEqual(limited.stop_reason, boundary["stop_reason"])
            self.assertEqual(limited.dimension_tuples_seen, boundary["dimension_tuples_seen"])
            self.assertEqual(limited.mapping_attempts, boundary["mapping_attempts"])
            self.assertEqual(limited.candidates, report.candidates[:boundary["candidate_count"]])

    def test_register_partition_distinguishes_maps_and_counts_bad_capacity(self):
        report = generate_encodings((2, 3), SearchConstraints(allowed_dimensions=(2,), max_registers=3))
        self.assertEqual([c.encoding.physical_basis_indices for c in report.candidates],
                         [(0, 1, 2, 3, 4, 5), (0, 1, 2, 4, 5, 6)])
        self.assertEqual([c.origin for c in report.candidates], ["flat-prefix", "register-prefix"])
        self.assertEqual(report.candidates[1].block_cuts, (1,))
        self.assertEqual(report.partition_rejections, 1)
        self.assertEqual(report.mapping_attempts, 3)
        self.assertEqual(report.dimension_rejections.insufficient_capacity, 2)

    def test_seeds_precede_generated_maps_deduplicate_and_preserve_axis_order(self):
        seed = BasisEncoding((2, 3), (3, 2), (0, 2, 4, 1, 3, 5))
        report = generate_encodings((2, 3), SearchConstraints(max_registers=2, max_physical_size=6),
                                    seed_encodings=(seed, seed))
        self.assertEqual([(c.encoding.physical_dimensions, c.encoding.physical_basis_indices)
                          for c in report.candidates],
                         [((3, 2), (0, 2, 4, 1, 3, 5)), ((2, 3), (0, 1, 2, 3, 4, 5)),
                          ((3, 2), (0, 1, 2, 3, 4, 5))])
        self.assertEqual(report.candidates[0].seed_index, 0)
        self.assertEqual(report.duplicate_mappings, 2)
        self.assertEqual(report.mapping_attempts, 6)
        self.assertEqual(report.partition_rejections, 1)
        self.assertEqual(GenerationReport.from_json(report.to_json()), report)

    def test_seed_order_is_visible_in_the_canonical_prefix(self):
        a = BasisEncoding((3,), (3,), (0, 1, 2))
        b = BasisEncoding((3,), (3,), (1, 2, 0))
        constraints = SearchConstraints(max_candidates=1, max_registers=1)
        first = generate_encodings((3,), constraints, seed_encodings=(a, b))
        second = generate_encodings((3,), constraints, seed_encodings=(b, a))
        self.assertEqual(first.candidates[0].encoding, a)
        self.assertEqual(second.candidates[0].encoding, b)
        self.assertEqual((first.dimension_tuples_seen, first.mapping_attempts), (0, 2))
        self.assertEqual(first.stop_reason, "candidate-budget")
        self.assertNotEqual(first.to_json(), second.to_json())

    def test_candidate_limit_is_not_a_stop_on_duplicates_alone(self):
        report = generate_encodings((3,), SearchConstraints(allowed_dimensions=(3,), max_registers=1,
            max_candidates=1, max_dimension_tuples=1, max_mapping_attempts=2))
        self.assertEqual(report.completion, "exhausted")
        self.assertEqual((report.mapping_attempts, report.duplicate_mappings), (2, 1))

    def test_unavailable_partition_does_not_consume_a_mapping_attempt(self):
        report = generate_encodings((2, 3), SearchConstraints(allowed_dimensions=(6,), max_registers=1))
        self.assertEqual(report.emitted_candidates, 1)
        self.assertEqual(report.family_unavailable, 1)
        self.assertEqual(report.mapping_attempts, 1)
        empty = generate_encodings((2, 3), SearchConstraints(allowed_dimensions=(6,), max_registers=1,
                                                          mapping_families=("register-prefix",)))
        self.assertEqual((empty.emitted_candidates, empty.mapping_attempts, empty.family_unavailable), (0, 0, 1))
        self.assertEqual(empty.completion, "exhausted")

    def test_preflight_rejects_every_bad_seed_before_generation(self):
        seed = BasisEncoding((3,), (2, 2), (0, 1, 2))
        bad_requests = [((3,), SearchConstraints(max_registers=1), (seed,)),
                        ((2,), SearchConstraints(), (seed,)),
                        ((3,), SearchConstraints(allowed_dimensions=(3,)), (seed,)),
                        ((3,), SearchConstraints(max_physical_size=3), (seed,)),
                        ((3,), SearchConstraints(), (seed, None)),
                        ((3,), SearchConstraints(), (seed,) * 4097)]
        with patch("q3hash.search._generate", side_effect=AssertionError("generation ran")):
            for logical, constraints, seeds in bad_requests:
                with self.subTest(logical=logical, constraints=constraints):
                    with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-002"):
                        generate_encodings(logical, constraints, seed_encodings=seeds)

    def test_top_level_inputs_and_logical_dimensions_are_strict(self):
        for logical, constraints, seeds in [([3], SearchConstraints(), ()),
                                             ((3,), {}, ()), ((3,), SearchConstraints(), [])]:
            with self.assertRaisesRegex(TypeError, "^Q3-SEARCH-001"):
                generate_encodings(logical, constraints, seed_encodings=seeds)
        for dimensions in ((), (True,), (3.0,), (1,), (33,)):
            with self.assertRaisesRegex(ValueError, "^Q3-ENC-001"):
                generate_encodings(dimensions, SearchConstraints())

    def test_large_logical_space_rejects_before_any_map_allocation(self):
        with patch("q3hash.search.BasisEncoding", side_effect=AssertionError("map allocated")), \
                patch("q3hash.search._register_map", side_effect=AssertionError("map allocated")):
            report = generate_encodings((32,) * 10, SearchConstraints(max_registers=2, max_physical_size=4))
        self.assertEqual(report.completion, "exhausted")
        self.assertEqual((report.dimension_tuples_seen, report.mapping_attempts, report.emitted_candidates), (6, 0, 0))
        self.assertEqual(report.dimension_rejections.insufficient_capacity, 3)
        self.assertEqual(report.dimension_rejections.physical_size_limit, 3)

    def test_huge_declared_domain_uses_one_lazy_lookahead_and_no_replay(self):
        consumed = []
        original = itertools.product

        def counted(*args, **kwargs):
            for item in original(*args, **kwargs):
                consumed.append(item)
                yield item

        with patch("q3hash.search.product", counted):
            report = generate_encodings((2,), SearchConstraints(allowed_dimensions=tuple(range(2, 33)),
                                                               max_registers=8, max_dimension_tuples=1))
        self.assertEqual(report.stop_reason, "dimension-budget")
        self.assertEqual(consumed, [(2,), (3,)])
        self.assertEqual(report.dimension_tuples_seen, 1)

    def test_digest_collision_does_not_merge_unequal_encodings(self):
        with patch("q3hash.search._encoding_id", return_value="0" * 64):
            with self.assertRaisesRegex(ValueError, "^Q3-SEARCH-004"):
                generate_encodings((2,), SearchConstraints(max_registers=1))

    def test_independent_tensor_label_and_event_trace_oracle(self):
        path = Path(__file__).resolve().parents[1] / "tools/check_search_generation.py"
        spec = importlib.util.spec_from_file_location("independent_search_audit", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        count = module.audit()
        self.assertGreaterEqual(count, 100)


if __name__ == "__main__":
    unittest.main()
