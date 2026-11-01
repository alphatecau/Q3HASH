"""Hardware input boundaries, canonical identities and strict wire acceptance."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from q3hash import (DEFAULT_HARDWARE_OBJECTIVES, HARDWARE_OBJECTIVES, ErrorRange, GateKind,
                    HardwareContext, HardwarePlacement, HardwareProfile, NativeBinding,
                    ProfileProvenance, TimeRange)
from q3hash._serialization import MAX_JSON_BYTES


AT = "2026-11-01T00:00:00Z"


def provenance(**changes):
    values = dict(kind="synthetic", provider="Q3# fixture", device_id="hybrid", snapshot_id="v1",
                  source_uri="urn:q3hash:synthetic:hybrid", retrieved_at=AT, calibrated_at=None, notes="")
    return ProfileProvenance(**{**values, **changes})


def profile(**changes):
    values = dict(name="tiny", site_dimensions=(3, 2), couplings=((1, 0),), bindings=(
        NativeBinding(GateKind.SHIFT, (0,), TimeRange(0, 10), None),
        NativeBinding(GateKind.SUM, (1, 0), None, ErrorRange("average-gate-infidelity", 0, 1))),
        provenance=provenance())
    return HardwareProfile(**{**values, **changes})


class HardwareModelTests(unittest.TestCase):
    def assert_code(self, kind, code, callback):
        with self.assertRaisesRegex(kind, "^" + code):
            callback()

    def test_time_bounds_preserve_large_integer_ticks_and_distinguish_unknown(self):
        for bounds in ((0, 0), (0, 10**15), (2**53 + 1, 16384 * 10**15)):
            value = TimeRange(*bounds)
            self.assertEqual(TimeRange.from_json(value.to_json()), value)
            self.assertEqual(tuple(value.to_dict().values()), bounds)
        for bounds in ((-1, 0), (2, 1), (0, 16384 * 10**15 + 1)):
            self.assert_code(ValueError, "Q3-HARD-002", lambda: TimeRange(*bounds))
        for value in (True, 1.0, None, "1"):
            self.assert_code(TypeError, "Q3-HARD-001", lambda: TimeRange(value, 1))
        known = NativeBinding(GateKind.SHIFT, (0,), TimeRange(0, 0), None)
        unknown = replace(known, duration=None)
        self.assertNotEqual(known.to_json(), unknown.to_json())
        self.assert_code(ValueError, "Q3-HARD-002", lambda: replace(known, duration=TimeRange(0, 10**15 + 1)))

    def test_error_ranges_normalise_numbers_and_reject_invalid_probabilities(self):
        for metric in ("average-gate-infidelity", "process-infidelity", "reported-unspecified-error"):
            value = ErrorRange(metric, -0.0, 1)
            self.assertIs(type(value.lower), float)
            self.assertEqual(math.copysign(1.0, value.lower), 1)
            self.assertEqual(value.to_json(), ErrorRange(metric, 0, 1.0).to_json())
            self.assertEqual(ErrorRange.from_json(value.to_json()), value)
        for bounds in ((-0.1, 0), (0, 1.1), (1, 0), (float("nan"), 1), (0, float("inf")), (0, 10**1000)):
            self.assert_code(ValueError, "Q3-HARD-002", lambda: ErrorRange("average-gate-infidelity", *bounds))
        for value in (True, None, "0", 0j):
            self.assert_code(TypeError, "Q3-HARD-001", lambda: ErrorRange("average-gate-infidelity", value, 1))
        self.assert_code(ValueError, "Q3-HARD-002", lambda: ErrorRange("success-probability", 0, 1))

    def test_provenance_strings_and_valid_utf8_are_bounded(self):
        for name in ("provider", "device_id", "snapshot_id"):
            self.assertEqual(getattr(provenance(**{name: "é" * 128}), name), "é" * 128)
            for value in ("", "x" * 129, "\ud800"):
                self.assert_code(ValueError, "Q3-HARD-002", lambda: provenance(**{name: value}))
            self.assert_code(TypeError, "Q3-HARD-001", lambda: provenance(**{name: 1}))
        self.assertEqual(len(provenance(notes="🧪" * 4096).notes), 4096)
        for changes in ({"notes": "x" * 4097}, {"notes": "\ud800"}, {"kind": "measured"}):
            self.assert_code(ValueError, "Q3-HARD-002", lambda: provenance(**changes))

    def test_provenance_uris_are_metadata_and_validate_without_network(self):
        for uri in ("https://example.invalid/snapshot?version=1#calibration", "https://[::1]:443/data", "urn:q3hash:synthetic:test"):
            self.assertEqual(provenance(source_uri=uri).source_uri, uri)
        for uri in ("", "http://example.invalid", "/relative", "https:///missing", "https://u:p@example.invalid",
                    "https://u@example.invalid", "https://example.invalid:bad", "https://example.invalid:0",
                    "https://example.invalid:65536", "https://[bad", "https://example.invalid/ bad",
                    "https://example.invalid\n/path", "https://example.invalid\\bad", "urn:q3hash:synthetic:", "x" * 2049):
            self.assert_code(ValueError, "Q3-HARD-002", lambda: provenance(source_uri=uri))
        self.assert_code(ValueError, "Q3-HARD-002", lambda: provenance(kind="reported-device"))
        self.assertEqual(provenance(kind="reported-device", source_uri="https://example.invalid").calibrated_at, None)

    def test_timestamps_are_calendar_checked_explicit_second_precision_utc(self):
        for instant in ("1970-01-01T00:00:00Z", "2000-02-29T12:34:56Z", "9999-12-31T23:59:59Z"):
            self.assertEqual(provenance(retrieved_at=instant).retrieved_at, instant)
        for instant in ("1969-12-31T23:59:59Z", "2026-02-29T00:00:00Z", "2026-11-01T24:00:00Z",
                        "2026-11-01T00:00:60Z", "2026-11-01T00:00:00+00:00", "2026-11-01T00:00:00.0Z",
                        "2026-1-01T00:00:00Z", "２０２６-11-01T00:00:00Z", "2026-11-01"):
            self.assert_code(ValueError, "Q3-HARD-002", lambda: provenance(retrieved_at=instant))
        self.assert_code(ValueError, "Q3-HARD-002", lambda: provenance(calibrated_at=AT))
        for invalid in (True, 1, []):
            self.assert_code(TypeError, "Q3-HARD-001", lambda: provenance(calibrated_at=invalid))
        reported = dict(kind="reported-device", source_uri="https://example.invalid/snapshot")
        self.assertEqual(provenance(**reported, calibrated_at=AT).calibrated_at, AT)
        self.assert_code(ValueError, "Q3-HARD-002", lambda: provenance(**reported, calibrated_at="2026-11-01T00:00:01Z"))

    def test_native_bindings_require_gatekind_and_ordered_exact_indices(self):
        for kind, sites in ((GateKind.SHIFT, (0,)), (GateKind.FOURIER, (63,)), (GateKind.SUM, (63, 0))):
            value = NativeBinding(kind, sites, None, None)
            self.assertEqual(NativeBinding.from_json(value.to_json()), value)
        self.assert_code(TypeError, "Q3-HARD-001", lambda: NativeBinding("sum", (0, 1), None, None))
        for sites in ((), (0, 0), (-1, 0), (0, 64), (True, 0), (0.0, 1), (0,), (0, 1, 2)):
            self.assert_code(ValueError, "Q3-HARD-002", lambda: NativeBinding(GateKind.SUM, sites, None, None))
        for changes in ({"sites": [0]}, {"duration": {}}, {"error": {}}):
            self.assert_code(TypeError, "Q3-HARD-001", lambda: replace(profile().bindings[0], **changes))

    def test_profile_is_matrix_free_even_at_full_site_and_edge_capacity(self):
        edges = tuple((a, b) for a in range(64) for b in range(64) if a != b)
        bindings = tuple(NativeBinding(GateKind.SUM, edge, None, None) for edge in edges)
        value = profile(site_dimensions=(32,) * 64, couplings=edges, bindings=bindings)
        self.assertEqual(len(value.couplings), 4032)
        self.assertEqual(HardwareProfile.from_json(value.to_json()), value)
        self.assertEqual(len(value.profile_id), 64)
        self.assertEqual(profile(couplings=(), bindings=()).bindings, ())

    def test_profile_rejects_wrong_dimensions_container_types_and_name_bounds(self):
        for dimensions in ((), (2,) * 65, (1,), (33,), (True,), (2.0,)):
            self.assert_code(ValueError, "Q3-HARD-002", lambda: profile(site_dimensions=dimensions))
        for changes in ({"site_dimensions": [3, 2]}, {"couplings": []}, {"bindings": []},
                        {"provenance": {}}, {"name": 1}):
            self.assert_code(TypeError, "Q3-HARD-001", lambda: profile(**changes))
        for value in ("", "x" * 129, "\ud800"):
            self.assert_code(ValueError, "Q3-HARD-002", lambda: profile(name=value))
        self.assertEqual(profile(name="x" * 128).name, "x" * 128)

    def test_profile_rejects_unsorted_duplicate_invalid_and_unbound_edges(self):
        for edges in (((1, 0), (0, 1)), ((1, 0), (1, 0)), ((0, 0),), ((0, 2),), ((True, 0),), ((1,),), ((0, 1),) * 4033):
            self.assert_code(ValueError, "Q3-HARD-002", lambda: profile(couplings=edges))
        self.assert_code(TypeError, "Q3-HARD-001", lambda: profile(couplings=([1, 0],)))
        self.assert_code(ValueError, "Q3-HARD-002", lambda: profile(couplings=()))
        self.assert_code(ValueError, "Q3-HARD-002", lambda: profile(couplings=((0, 1),)))
        first, second = profile().bindings
        for bindings in ((second, first), (first, first), (first,) * 8193,
                         (NativeBinding(GateKind.SHIFT, (2,), None, None),)):
            self.assert_code(ValueError, "Q3-HARD-002", lambda: profile(bindings=bindings))
        self.assert_code(TypeError, "Q3-HARD-001", lambda: profile(bindings=({},)))

    def test_profile_identity_includes_provenance_order_dimensions_and_unknowns(self):
        value = profile()
        expected = hashlib.sha256(json.dumps(value.to_dict(), sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        self.assertEqual(value.profile_id, expected)
        variants = (replace(value, name="changed"), replace(value, site_dimensions=(2, 3)),
                    replace(value, provenance=replace(value.provenance, notes="new evidence")),
                    replace(value, bindings=(replace(value.bindings[0], duration=None), value.bindings[1])))
        self.assertEqual(len({value.profile_id, *(item.profile_id for item in variants)}), 5)
        self.assertNotIn("profile_id", value.to_dict())

    def test_context_integer_boundaries_and_forbidden_error_objectives(self):
        self.assertEqual(HardwareContext(AT, 0).objectives, DEFAULT_HARDWARE_OBJECTIVES)
        for name, low, high in (("max_calibration_age_seconds", 0, 31536000), ("max_gate_checks", 1, 4194304)):
            for number in (low, high):
                value = replace(HardwareContext(AT, 0), **{name: number})
                self.assertEqual(getattr(value, name), number)
            for number in (low - 1, high + 1):
                self.assert_code(ValueError, "Q3-HARD-001", lambda: replace(HardwareContext(AT, 0), **{name: number}))
            for number in (True, 1.0, "1", None):
                self.assert_code(TypeError, "Q3-HARD-001", lambda: replace(HardwareContext(AT, 0), **{name: number}))
        for names in ((), ("circuit_error",), ("success_probability",), ("active_sites",) * 2, (True,)):
            self.assert_code(ValueError, "Q3-HARD-001", lambda: HardwareContext(AT, 0, objectives=names))
        self.assert_code(TypeError, "Q3-HARD-001", lambda: HardwareContext(AT, 0, objectives=[]))

    def test_context_canonical_identity_preserves_objective_order(self):
        value = HardwareContext(AT, 10, objectives=HARDWARE_OBJECTIVES)
        self.assertEqual(HardwareContext.from_json(value.to_json()), value)
        self.assertEqual(value.context_id, hashlib.sha256(value.to_json().encode()).hexdigest())
        for changes in ({"as_of": "2026-11-01T00:00:01Z"}, {"max_gate_checks": 1},
                        {"max_calibration_age_seconds": 11}, {"objectives": tuple(reversed(value.objectives))}):
            self.assertNotEqual(replace(value, **changes).context_id, value.context_id)

    def test_context_validates_relative_instants_without_clock_calls(self):
        value = profile(provenance=provenance(kind="reported-device", source_uri="https://example.invalid",
                                             calibrated_at="2026-10-31T23:00:00Z"))
        with patch("q3hash.hardware_models.datetime") as clock:
            # Permit explicit parsing; fail if any implementation starts consulting now().
            from datetime import datetime
            clock.strptime.side_effect = datetime.strptime
            clock.now.side_effect = AssertionError("hidden current clock")
            HardwareContext(AT, 3600).validate_profile(value)
        self.assert_code(ValueError, "Q3-HARD-001", lambda: HardwareContext("2026-10-31T23:59:59Z", 3600).validate_profile(value))
        self.assert_code(TypeError, "Q3-HARD-001", lambda: HardwareContext(AT, 0).validate_profile({}))

    def test_placement_ids_are_strict_and_arity_validates_against_explicit_profile(self):
        value = HardwarePlacement("a" * 64, (1, 0))
        self.assertEqual(HardwarePlacement.from_json(value.to_json()), value)
        value.validate_for(profile(), (2, 3))
        value.validate_for(profile(), (3, 2))  # Dimension mismatch is a valid future unsupported outcome.
        for digest in ("", "a" * 63, "A" * 64, "g" * 64):
            self.assert_code(ValueError, "Q3-HARD-003", lambda: HardwarePlacement(digest, (0,)))
        for sites in ((), (0,) * 2, (True,), (1.0,), (-1,), (64,), tuple(range(65))):
            self.assert_code(ValueError, "Q3-HARD-003", lambda: HardwarePlacement("a" * 64, sites))
        self.assert_code(TypeError, "Q3-HARD-001", lambda: HardwarePlacement(1, (0,)))
        self.assert_code(TypeError, "Q3-HARD-001", lambda: HardwarePlacement("a" * 64, [0]))
        for sites, dimensions in (((0,), (2, 3)), ((2,), (3,))):
            self.assert_code(ValueError, "Q3-HARD-003", lambda: HardwarePlacement("a" * 64, sites).validate_for(profile(), dimensions))
        for dimensions in ((), (True,), (1,), (33,)):
            self.assert_code(ValueError, "Q3-HARD-003", lambda: value.validate_for(profile(), dimensions))

    def test_placement_identity_includes_physical_program_profile_and_site_order(self):
        value = HardwarePlacement("a" * 64, (1, 0))
        body = dict(schema="q3hash.hardware-placement-key", schema_version=1, candidate_id=value.candidate_id,
                    profile_id="b" * 64, physical_id="c" * 64, site_indices=[1, 0])
        expected = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(value.identifier("b" * 64, "c" * 64), expected)
        variants = (value.identifier("d" * 64, "c" * 64), value.identifier("b" * 64, "d" * 64),
                    replace(value, site_indices=(0, 1)).identifier("b" * 64, "c" * 64),
                    replace(value, candidate_id="d" * 64).identifier("b" * 64, "c" * 64))
        self.assertEqual(len({expected, *variants}), 5)
        self.assert_code(ValueError, "Q3-HARD-003", lambda: value.identifier("bad", "c" * 64))

    def test_models_are_frozen_and_decoded_containers_are_fresh(self):
        value = profile()
        for item, name in ((value, "name"), (value.provenance, "notes"), (value.bindings[0], "sites"),
                           (value.bindings[0].duration, "lower_ps"), (value.bindings[1].error, "lower"),
                           (HardwareContext(AT, 0), "as_of"), (HardwarePlacement("a" * 64, (0,)), "candidate_id")):
            with self.assertRaises(FrozenInstanceError):
                setattr(item, name, None)
        body = value.to_dict()
        restored = HardwareProfile.from_dict(body)
        body["couplings"][0][0] = 0
        body["bindings"][0]["duration"]["upper_ps"] = 100
        body["provenance"]["notes"] = "changed"
        self.assertEqual(restored, value)
        self.assertEqual(value.bindings[0].duration.upper_ps, 10)

    def test_wire_headers_and_unknown_nested_fields_fail_closed(self):
        for cls, original in ((HardwareProfile, profile().to_dict()), (HardwareContext, HardwareContext(AT, 0).to_dict())):
            for field, item, code in (("schema", "wrong", "Q3-SER-004"), ("schema_version", True, "Q3-SER-004"),
                                     ("schema_version", 2, "Q3-SER-004"), ("extra", 1, "Q3-SER-003")):
                self.assert_code(ValueError, code, lambda: cls.from_dict({**original, field: item}))
        for field in ("duration", "error"):
            body = profile().to_dict()
            body["bindings"][1][field] = {"extra": 1}
            self.assert_code(ValueError, "Q3-SER-003", lambda: HardwareProfile.from_dict(body))
        for field in ("bindings", "couplings", "provenance"):
            body = profile().to_dict()
            body[field] = {} if field != "provenance" else []
            self.assert_code(ValueError, "Q3-SER-003", lambda: HardwareProfile.from_dict(body))

    def test_wire_rejects_bool_float_and_nested_object_substitutions(self):
        mutations = [lambda x: x.update(name=True), lambda x: x["site_dimensions"].__setitem__(0, 3.0),
                     lambda x: x["couplings"][0].__setitem__(0, True), lambda x: x["bindings"][0].update(kind=1),
                     lambda x: x["bindings"][0].update(duration=[]),
                     lambda x: x["bindings"][0]["duration"].update(upper_ps=10.0),
                     lambda x: x["bindings"][1]["error"].update(lower=True),
                     lambda x: x["provenance"].update(calibrated_at=1)]
        for mutation in mutations:
            body = profile().to_dict()
            mutation(body)
            self.assert_code(ValueError, "Q3-SER-003", lambda: HardwareProfile.from_dict(body))
        self.assert_code(ValueError, "Q3-SER-003", lambda: HardwareContext.from_dict({**HardwareContext(AT, 0).to_dict(), "max_gate_checks": True}))
        self.assert_code(ValueError, "Q3-SER-003", lambda: HardwarePlacement.from_dict({"candidate_id": "a" * 64, "site_indices": [0.0]}))

    def test_wire_uses_symmetric_utf8_budget_and_rejects_duplicates_and_nonfinite(self):
        for text, code in (("{\"schema\":1,\"schema\":2}", "Q3-SER-002"), ("{\"x\":{\"a\":1,\"a\":2}}", "Q3-SER-002"),
                           ("{\"x\":NaN}", "Q3-SER-001"), ("{\"x\":1e999}", "Q3-SER-001"),
                           ('"\\ud800"', "Q3-SER-001"), (" " * (MAX_JSON_BYTES + 1), "Q3-SER-001")):
            self.assert_code(ValueError, code, lambda: HardwareProfile.from_json(text))
        value = profile(name="é")
        text = value.to_json()
        padded = text + " " * (MAX_JSON_BYTES - len(text.encode()))
        self.assertEqual(HardwareProfile.from_json(padded), value)
        self.assert_code(ValueError, "Q3-SER-001", lambda: HardwareProfile.from_json(padded + " "))
        with patch("q3hash._serialization.MAX_JSON_BYTES", len(text.encode()) - 1):
            self.assert_code(ValueError, "Q3-SER-001", value.to_json)
            self.assert_code(ValueError, "Q3-SER-001", lambda: value.profile_id)
        self.assert_code(TypeError, "Q3-SER-001", lambda: HardwareProfile.from_json(b"{}"))

    def test_fixed_profiles_context_and_targets_use_production_input_models(self):
        fixture = json.loads((Path(__file__).resolve().parents[1] / "benchmarks/hardware-cost-v1.json").read_text())
        context = HardwareContext.from_dict(fixture["context"])
        profiles = {}
        for name, body in fixture["profiles"].items():
            value = HardwareProfile.from_dict(body)
            self.assertEqual(HardwareProfile.from_json(value.to_json()), value)
            self.assertEqual(HardwareProfile.from_dict(deepcopy(body)), value)
            context.validate_profile(value)
            profiles[name] = value
        self.assertEqual(len({value.profile_id for value in profiles.values()}), 8)
        workloads = {row["id"]: row for row in fixture["workloads"]}
        # Source-level mapping/candidate membership belongs to the future report producer.
        from q3hash import logical_from_source
        for row in fixture["target_cases"]:
            physical = logical_from_source(workloads[row["workload"]]["physical"])
            placement = HardwarePlacement("a" * 64, tuple(row["site_indices"]))
            placement.validate_for(profiles[row["profile"]], physical.dimensions)


if __name__ == "__main__":
    unittest.main()
