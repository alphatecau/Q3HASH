"""Normative logical IR, exact basis-map and fail-closed wire contract vectors."""

from dataclasses import FrozenInstanceError
import json
import math
import unittest

from q3hash import (BasisEncoding, CircuitIR, LogicalProgram, Register, apply_state,
                    logical_from_source, lower, parse, simulate)


class LogicalContractTests(unittest.TestCase):
    def test_source_adapter_preserves_interleaving_and_resolved_semantics(self):
        source = "qubit a\nfourier a\nqutrit b\nsum a b"
        program = logical_from_source(source)
        self.assertEqual(program.ir, lower(parse(source)))
        self.assertEqual(program.dimensions, (2, 3))
        self.assertEqual(program.state_size, 6)
        self.assertEqual(LogicalProgram.from_json(program.to_json()), program)
        self.assertEqual([op["control"] for op in program.to_dict()["operations"]], [None, 0])
        self.assertEqual(LogicalProgram.from_dict(program.to_dict()).ir, program.ir)

    def test_identity_program_and_large_ir_require_no_state_allocation(self):
        program = LogicalProgram(CircuitIR((Register("q", 2),), ()))
        self.assertEqual(program.to_dict()["operations"], [])
        large = logical_from_source("\n".join(f"qudit 32 q{i}" for i in range(4)))
        self.assertEqual(large.state_size, 1_048_576)
        with self.assertRaisesRegex(ValueError, "statevector too large"):
            simulate(large.ir)

    def test_logical_type_validation_and_source_diagnostics(self):
        for invalid in (None, "qutrit q", parse("qutrit q")):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(TypeError, "Q3-LIR-001"):
                LogicalProgram(invalid)
        with self.assertRaisesRegex(ValueError, "line 2: unknown register"):
            logical_from_source("qutrit q\nsum q missing")

    def test_to_dict_is_fresh_and_logical_model_is_frozen(self):
        program = logical_from_source("qubit a\nqutrit b\nsum a b")
        data = program.to_dict()
        data["registers"][0]["name"] = "changed"
        data["operations"].clear()
        self.assertEqual(program.ir.registers[0].name, "a")
        self.assertEqual(len(program.ir.operations), 1)
        with self.assertRaises(FrozenInstanceError):
            program.ir = None


