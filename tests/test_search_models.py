"""Strict model, provenance, serialization and replay tests for bounded generation."""

from dataclasses import FrozenInstanceError, replace
import hashlib
import itertools
import json
import unittest

from q3hash import (BasisEncoding, DimensionRejections, EncodingCandidate,
                    GenerationReport, SearchConstraints, generate_encodings)
from q3hash._serialization import MAX_JSON_BYTES


class SearchModelTests(unittest.TestCase):
    def assert_code(self, error_type, code, callback):
        with self.assertRaisesRegex(error_type, "^" + code):
            callback()

    def test_constraints_validate_every_scalar_boundary_and_type(self):
        limits = {"max_registers": (1, 8), "max_physical_size": (2, 64),
                  "max_dimension_tuples": (1, 65536), "max_mapping_attempts": (1, 262144),
                  "max_candidates": (1, 4096), "max_verifications": (1, 256),
                  "max_operations_per_program": (1, 16384), "max_gate_column_steps": (1, 4194304)}
        for name, (low, high) in limits.items():
            for value in (low, high):
                with self.subTest(name=name, value=value):
                    self.assertEqual(getattr(SearchConstraints(**{name: value}), name), value)
            for value in (low - 1, high + 1):
                self.assert_code(ValueError, "Q3-SEARCH-001", lambda: SearchConstraints(**{name: value}))
            for value in (True, 1.0, "1", None):
                self.assert_code(TypeError, "Q3-SEARCH-001", lambda: SearchConstraints(**{name: value}))

    def test_constraints_reject_noncanonical_tuple_values(self):
        cases = [("allowed_dimensions", value) for value in
                 ((), (3, 2), (2, 2), (True,), (2.0,), ("2",), (1,), (33,))]
        cases += [("mapping_families", value) for value in
                  ((), ("other",), ("register-prefix", "flat-prefix"),
                   ("flat-prefix", "flat-prefix"), (2,))]
        cases += [("objectives", value) for value in
                  ((), ("other",), ("gate_count", "gate_count"), (2,))]
        for name, value in cases:
            with self.subTest(name=name, value=value):
                self.assert_code(ValueError, "Q3-SEARCH-001", lambda: SearchConstraints(**{name: value}))
        for name in ("allowed_dimensions", "mapping_families", "objectives"):
            self.assert_code(TypeError, "Q3-SEARCH-001", lambda: SearchConstraints(**{name: []}))
        self.assert_code(TypeError, "Q3-SEARCH-001", lambda: SearchConstraints(
            allowed_dimensions=(1,), objectives=[]))

    def test_constraints_are_immutable_fresh_and_canonical(self):
        constraints = SearchConstraints(objectives=("gate_count", "physical_registers"))
        with self.assertRaises(FrozenInstanceError):
            constraints.max_registers = 8
        value = constraints.to_dict()
        value["allowed_dimensions"].append(7)
        self.assertEqual(constraints.allowed_dimensions, (2, 3))
        encoded = constraints.to_json()
        self.assertEqual(SearchConstraints.from_json(encoded), constraints)
        reversed_keys = dict(reversed(list(constraints.to_dict().items())))
        self.assertEqual(SearchConstraints.from_dict(reversed_keys).to_json(), encoded)
        self.assertFalse(encoded.endswith("\n"))

    def test_constraints_wire_rejects_types_fields_and_versions(self):
        for field, value in (("max_registers", True), ("max_candidates", 3.0),
                             ("allowed_dimensions", [2.0]), ("objectives", [True]),
                             ("mapping_families", "flat-prefix")):
            body = SearchConstraints().to_dict()
            body[field] = value
            self.assert_code(ValueError, "Q3-SER-003", lambda: SearchConstraints.from_dict(body))
        for update in ({"schema": "unknown"}, {"schema_version": 2}, {"schema_version": True}):
            body = {**SearchConstraints().to_dict(), **update}
            self.assert_code(ValueError, "Q3-SER-004", lambda: SearchConstraints.from_dict(body))
        body = SearchConstraints().to_dict()
        body["extra"] = 1
        self.assert_code(ValueError, "Q3-SER-003", lambda: SearchConstraints.from_dict(body))
        del body["extra"], body["objectives"]
        self.assert_code(ValueError, "Q3-SER-003", lambda: SearchConstraints.from_dict(body))
        self.assert_code(TypeError, "Q3-SER-003", lambda: SearchConstraints.from_json("[]"))
        self.assert_code(TypeError, "Q3-SER-001", lambda: SearchConstraints.from_json(b"{}"))

    def test_candidate_id_hashes_canonical_encoding_and_preserves_provenance(self):
        encoding = BasisEncoding((2, 3), (2, 2, 2), (0, 1, 2, 4, 5, 6))
        candidate = EncodingCandidate(encoding, "register-prefix", block_cuts=(1,))
        independent_json = json.dumps({"schema": "q3hash.basis-encoding", "schema_version": 1,
            "kind": "basis-injection", "logical_dimensions": [2, 3],
            "physical_dimensions": [2, 2, 2], "physical_basis_indices": [0, 1, 2, 4, 5, 6]},
            sort_keys=True, separators=(",", ":"))
        self.assertEqual(candidate.candidate_id, hashlib.sha256(independent_json.encode()).hexdigest())
        self.assertEqual(EncodingCandidate.from_dict(candidate.to_dict()), candidate)
        self.assertEqual(EncodingCandidate(BasisEncoding((3,), (2, 2), (0, 1, 2)),
                                           "register-prefix", block_cuts=()).block_cuts, ())
        body = candidate.to_dict()
        body["encoding"]["physical_basis_indices"][0] = 7
        self.assertEqual(candidate.encoding.physical_basis_indices[0], 0)
        with self.assertRaises(FrozenInstanceError):
            candidate.origin = "seed"

    def test_candidate_rejects_false_origin_and_partition_claims(self):
        flat = BasisEncoding((2, 3), (2, 2, 2), (0, 1, 2, 3, 4, 5))
        blocked = BasisEncoding((2, 3), (2, 2, 2), (0, 1, 2, 4, 5, 6))
        cases = [lambda: EncodingCandidate(flat, "unknown"),
                 lambda: EncodingCandidate(blocked, "flat-prefix"),
                 lambda: EncodingCandidate(flat, "flat-prefix", seed_index=0),
                 lambda: EncodingCandidate(flat, "seed"),
                 lambda: EncodingCandidate(flat, "seed", seed_index=-1),
                 lambda: EncodingCandidate(flat, "seed", seed_index=4096),
                 lambda: EncodingCandidate(flat, "seed", seed_index=0, block_cuts=()),
                 lambda: EncodingCandidate(blocked, "register-prefix", block_cuts=(2,)),
                 lambda: EncodingCandidate(blocked, "register-prefix", block_cuts=(True,)),
                 lambda: EncodingCandidate(blocked, "register-prefix", block_cuts=(0,)),
                 lambda: EncodingCandidate(blocked, "register-prefix", block_cuts=(1, 2)),
                 lambda: EncodingCandidate(flat, "register-prefix", block_cuts=(1,)),
                 lambda: EncodingCandidate(BasisEncoding((2,), (3, 3, 3, 3), (0, 1)), "seed", seed_index=0)]
        for callback in cases:
            self.assert_code(ValueError, "Q3-SEARCH-005", callback)
        self.assert_code(TypeError, "Q3-SEARCH-005", lambda: EncodingCandidate(flat, "seed", seed_index=True))
        self.assert_code(TypeError, "Q3-SEARCH-005", lambda: EncodingCandidate(flat, "register-prefix", block_cuts=[1]))

    def test_candidate_wire_ids_and_nested_types_fail_closed(self):
        candidate = EncodingCandidate(BasisEncoding((3,), (2, 2), (0, 1, 2)), "flat-prefix")
        body = candidate.to_dict()
        body["candidate_id"] = "0" * 64
        self.assert_code(ValueError, "Q3-SEARCH-005", lambda: EncodingCandidate.from_dict(body))
        for field, value in (("encoding", []), ("candidate_id", 1), ("seed_index", 0.0)):
            body = {**candidate.to_dict(), field: value}
            self.assert_code(ValueError, "Q3-SER-003", lambda: EncodingCandidate.from_dict(body))

    def test_report_round_trip_is_immutable_and_fresh(self):
        report = generate_encodings((3,), SearchConstraints(max_registers=2, max_physical_size=9))
        self.assertEqual(GenerationReport.from_json(report.to_json()), report)
        self.assertEqual(GenerationReport(**{name: getattr(report, name)
                         for name in report.__dataclass_fields__}), report)
        with self.assertRaises(FrozenInstanceError):
            report.completion = "truncated"
        with self.assertRaises(FrozenInstanceError):
            report.dimension_rejections.insufficient_capacity = 0
        body = report.to_dict()
        body["candidates"][0]["encoding"]["physical_basis_indices"][0] = 2
        body["dimension_rejections"]["insufficient-capacity"] = 99
        self.assertEqual(report.candidates[0].encoding.physical_basis_indices[0], 0)
        self.assertEqual(report.dimension_rejections.insufficient_capacity, 1)

    def test_report_rejects_forged_counts_order_completion_and_provenance(self):
        report = generate_encodings((3,), SearchConstraints(max_registers=2, max_physical_size=9))
        for update in ({"mapping_attempts": 0}, {"emitted_candidates": 0},
                       {"dimension_tuples_seen": 5}, {"family_unavailable": 1},
                       {"completion": "truncated", "stop_reason": "dimension-budget"},
                       {"completion": "exhausted", "stop_reason": "candidate-budget"},
                       {"candidates": tuple(reversed(report.candidates))},
                       {"candidates": (report.candidates[0],) * len(report.candidates)},
                       {"dimension_rejections": DimensionRejections(0, 0)}):
            with self.subTest(update=update):
                self.assert_code(ValueError, "Q3-SEARCH-005", lambda: replace(report, **update))
        self.assert_code(TypeError, "Q3-SEARCH-005", lambda: replace(report, candidates=list(report.candidates)))
        self.assert_code(TypeError, "Q3-SEARCH-005", lambda: replace(report, mapping_attempts=True))
        body = report.to_dict()
        body["candidates"][0]["origin"] = "register-prefix"
        body["candidates"][0]["block_cuts"] = []
        self.assert_code(ValueError, "Q3-SEARCH-005", lambda: GenerationReport.from_dict(body))

    def test_report_wire_rejects_unknown_nested_fields_and_bad_scalars(self):
        self.assert_code(TypeError, "Q3-SEARCH-005", lambda: DimensionRejections(-1, True))
        report = generate_encodings((2,), SearchConstraints(max_registers=1))
        for field, value in (("mapping_attempts", True), ("completion", 1),
                             ("logical_dimensions", [2.0]), ("constraints", []),
                             ("candidates", [None]), ("dimension_rejections", {})):
            body = {**report.to_dict(), field: value}
            self.assert_code(ValueError, "Q3-SER-003", lambda: GenerationReport.from_dict(body))
        body = report.to_dict()
        body["candidates"][0]["extra"] = "forged"
        self.assert_code(ValueError, "Q3-SER-003", lambda: GenerationReport.from_dict(body))
        body = report.to_dict()
        body["schema_version"] = True
        self.assert_code(ValueError, "Q3-SER-004", lambda: GenerationReport.from_dict(body))
        self.assert_code(TypeError, "Q3-SER-003", lambda: GenerationReport.from_json("[]"))

    def test_report_json_rejects_duplicates_unicode_nonfinite_and_oversize(self):
        for text, code in (("{\"schema\":1,\"schema\":2}", "Q3-SER-002"),
                           ("{\"a\":{\"x\":1,\"x\":2}}", "Q3-SER-002"),
                           ("{\"x\":NaN}", "Q3-SER-001"),
                           ('"\\ud800"', "Q3-SER-001"),
                           (" " * (MAX_JSON_BYTES + 1), "Q3-SER-001")):
            self.assert_code(ValueError, code, lambda: GenerationReport.from_json(text))
        report = generate_encodings((2,), SearchConstraints(max_registers=1))
        text = report.to_json()
        self.assertEqual(GenerationReport.from_json(text + " " * (MAX_JSON_BYTES - len(text))), report)

    def test_large_valid_report_refuses_wire_overflow_without_losing_maps(self):
        dimensions = (2,) * 6
        seeds = tuple(BasisEncoding(dimensions, dimensions, mapping)
                      for mapping in itertools.islice(itertools.permutations(range(64)), 2048))
        constraints = SearchConstraints(allowed_dimensions=(2,), max_registers=6,
            max_candidates=2048, max_mapping_attempts=2050, max_dimension_tuples=6)
        report = generate_encodings(dimensions, constraints, seed_encodings=seeds)
        self.assertEqual(report.completion, "exhausted")
        self.assertEqual(report.emitted_candidates, 2048)
        self.assert_code(ValueError, "Q3-SER-001", report.to_json)
        self.assertEqual(len(report.candidates), 2048)


if __name__ == "__main__":
    unittest.main()
