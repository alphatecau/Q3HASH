"""Audit fixed v0.4 CLI acceptance vectors through real process entry points."""

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from q3hash import RESOURCE_OBJECTIVES, SearchConstraints, SearchReport, __version__


ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def audit(console=None, *, isolated=False):
    vectors = json.loads((ROOT / "benchmarks/search-cli-v1.json").read_text(encoding="utf-8"))
    require(vectors["schema"] == "q3hash.search-cli-acceptance-vectors" and vectors["schema_version"] == 1,
            "Unsupported CLI audit fixture")
    module = [sys.executable, *(["-I"] if isolated else []), "-m", "q3hash.search_cli"]
    commands = [module] + ([] if console is None else [[str(console)]])
    stats = dict(cases_per_entry_point=len(vectors["cases"]), entry_points=len(commands), json_reports=0, invalid_inputs=0)
    with tempfile.TemporaryDirectory(prefix="q3hash-cli-audit-") as directory:
        root = Path(directory)
        programs, encodings = {}, {}
        for name, source in vectors["programs"].items():
            programs[name] = root / (name + ".q3")
            programs[name].write_text(source, encoding="utf-8")
        for name, value in vectors["encodings"].items():
            encodings[name] = root / (name + ".encoding.json")
            encodings[name].write_text(canonical(value), encoding="utf-8")
        ids = {name: hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()
               for name, value in vectors["encodings"].items()}
        first_bytes = None
        for command in commands:
            for index, case in enumerate(vectors["cases"]):
                overrides = {key: tuple(value) if type(value) is list else value for key, value in case["constraints"].items()}
                constraints = replace(SearchConstraints(max_registers=2, max_physical_size=4), **overrides)
                path = root / "constraints.json"
                path.write_text(constraints.to_json(), encoding="utf-8")
                args = [str(programs[case["logical"]]), "--constraints", str(path),
                        "--max-dimension", str(case["max_dimension"])]
                for seed in case["seeds"]:
                    args += ["--seed", str(encodings[seed])]
                for encoding, program in case["implementations"]:
                    args += ["--implementation", str(encodings[encoding]), str(programs[program])]
                result = subprocess.run(command + args + ["--json"], cwd=ROOT, text=True,
                                        capture_output=True, timeout=30)
                name = case["name"]
                require(result.returncode == case["exit"] and not result.stderr, f"{name}: exit/output error: {result.stderr}")
                report = SearchReport.from_json(result.stdout)
                require(report.to_json() == result.stdout, f"{name}: noncanonical or contaminated JSON output")
                expected_ids = tuple(ids[key] for key in case["candidates"])
                require(tuple(row.candidate_id for row in report.evaluations) == expected_ids, f"{name}: candidate identity/order")
                require([row.status for row in report.evaluations] == case["statuses"], f"{name}: statuses")
                require([row.reason_code for row in report.evaluations] == case["reasons"], f"{name}: reasons")
                require((report.verification_calls, report.gate_column_steps) ==
                        (case["verification_calls"], case["gate_column_steps"]), f"{name}: ledger")
                require(report.front_ids == tuple(expected_ids[i] for i in case["front_indices"]), f"{name}: front")
                require(report.generation.completion == case["completion"], f"{name}: completion")
                for row, expected in zip(report.evaluations, case["resources"]):
                    actual = None if row.resources is None else [getattr(row.resources, key) for key in RESOURCE_OBJECTIVES]
                    require(actual == expected, f"{name}: exact resource vector")
                require(report.engine_version == __version__ and report.evidence_origin == "recorded", f"{name}: provenance")
                stats["json_reports"] += 1
                if index == 0:
                    if first_bytes is None:
                        first_bytes = result.stdout
                    require(result.stdout == first_bytes, "Module/console canonical report disagreement")
                    repeated = subprocess.run(command + args + ["--json"], cwd=ROOT, text=True, capture_output=True, timeout=30)
                    require((repeated.returncode, repeated.stdout, repeated.stderr) == (0, first_bytes, ""),
                            "Repeated canonical report bytes changed")
                    stats["json_reports"] += 1
                    human = subprocess.run(command + args, cwd=ROOT, text=True, capture_output=True, timeout=30)
                    require(human.returncode == 0 and "Partial front: no" in human.stdout and
                            "passing-supplied-circuits-only" in human.stdout and not human.stderr, "Human coverage output")
            for option in ("--help", "--version"):
                result = subprocess.run(command + [option], cwd=ROOT, text=True, capture_output=True, timeout=30)
                require(result.returncode == 0 and not result.stderr, "CLI help/version failed")
                if option == "--version":
                    require(result.stdout.strip() == f"q3hash {__version__}", "Entry-point version mismatch")
            bad = root / "invalid.q3"
            bad.write_text("qubit q\nsum q q", encoding="utf-8")
            invalid_cases = ([str(root / "missing.q3")], [str(bad)], [str(programs["shift"]), "--tolerance", "nan"])
            for args in invalid_cases:
                result = subprocess.run(command + list(args) + ["--json"], cwd=ROOT, text=True, capture_output=True, timeout=30)
                require(result.returncode == 2 and not result.stdout and "error:" in result.stderr and
                        "Traceback" not in result.stderr, "Invalid input was not a clean diagnostic")
                stats["invalid_inputs"] += 1
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--console", type=Path, help="also audit the installed q3hash-search executable")
    parser.add_argument("--isolated", action="store_true", help="use python -I for installed module checks")
    args = parser.parse_args()
    print("Search CLI acceptance audit:", json.dumps(audit(args.console, isolated=args.isolated), sort_keys=True))
    print("Fixed expected statuses, call/work totals, resources and fronts; no synthesis or hardware-performance claim.")


if __name__ == "__main__":
    main()