class BasisEncodingContractTests(unittest.TestCase):
    def test_qutrit_isometry_and_linear_zero_and_unnormalised_vectors(self):
        encoding = BasisEncoding((3,), (2, 2), (0, 1, 2))
        self.assertEqual(encoding.encode_vector((2, 1j, -3)), (2 + 0j, 1j, -3 + 0j, 0j))
        self.assertEqual(encoding.encode_vector((0, 0, 0)), (0j,) * 4)
        matrix = encoding.isometry_matrix()
        for left in range(3):
            for right in range(3):
                self.assertEqual(sum(row[left].conjugate() * row[right] for row in matrix), int(left == right))
        self.assertEqual(matrix[3], (0j, 0j, 0j))
        self.assertTrue(all(type(value) is complex for row in matrix for value in row))

    def test_nontrivial_mixed_order_and_map_permutation(self):
        encoding = BasisEncoding((2, 3), (3, 2), (5, 0, 4, 1, 3, 2))
        self.assertEqual(encoding.encode_vector((0, 1, 2, 3, 4, 5)), (1, 3, 5, 4, 2, 0))
        self.assertEqual(BasisEncoding.from_json(encoding.to_json()), encoding)
        altered = BasisEncoding((2, 3), (3, 2), tuple(reversed(encoding.physical_basis_indices)))
        self.assertNotEqual(altered.to_json(), encoding.to_json())

    def test_exact_tuple_and_dimension_requirements(self):
        for logical, physical, mapping, code in [
                ([3], (2, 2), (0, 1, 2), "001"),
                ((3,), [2, 2], (0, 1, 2), "001"),
                ((3,), (2, 2), [0, 1, 2], "003")]:
            with self.subTest(logical=logical, physical=physical), self.assertRaisesRegex(TypeError, "Q3-ENC-" + code):
                BasisEncoding(logical, physical, mapping)
        for dimensions in ((), (True,), (1,), (33,), (3.0,), ("3",)):
            with self.subTest(dimensions=dimensions), self.assertRaisesRegex(ValueError, "Q3-ENC-001"):
                BasisEncoding(dimensions, (4,), (0, 1, 2))

    def test_mapping_capacity_type_range_and_injection_diagnostics(self):
        cases = [((3,), (2,), (0, 1, 2), "002"),
                 ((3,), (4,), (0, 1), "003"), ((3,), (4,), (0, True, 2), "003"),
                 ((3,), (4,), (0, 1.0, 2), "003"), ((3,), (4,), (0, -1, 2), "005"),
                 ((3,), (4,), (0, 4, 2), "005"), ((3,), (4,), (0, 1, 1), "004")]
        for logical, physical, mapping, code in cases:
            with self.subTest(mapping=mapping, code=code), self.assertRaisesRegex(ValueError, "Q3-ENC-" + code):
                BasisEncoding(logical, physical, mapping)
        # Range precedes uniqueness, and explicit-map cap precedes map length.
        with self.assertRaisesRegex(ValueError, "Q3-ENC-005"):
            BasisEncoding((3,), (4,), (-1, -1, 2))
        with self.assertRaisesRegex(ValueError, "Q3-ENC-006"):
            BasisEncoding((32, 32, 32, 3), (32, 32, 32, 3), ())

    def test_large_physical_space_is_representable_but_allocations_are_bounded(self):
        encoding = BasisEncoding((3,), (32, 32, 32, 32), (0, 1, 2))
        self.assertEqual(encoding.physical_size, 1_048_576)
        self.assertEqual(BasisEncoding.from_json(encoding.to_json()), encoding)
        with self.assertRaisesRegex(ValueError, "Q3-STATE-003"):
            encoding.encode_vector((0, 0, 0))
        with self.assertRaisesRegex(ValueError, "Q3-DENSE-001"):
            encoding.isometry_matrix()
        small = BasisEncoding((2,), (5, 13), (0, 64))
        with self.assertRaisesRegex(ValueError, "Q3-DENSE-001"):
            small.isometry_matrix()
        self.assertEqual(len(small.isometry_matrix(max_physical_dimension=65)), 65)
        for limit in (True, 64.0, None):
            with self.subTest(limit=limit), self.assertRaisesRegex(TypeError, "Q3-DENSE-001"):
                small.isometry_matrix(max_physical_dimension=limit)
        for limit in (0, -1):
            with self.assertRaisesRegex(ValueError, "Q3-DENSE-001"):
                small.isometry_matrix(max_physical_dimension=limit)

    def test_vector_validation_rejects_coercion_nonfinite_and_unrepresentable_values(self):
        encoding = BasisEncoding((2,), (2,), (0, 1))
        for container in ([1, 0], "10", iter((1, 0)), None):
            with self.subTest(container=container), self.assertRaisesRegex(TypeError, "Q3-STATE-001"):
                encoding.encode_vector(container)
        for values in ((1,), (True, 0), ("1", 0), (object(), 0)):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, "Q3-STATE-001"):
                encoding.encode_vector(values)
        for values in ((float("nan"), 0), (float("inf"), 0), (complex(0, float("inf")), 0), (10 ** 1000, 0)):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, "Q3-STATE-002"):
                encoding.encode_vector(values)

    def test_dictionary_is_fresh_and_model_is_frozen(self):
        encoding = BasisEncoding((3,), (4,), (0, 1, 2))
        data = encoding.to_dict()
        data["physical_basis_indices"].reverse()
        self.assertEqual(encoding.physical_basis_indices, (0, 1, 2))
        with self.assertRaises(FrozenInstanceError):
            encoding.physical_dimensions = (3,)


