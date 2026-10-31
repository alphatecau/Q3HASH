"""End-to-end CLI behaviour for the public examples and invalid input."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run([sys.executable, "-m", "q3hash.cli", *map(str, arguments)],
                              cwd=ROOT, capture_output=True, text=True, timeout=15)

    def test_entangled_basis_labels_and_amplitudes(self):
        result = self.run_cli("examples/bell.q3", "--amplitudes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("|0,0>: 0.50000000", result.stdout)
        self.assertIn("|1,1>: 0.50000000", result.stdout)
        self.assertIn("amplitude=+0.70710678+0.00000000j", result.stdout)

    def test_original_single_register_example(self):
        result = self.run_cli("examples/qutrit.q3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("|2>: 0.33333333", result.stdout)
        self.assertNotIn("amplitude=", result.stdout)

    def test_invalid_source_reports_a_line_without_a_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.q3"
            path.write_text("qutrit q\nsum q q\n")
            result = self.run_cli(path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("line 2:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_file_is_a_clean_cli_error(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_cli(Path(directory) / "missing.q3")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
