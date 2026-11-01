"""Hardware command boundaries, fresh evidence, preflight and output atomicity."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from q3hash import (BasisEncoding, CircuitImplementation, HardwareContext, HardwarePlacement, HardwareProfile,
                    HardwareReport, SearchConstraints, __version__, assess_hardware, evaluate_candidates,
                    generate_encodings, logical_from_source)
from q3hash import hardware_cli
from q3hash._serialization import MAX_JSON_BYTES


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "benchmarks/hardware-cost-v1.json").read_text(encoding="utf-8"))


class HardwareCLITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="q3hash hardware cli ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.logical = self.write("logical.q3", "qutrit q\nshift q")
        self.binary = self.write("binary.q3", "qubit a\nqubit b\nsum a b\nsum b a\nshift b")
        self.native_value = BasisEncoding((3,), (3,), (0, 1, 2))
        self.binary_value = BasisEncoding((3,), (2, 2), (0, 1, 2))
        self.native = self.write("native.json", self.native_value.to_json())
        self.encoding = self.write("binary.json", self.binary_value.to_json())
        self.profile_value = HardwareProfile.from_dict(FIXTURE["profiles"]["hybrid"])
        self.context_value = HardwareContext.from_dict(FIXTURE["context"])
        self.constraints_value = SearchConstraints(max_registers=2, max_physical_size=4)
        self.profile = self.write("profile.json", self.profile_value.to_json())
        self.context = self.write("context.json", self.context_value.to_json())
        self.constraints = self.write("constraints.json", self.constraints_value.to_json())

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def arguments(self, *, bindings=True, placements=True):
        args = [str(self.logical), "--profile", str(self.profile), "--context", str(self.context),
                "--constraints", str(self.constraints)]
        if bindings:
            args += ["--implementation", str(self.encoding), str(self.binary),
                     "--implementation", str(self.native), str(self.logical)]
        if placements:
            args += ["--placement", str(self.encoding), "[1,2]", "--placement", str(self.native), "[0]"]
        return args

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), self.assertRaises(SystemExit) as result:
            hardware_cli.main(list(map(str, args)))
        return result.exception.code, stdout.getvalue(), stderr.getvalue()

    def report(self, args, code=0):
        actual, stdout, stderr = self.invoke(*args, "--json")
        self.assertEqual((actual, stderr), (code, ""))
        report = HardwareReport.from_json(stdout)
        self.assertEqual(stdout, report.to_json())
        return report

    def invalid_before_numerics(self, args):
        with patch("q3hash.search_verification.verify_equivalence", side_effect=AssertionError("numerical work")):
            code, stdout, stderr = self.invoke(*args, "--json")
        self.assertEqual((code, stdout), (2, ""))
        self.assertIn("error:", stderr)
        self.assertNotIn("Traceback", stderr)
        return stderr

    def test_module_matches_fresh_public_api_and_canonical_bytes(self):
        result = subprocess.run([sys.executable, "-m", "q3hash.hardware_cli", *self.arguments(), "--json"],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        logical = logical_from_source(self.logical.read_text())
        generation = generate_encodings(logical.dimensions, self.constraints_value)
        source = evaluate_candidates(logical, generation, (CircuitImplementation(self.native_value, logical.ir),
            CircuitImplementation(self.binary_value, logical_from_source(self.binary.read_text()).ir)))
        placements = tuple(HardwarePlacement(row.candidate_id, (0,) if i == 0 else (1, 2))
                           for i, row in enumerate(source.evaluations))
        expected = assess_hardware(source, self.profile_value, placements, self.context_value)
        self.assertEqual((result.returncode, result.stderr, result.stdout), (0, "", expected.to_json()))

    def test_computed_evidence_is_passed_directly_to_assessment(self):
        seen = []
        def capture(source, *args):
            seen.append(source.evidence_origin)
            return assess_hardware(source, *args)
        with patch("q3hash.hardware_cli.assess_hardware", side_effect=capture):
            self.report(self.arguments())
        self.assertEqual(seen, ["computed"])

    def test_human_report_discloses_profile_scope_ledgers_and_numerics(self):
        code, stdout, stderr = self.invoke(*self.arguments())
        self.assertEqual((code, stderr), (0, ""))
        for phrase in ("Generation: exhausted", "pass=2", "supported=2", "Verifier calls: 2/64",
                       "Gate-column steps: 21/", "Hardware gate checks: 4/262144", "Freshness: synthetic",
                       "As of: 2026-11-01T01:00:00Z", "maximum calibration age: 3600 s", "Snapshot:",
                       "Retrieved:", "calibrated: None", "Partial front: no", "Objectives:",
                       "verified-supplied-placements-under-one-profile", "exclusive-sites-critical-path-v1",
                       "residual=", "leakage=", "physical-unitarity=", "critical_path_ps=[40000,60000] ps",
                       "average-gate-infidelity", "no-noise-composition-model", "not measured execution times"):
            self.assertIn(phrase, stdout)

    def test_required_profile_and_context_have_no_implicit_defaults(self):
        for args in ([], [self.logical], [self.logical, "--profile", self.profile],
                     [self.logical, "--context", self.context]):
            self.invalid_before_numerics(args)

    def test_default_search_constraints_retain_missing_coverage(self):
        report = self.report([self.logical, "--profile", self.profile, "--context", self.context], 3)
        self.assertEqual(report.source_report.generation.constraints, SearchConstraints())
        self.assertTrue(report.front_is_partial)
        self.assertEqual(report.source_report.verification_calls, 0)

    def test_all_late_files_are_parsed_before_generation(self):
        missing = self.root / "missing.json"
        for flag, operands in (("--seed", [missing]), ("--implementation", [self.native, missing]),
                               ("--placement", [missing, "[0]"])):
            with patch("q3hash.hardware_cli.generate_encodings", side_effect=AssertionError("generation")):
                self.invalid_before_numerics(self.arguments() + [flag, *operands])

    def test_late_invalid_placement_precedes_any_verifier_call(self):
        for sites in ("[0]", "[1,1]", "[1,4]", "[-1,2]", "[1,64]", "[]", "[true,2]", "[1.0,2]",
                      "null", "{}", "1,2", "[NaN,2]", '"\\ud800"'):
            with self.subTest(sites=sites):
                self.invalid_before_numerics(self.arguments(placements=False) +
                    ["--placement", self.native, "[0]", "--placement", self.encoding, sites])

    def test_duplicate_placement_is_an_error_even_when_identical(self):
        stderr = self.invalid_before_numerics(self.arguments() + ["--placement", self.native, "[0]"])
        self.assertIn("Q3-HARD-003", stderr)

    def test_unimplemented_and_foreign_placements_do_not_add_bindings_or_seeds(self):
        foreign = self.write("cycle.json", BasisEncoding((3,), (3,), (1, 2, 0)).to_json())
        for args in (self.arguments(bindings=False), self.arguments() + ["--placement", foreign, "[3]"],
                     self.arguments() + ["--implementation", foreign, self.logical]):
            self.invalid_before_numerics(args)

    def test_explicit_seed_and_input_placement_order_are_preserved_or_normalised(self):
        report = self.report(self.arguments() + ["--seed", self.encoding, "--seed", self.encoding])
        self.assertEqual(report.source_report.generation.seed_encodings, (self.binary_value,) * 2)
        self.assertEqual([p.site_indices for p in report.placements], [(1, 2), (0,)])
        self.assertEqual(report.evaluations[1].placement_id, report.front_ids[0])

    def test_duplicate_implementation_fails_before_work(self):
        self.invalid_before_numerics(self.arguments() + ["--implementation", self.native, self.logical])

    def test_invalid_source_options_precede_work(self):
        for flag, values in (("--tolerance", ("nan", "inf", "0", "-1")), ("--max-dimension", ("0", "65", "1.5"))):
            for value in values:
                self.invalid_before_numerics(self.arguments() + [flag, value])

    def test_context_before_retrieval_precedes_work(self):
        self.context.write_text(replace(self.context_value, as_of="2026-10-31T23:59:59Z").to_json())
        self.assertIn("Q3-HARD-001", self.invalid_before_numerics(self.arguments()))

    def test_profile_and_context_strict_schema_errors_precede_work(self):
        for path in (self.profile, self.context, self.constraints):
            original = path.read_text()
            value = json.loads(original)
            value["unrecognised"] = 1
            path.write_text(json.dumps(value))
            self.invalid_before_numerics(self.arguments())
            path.write_text(original)

    def test_each_input_file_is_byte_bounded_and_utf8_checked(self):
        for path in (self.logical, self.profile, self.context, self.constraints, self.native, self.binary):
            original = path.read_bytes()
            for data in (b"\xff", b" " * (MAX_JSON_BYTES + 1), ("\u00e9" * (MAX_JSON_BYTES // 2 + 1)).encode()):
                path.write_bytes(data)
                self.invalid_before_numerics(self.arguments())
            path.write_bytes(original)

    def test_literal_json_has_the_same_transport_budget(self):
        stderr = self.invalid_before_numerics(self.arguments(placements=False) +
            ["--placement", self.native, " " * MAX_JSON_BYTES + "[0]"])
        self.assertIn("Q3-SER-001", stderr)

    def test_all_flag_caps_are_checked_before_reads(self):
        for flag, operands in (("--seed", [self.native]), ("--implementation", [self.native, self.logical]),
                               ("--placement", [self.native, "[0]"])):
            args = self.arguments(bindings=False, placements=False) + [str(item) for _ in range(4097) for item in (flag, *operands)]
            with patch("q3hash.hardware_cli._read_input", side_effect=AssertionError("file read")):
                self.assertIn("Q3-CLI-001", self.invalid_before_numerics(args))

    def test_placement_digest_collision_fails_before_numerics(self):
        with patch.object(HardwarePlacement, "identifier", return_value="0" * 64):
            self.assertIn("Q3-HARD-004", self.invalid_before_numerics(self.arguments()))

    def test_profile_fingerprint_representation_fails_before_numerics(self):
        with patch.object(HardwareProfile, "to_json", side_effect=ValueError("Q3-SER-001: wire budget")):
            self.assertIn("Q3-SER-001", self.invalid_before_numerics(self.arguments()))

    def test_output_serialisation_failure_leaves_both_modes_empty(self):
        for flags in ([], ["--json"]):
            with patch.object(HardwareReport, "to_json", side_effect=ValueError("Q3-SER-001: output budget")):
                code, stdout, stderr = self.invoke(*self.arguments(), *flags)
            self.assertEqual((code, stdout), (2, ""))
            self.assertIn("Q3-SER-001", stderr)

    def test_dimension_mismatch_is_complete_target_infeasibility(self):
        args = self.arguments(placements=False) + ["--placement", self.native, "[1]", "--placement", self.encoding, "[0,3]"]
        report = self.report(args, 4)
        self.assertEqual(report.front_reason, "no-supported-placements")
        self.assertFalse(report.front_is_partial)
        self.assertEqual(report.gate_checks, 0)
        code, stdout, stderr = self.invoke(*args)
        self.assertEqual((code, stderr), (4, ""))
        self.assertIn("Run status: target-infeasible", stdout)

    def test_stale_data_stays_explicit_in_human_output(self):
        self.profile.write_text(HardwareProfile.from_dict(FIXTURE["profiles"]["reported-stale"]).to_json())
        code, stdout, stderr = self.invoke(*self.arguments())
        self.assertEqual((code, stderr), (3, ""))
        self.assertIn("Freshness: stale", stdout)
        self.assertIn("critical_path_ps=unknown", stdout)
        self.assertIn("stale-calibration", stdout)

    def test_source_failure_precedes_partial_coverage(self):
        identity = self.write("identity.q3", "qutrit q")
        args = self.arguments(bindings=False, placements=False) + ["--implementation", self.native, identity,
                                                                "--placement", self.native, "[0]"]
        report = self.report(args, 1)
        self.assertTrue(report.front_is_partial)
        self.assertEqual(report.status_counts["ineligible"], 2)
        self.assertEqual(report.gate_checks, 0)

    def test_bad_arguments_are_clean_diagnostics(self):
        for extra in (["--best"], ["--placement", self.native], ["--source-report", "report.json"]):
            self.invalid_before_numerics(self.arguments() + extra)

    def test_help_and_version_need_no_files(self):
        for flag in ("--help", "--version"):
            code, stdout, stderr = self.invoke(flag)
            self.assertEqual((code, stderr), (0, ""))
            self.assertIn("--placement" if flag == "--help" else f"q3hash {__version__}", stdout)

    def test_input_files_and_paths_with_spaces_are_unchanged(self):
        before = {path: path.read_bytes() for path in self.root.iterdir()}
        self.report(self.arguments())
        self.assertEqual({path: path.read_bytes() for path in self.root.iterdir()}, before)

    def test_runtime_defects_remain_visible(self):
        with patch("q3hash.hardware_cli.assess_hardware", side_effect=RuntimeError("internal defect")):
            with self.assertRaisesRegex(RuntimeError, "internal defect"):
                self.invoke(*self.arguments())

    def test_fixed_process_vectors_cover_all_exit_classes_and_both_ledgers(self):
        spec = importlib.util.spec_from_file_location("hardware_cli_audit", ROOT / "tools/check_hardware_cli.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stats = module.audit()
        self.assertEqual(stats, dict(cases_per_entry_point=23, entry_points=1, json_reports=24, invalid_inputs=5))


if __name__ == "__main__":
    unittest.main()
