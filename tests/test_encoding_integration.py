"""Reproduce the release-candidate benchmarks with the installed Python core."""

import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EncodingIntegrationTests(unittest.TestCase):
    def test_independent_report_is_reproducible_and_preserves_unavailable_candidates(self):
        command = [sys.executable, "-I", str(ROOT / "tools/check_encoding_integration.py"), "--json"]
        first = subprocess.check_output(command, cwd=ROOT, timeout=30)
        self.assertEqual(first, subprocess.check_output(command, cwd=ROOT, timeout=30))
        report = json.loads(first)
        self.assertEqual((report["schema_version"], report["basis_order"]), (1, "last-register-fastest"))
        workloads = {row["id"]: row for row in report["workloads"]}
        self.assertEqual({name: row["status"] for name, row in workloads.items()}, {
            "qubit-shift": "pass", "qutrit-shift": "partial", "active-mixed-sum": "partial",
        })
        for name, missing in (("qutrit-shift", [3, 2]), ("active-mixed-sum", [2, 2, 2])):
            candidates = workloads[name]["candidates"]
            self.assertEqual([row["status"] for row in candidates], ["pass", "pass", "pass", "unsupported"])
            self.assertEqual(candidates[-1]["dimensions"], missing)
            self.assertIsNone(candidates[-1]["metrics"])
            self.assertIsNone(candidates[-1]["resources"])
        reordered = next(row for row in workloads["active-mixed-sum"]["candidates"] if row["id"] == "reordered")
        self.assertEqual(reordered["basis_indices"], [0, 2, 4, 1, 3, 5])
        controls = {row["id"]: row for row in report["negative_controls"]}
        self.assertEqual({row["status"] for row in controls.values()}, {"fail"})
        self.assertEqual(controls["qutrit-leakage"]["metrics"]["leakage_norm"], 1)
        self.assertGreater(controls["wrong-mixed-basis-order"]["metrics"]["subspace_residual"], report["tolerance"])
