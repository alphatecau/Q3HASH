"""CLI transport, exit precedence and honest complete/partial search output."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from q3hash import (BasisEncoding, CircuitImplementation, SearchConstraints, SearchReport,
                    VerificationReport, __version__, evaluate_candidates, generate_encodings, logical_from_source)
from q3hash import search_cli


ROOT = Path(__file__).resolve().parents[1]


class SearchCLITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="q3hash search ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.logical = self.write("logical.q3", "qutrit q\nshift q")
        self.binary = self.write("binary.q3", "qubit a\nqubit b\nsum a b\nsum b a\nshift b")
        self.identity = self.write("identity.q3", "qutrit q")
        self.native_encoding = BasisEncoding((3,), (3,), (0, 1, 2))
        self.binary_encoding = BasisEncoding((3,), (2, 2), (0, 1, 2))
        self.native = self.write("native.json", self.native_encoding.to_json())
        self.encoding = self.write("binary.json", self.binary_encoding.to_json())
        self.constraints_value = SearchConstraints(max_registers=2, max_physical_size=4)
        self.constraints = self.write("constraints.json", self.constraints_value.to_json())

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def arguments(self, *, both=True):
        args = [str(self.logical), "--constraints", str(self.constraints)]
        if both:
            # Bindings arrive in reverse order and must be matched by encoding.
            args += ["--implementation", str(self.encoding), str(self.binary),
                     "--implementation", str(self.native), str(self.logical)]
        return args

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as result:
                search_cli.main(list(map(str, args)))
        return result.exception.code, stdout.getvalue(), stderr.getvalue()

    def report(self, args, expected_exit):
        code, stdout, stderr = self.invoke(*args, "--json")
        self.assertEqual(code, expected_exit, stderr)
        self.assertEqual(stderr, "")
        report = SearchReport.from_json(stdout)
        self.assertEqual(stdout, report.to_json())
        return report

    def test_module_entry_point_emits_the_same_complete_report_as_public_api(self):
        result = subprocess.run([sys.executable, "-m", "q3hash.search_cli", *self.arguments(), "--json"],
                                cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        logical = logical_from_source(self.logical.read_text())
        generation = generate_encodings((3,), self.constraints_value)
        expected = evaluate_candidates(logical, generation, (
            CircuitImplementation(self.native_encoding, logical.ir),
            CircuitImplementation(self.binary_encoding, logical_from_source(self.binary.read_text()).ir)))
        self.assertEqual(result.stdout, expected.to_json())
        self.assertEqual(result.stderr, "")

    def test_human_output_explains_coverage_counts_budgets_and_objectives(self):
        code, stdout, stderr = self.invoke(*self.arguments())
        self.assertEqual((code, stderr), (0, ""))
        for phrase in ("Generation: exhausted", "pass=2", "Verifier calls: 2/64", "Gate-column steps: 21/",
                       "Partial front: no", "passing-supplied-circuits-only", "unused_basis_states=1",
                       "q3hash-circuit", "physical_registers=1", "Front candidates: 2", "residual=", "leakage="):
            self.assertIn(phrase, stdout)

    def test_default_constraints_leave_missing_circuits_explicit(self):
        report = self.report([self.logical], 3)
        self.assertEqual(report.generation.constraints, SearchConstraints())
        self.assertGreater(len(report.evaluations), 2)
        self.assertEqual(report.status_counts["unimplemented"], len(report.evaluations))
        self.assertEqual((report.front_ids, report.verification_calls), ((), 0))

    def test_custom_seed_order_and_duplicate_provenance_are_preserved(self):
        report = self.report(self.arguments() + ["--seed", self.encoding, "--seed", self.encoding], 0)
        self.assertEqual(report.generation.seed_encodings, (self.binary_encoding,) * 2)
        self.assertEqual(report.evaluations[0].candidate.encoding, self.binary_encoding)
        self.assertEqual(report.generation.candidates[0].seed_index, 0)
        self.assertGreater(report.generation.duplicate_mappings, 0)

    def test_implementation_does_not_implicitly_add_a_seed(self):
        foreign = self.write("foreign.json", BasisEncoding((3,), (3,), (2, 1, 0)).to_json())
        with patch("q3hash.search_verification.verify_equivalence", side_effect=AssertionError("numeric call")):
            code, stdout, stderr = self.invoke(*self.arguments(both=False), "--implementation", foreign, self.logical)
        self.assertEqual((code, stdout), (2, ""))
        self.assertIn("Q3-SEARCH-003", stderr)

    def test_duplicate_implementation_is_rejected_before_any_call(self):
        with patch("q3hash.search_verification.verify_equivalence", side_effect=AssertionError("numeric call")):
            code, stdout, stderr = self.invoke(*self.arguments(), "--implementation", self.native, self.logical)
        self.assertEqual((code, stdout), (2, ""))
        self.assertIn("Q3-SEARCH-003", stderr)

    def test_all_files_are_read_before_generation_and_numerical_work(self):
        with patch("q3hash.search_cli.generate_encodings", side_effect=AssertionError("generation called")):
            code, stdout, stderr = self.invoke(*self.arguments(), "--seed", self.root / "missing.json")
        self.assertEqual((code, stdout), (2, ""))
        self.assertNotIn("Traceback", stderr)

    def test_work_skip_allows_later_smaller_circuit_and_reports_partial(self):
        self.constraints.write_text(replace(self.constraints_value, max_gate_column_steps=6).to_json())
        report = self.report(self.arguments() + ["--seed", self.encoding], 3)
        self.assertEqual([row.reason_code for row in report.evaluations], ["gate-column-budget", "verified"])
        self.assertEqual((report.verification_calls, report.gate_column_steps), (1, 6))

    def test_call_skip_and_identity_zero_work_have_distinct_accounting(self):
        self.constraints.write_text(replace(self.constraints_value, max_verifications=1).to_json())
        report = self.report(self.arguments(), 3)
        self.assertEqual(report.evaluations[1].reason_code, "verification-call-budget")
        self.assertEqual(report.gate_column_steps, 6)
        self.logical.write_text("qutrit q")
        self.binary.write_text("qubit a\nqubit b")
        report = self.report(self.arguments(), 3)
        self.assertEqual((report.verification_calls, report.gate_column_steps), (1, 0))

    def test_operation_limit_precedes_dense_limit_with_no_calls(self):
        self.constraints.write_text(replace(self.constraints_value, max_operations_per_program=1).to_json())
        report = self.report(self.arguments() + ["--max-dimension", "2"], 3)
        self.assertEqual([row.reason_code for row in report.evaluations], ["dense-limit", "operation-limit"])
        self.assertEqual(report.verification_calls, 0)

    def test_generation_truncation_stays_partial_even_when_retained_candidate_passes(self):
        self.constraints.write_text(replace(self.constraints_value, max_candidates=1).to_json())
        report = self.report(self.arguments(both=False) + ["--implementation", self.native, self.logical], 3)
        self.assertEqual(report.generation.stop_reason, "candidate-budget")
        self.assertEqual(report.status_counts["pass"], 1)

    def test_zero_candidates_is_inconclusive_and_has_explicit_reason(self):
        self.logical.write_text("qudit 5 q")
        report = self.report(self.arguments(both=False), 3)
        self.assertEqual(report.front_reason, "no-candidates")
        self.assertEqual(report.evaluations, ())

    def test_numerical_failure_takes_precedence_over_missing_circuits(self):
        report = self.report(self.arguments(both=False) + ["--implementation", self.native, self.identity], 1)
        self.assertEqual([row.status for row in report.evaluations], ["fail", "unimplemented"])
        self.assertEqual(report.gate_column_steps, 3)

    def test_nonfinite_computed_failure_exits_one_with_valid_null_snapshot(self):
        failed = VerificationReport("fail", "nonfinite computed metrics", "q3hash-circuit", 3, 3, 1e-10)
        with patch("q3hash.search_verification.verify_equivalence", return_value=failed):
            report = self.report(self.arguments(both=False) + ["--implementation", self.native, self.logical], 1)
        self.assertEqual(report.evaluations[0].reason_code, "nonfinite-metrics")

    def test_malformed_source_is_a_clean_error_with_source_line(self):
        self.binary.write_text("qubit a\nsum a a")
        code, stdout, stderr = self.invoke(*self.arguments())
        self.assertEqual((code, stdout), (2, ""))
        self.assertIn("line 2:", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_constraints_and_encodings_remain_strict_json(self):
        for path, text in ((self.constraints, '{"schema_version":1,' + self.constraints.read_text()[1:]),
                           (self.native, self.native.read_text().replace('"schema_version":1', '"schema_version":true'))):
            old = path.read_text()
            path.write_text(text)
            code, stdout, stderr = self.invoke(*self.arguments())
            self.assertEqual((code, stdout), (2, ""))
            self.assertIn("Q3-SER-", stderr)
            path.write_text(old)

    def test_invalid_options_do_not_emit_a_partial_json_document(self):
        for option, value in (("--tolerance", "nan"), ("--tolerance", "inf"), ("--tolerance", "0"),
                              ("--max-dimension", "0"), ("--max-dimension", "65"),
                              ("--max-dimension", "2.5")):
            code, stdout, stderr = self.invoke(*self.arguments(), option, value, "--json")
            self.assertEqual((code, stdout), (2, ""))
            self.assertIn("error:", stderr)

    def test_missing_or_non_utf8_file_is_a_clean_input_error(self):
        for data in (None, b"\xff"):
            if data is None:
                self.logical.unlink()
            else:
                self.logical.write_bytes(data)
            code, stdout, stderr = self.invoke(*self.arguments())
            self.assertEqual((code, stdout), (2, ""))
            self.assertNotIn("Traceback", stderr)

    def test_transport_limit_is_bounded_in_bytes_before_parsing(self):
        stream = io.BytesIO(b"a" * (1_048_576 + 1))
        with patch.object(Path, "open", return_value=stream):
            with self.assertRaisesRegex(ValueError, "^Q3-CLI-001"):
                search_cli._read_input(self.logical)
        # Multibyte text exceeds the byte cap well before a million characters.
        self.logical.write_text("#" + "é" * 600000, encoding="utf-8")
        code, stdout, stderr = self.invoke(*self.arguments(both=False))
        self.assertEqual((code, stdout), (2, ""))
        self.assertIn("Q3-CLI-001", stderr)

    def test_wire_output_failure_leaves_stdout_empty(self):
        with patch.object(SearchReport, "to_json", side_effect=ValueError("Q3-SER-001: wire limit")):
            code, stdout, stderr = self.invoke(*self.arguments(), "--json")
        self.assertEqual((code, stdout), (2, ""))
        self.assertIn("Q3-SER-001", stderr)

    def test_help_version_and_invalid_argument_shapes(self):
        for option, expected in (("--help", "--implementation"), ("--version", __version__)):
            code, stdout, stderr = self.invoke(option)
            self.assertEqual((code, stderr), (0, ""))
            self.assertIn(expected, stdout)
        for args in ((self.logical, "--implementation", self.native), (self.logical, "--best"), ()):
            code, stdout, stderr = self.invoke(*args)
            self.assertEqual((code, stdout), (2, ""))
            self.assertIn("error:", stderr)

    def test_flag_counts_are_checked_before_file_reads(self):
        for flag, arguments in (("--seed", [self.native]), ("--implementation", [self.native, self.logical])):
            args = [self.logical] + [str(item) for _ in range(4097) for item in (flag, *arguments)]
            with patch("q3hash.search_cli._read_input", side_effect=AssertionError("file read")):
                code, stdout, stderr = self.invoke(*args)
            self.assertEqual((code, stdout), (2, ""))
            self.assertIn("Q3-CLI-001", stderr)

    def test_input_files_are_unchanged_and_paths_with_spaces_work(self):
        before = {path: path.read_bytes() for path in self.root.iterdir()}
        self.report(self.arguments(), 0)
        self.assertEqual({path: path.read_bytes() for path in self.root.iterdir()}, before)

    def test_unexpected_runtime_exception_is_not_converted_to_partial(self):
        with patch("q3hash.search_cli.evaluate_candidates", side_effect=RuntimeError("internal bug")):
            with self.assertRaisesRegex(RuntimeError, "internal bug"):
                self.invoke(*self.arguments())

    def test_release_cli_vectors_use_public_process_entry_point(self):
        spec = importlib.util.spec_from_file_location("search_release_audit", ROOT / "tools/check_search.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stats = module.audit()
        self.assertEqual(stats["cases_per_entry_point"], 17)
        self.assertEqual(stats["entry_points"], 1)
        self.assertEqual(stats["json_reports"], 18)
        self.assertEqual(stats["invalid_inputs"], 3)


if __name__ == "__main__":
    unittest.main()