class SerializationContractTests(unittest.TestCase):
    def test_canonical_key_order_no_newline_and_exact_roundtrip(self):
        for model in (logical_from_source("qutrit q\nfourier q"), BasisEncoding((3,), (4,), (2, 0, 1))):
            data = model.to_dict()
            reordered = dict(reversed(list(data.items())))
            clone = type(model).from_json(json.dumps(reordered, indent=2))
            self.assertEqual(clone, model)
            self.assertEqual(clone.to_json(), model.to_json())
            self.assertFalse(model.to_json().endswith("\n"))
            self.assertEqual(model.to_json(), json.dumps(data, sort_keys=True, separators=(",", ":"),
                                                         ensure_ascii=False, allow_nan=False))

    def test_duplicate_keys_malformed_unicode_nonfinite_and_oversize_json(self):
        invalid = [('{"schema":1,"schema":2}', "002"),
                   ('{"outer":{"x":1,"x":2}}', "002"),
                   ('{"x":NaN}', "001"), ('{"x":Infinity}', "001"),
                   ('{"x":1e999}', "001"), ('{"x":"\\ud800"}', "001"),
                   ("\ud800", "001"), ("{", "001"), (" " * 1_048_577, "001")]
        for model in (LogicalProgram, BasisEncoding):
            for text, code in invalid:
                with self.subTest(model=model, text=text[:30]), self.assertRaisesRegex(ValueError, "Q3-SER-" + code):
                    model.from_json(text)
            with self.assertRaisesRegex(TypeError, "Q3-SER-001"):
                model.from_json(b"{}")
            with self.assertRaisesRegex(TypeError, "Q3-SER-003"):
                model.from_dict([])
            with self.assertRaisesRegex(TypeError, "Q3-SER-003"):
                model.from_json("[]")

    def test_exact_wire_budget_accepts_valid_json_and_output_budget_is_symmetric(self):
        encoding = BasisEncoding((3,), (4,), (0, 1, 2))
        text = encoding.to_json()
        text += " " * (1_048_576 - len(text.encode("utf-8")))
        self.assertEqual(BasisEncoding.from_json(text), encoding)
        huge = BasisEncoding((32, 32, 32, 2), (32,) * 13,
                             tuple(10 ** 19 + index for index in range(65_536)))
        with self.assertRaisesRegex(ValueError, "Q3-SER-001"):
            huge.to_json()

    def test_schema_versions_unknown_fields_and_nested_types_fail_closed(self):
        for model in (logical_from_source("qutrit q\nfourier q"), BasisEncoding((3,), (4,), (0, 1, 2))):
            for version in (True, 1.0, "1", 2, None):
                data = model.to_dict()
                data["schema_version"] = version
                with self.subTest(version=version), self.assertRaisesRegex(ValueError, "Q3-SER-004"):
                    type(model).from_dict(data)
            for change in ("missing", "unknown"):
                data = model.to_dict()
                if change == "missing":
                    data.pop("schema")
                else:
                    data["extra"] = 1
                with self.assertRaisesRegex(ValueError, "Q3-SER-003"):
                    type(model).from_dict(data)
            data = model.to_dict()
            data["schema"] = "q3hash.unknown"
            with self.assertRaisesRegex(ValueError, "Q3-SER-004"):
                type(model).from_dict(data)
        program = logical_from_source("qutrit q\nfourier q")
        for key, value in (("dimension", True), ("dimension", 3.0), ("name", 3)):
            data = program.to_dict()
            data["registers"][0][key] = value
            with self.assertRaisesRegex(ValueError, "Q3-SER-003"):
                LogicalProgram.from_dict(data)
        data = program.to_dict()
        data["operations"][0].pop("control")
        with self.assertRaisesRegex(ValueError, "Q3-SER-003"):
            LogicalProgram.from_dict(data)
        data = BasisEncoding((3,), (4,), (0, 1, 2)).to_dict()
        data["kind"] = "unverified-inference"
        with self.assertRaisesRegex(ValueError, "Q3-SER-004"):
            BasisEncoding.from_dict(data)
        for value in (True, 1.0, "1"):
            data = BasisEncoding((3,), (4,), (0, 1, 2)).to_dict()
            data["physical_basis_indices"][1] = value
            with self.assertRaisesRegex(ValueError, "Q3-SER-003"):
                BasisEncoding.from_dict(data)


class ArbitraryStateTests(unittest.TestCase):
    def test_apply_state_is_linear_without_renormalisation(self):
        circuit = parse("qutrit q\nfourier q\nshift q")
        left, right = (2, 1j, -3), (1j, -2, 4)
        combined = tuple(2 * a - 3j * b for a, b in zip(left, right))
        actual = apply_state(circuit, combined)
        expected = tuple(2 * a - 3j * b for a, b in zip(apply_state(circuit, left), apply_state(circuit, right)))
        self.assertLess(max(abs(a - b) for a, b in zip(actual, expected)), 1e-12)
        self.assertEqual(apply_state(circuit, (0, 0, 0)), (0j,) * 3)
        self.assertEqual(simulate(circuit), apply_state(circuit, (1, 0, 0)))

    def test_apply_state_limits_types_and_unrepresentable_outputs(self):
        with self.assertRaises(TypeError):
            apply_state("qubit q", (1, 0))
        with self.assertRaisesRegex(TypeError, "Q3-STATE-001"):
            apply_state(parse("qubit q"), [1, 0])
        large = parse("\n".join(f"qudit 32 q{i}" for i in range(4)))
        with self.assertRaisesRegex(ValueError, "Q3-STATE-003"):
            apply_state(large, ())
        with self.assertRaisesRegex(ValueError, "Q3-STATE-002"):
            apply_state(parse("qubit q\nfourier q"), (1.7e308, 1.7e308))


if __name__ == "__main__":
    unittest.main()
