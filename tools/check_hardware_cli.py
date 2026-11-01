"""Audit fixed hardware CLI vectors through real module and installed commands."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from q3hash import HardwareReport, SearchConstraints, __version__


ROOT = Path(__file__).resolve().parents[1]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def cost_vector(row):
    if row.costs is None:
        return [row.status, row.reason_code, row.gate_checks, None, None, None, None]
    costs = row.costs
    timing = lambda value: None if value is None else [value.lower_ps, value.upper_ps]
    return [row.status, row.reason_code, row.gate_checks,
            [costs.active_sites, costs.native_operations, costs.two_site_operations], costs.timing_reason,
            timing(costs.critical_path_ps), timing(costs.serial_duration_ps)]


def audit(console=None, *, isolated=False):
    vectors = json.loads((ROOT / "benchmarks/hardware-cli-v1.json").read_text(encoding="utf-8"))
    source_inputs = json.loads((ROOT / "benchmarks/search-cli-v1.json").read_text(encoding="utf-8"))
    target_inputs = json.loads((ROOT / "benchmarks/hardware-cost-v1.json").read_text(encoding="utf-8"))
    require(vectors["schema"] == "q3hash.hardware-cli-acceptance-vectors" and vectors["schema_version"] == 1,
            "Unsupported hardware CLI fixture")
    module = [sys.executable, *(["-I"] if isolated else []), "-m", "q3hash.hardware_cli"]
    commands = [module] + ([] if console is None else [[str(console)]])
    stats = dict(cases_per_entry_point=len(vectors["cases"]), entry_points=len(commands), json_reports=0, invalid_inputs=0)
    with tempfile.TemporaryDirectory(prefix="q3hash hardware audit ") as directory:
        root = Path(directory)
        programs, encodings = {}, {}
        for name, value in source_inputs["programs"].items():
            programs[name] = root / (name + ".q3")
            programs[name].write_text(value, encoding="utf-8")
        for name, value in source_inputs["encodings"].items():
            encodings[name] = root / (name + ".json")
            encodings[name].write_text(canonical(value), encoding="utf-8")
        ids = {name: digest(value) for name, value in source_inputs["encodings"].items()}
        first_bytes = None
        for command in commands:
            for index, case in enumerate(vectors["cases"]):
                profile = deepcopy(target_inputs["profiles"][case["profile"]])
                context = {**target_inputs["context"], **case["context"]}
                constraints = {**SearchConstraints(max_registers=2, max_physical_size=4).to_dict(), **case["constraints"]}
                for name, value in (("profile", profile), ("context", context), ("constraints", constraints)):
                    (root / (name + ".json")).write_text(canonical(value), encoding="utf-8")
                args = [str(programs[case["logical"]]), "--profile", str(root / "profile.json"),
                        "--context", str(root / "context.json"), "--constraints", str(root / "constraints.json"),
                        "--max-dimension", str(case["max_dimension"])]
                for seed in case["seeds"]:
                    args += ["--seed", str(encodings[seed])]
                for encoding, program in case["implementations"]:
                    args += ["--implementation", str(encodings[encoding]), str(programs[program])]
                for encoding, sites in case["placements"]:
                    args += ["--placement", str(encodings[encoding]), canonical(sites)]
                result = subprocess.run(command + args + ["--json"], cwd=ROOT, text=True, capture_output=True, timeout=30)
                name = case["name"]
                require(result.returncode == case["exit"] and not result.stderr, f"{name}: exit/output: {result.returncode}: {result.stderr}")
                report = HardwareReport.from_json(result.stdout)
                source = report.source_report
                require(result.stdout == report.to_json(), f"{name}: noncanonical or contaminated output")
                expected_ids = tuple(ids[key] for key in case["candidates"])
                require(tuple(row.candidate_id for row in report.evaluations) == expected_ids, f"{name}: candidate identity/order")
                require([row.status for row in source.evaluations] == case["source_statuses"], f"{name}: source status")
                require([row.reason_code for row in source.evaluations] == case["source_reasons"], f"{name}: source reason")
                require((source.verification_calls, source.gate_column_steps) ==
                        (case["verification_calls"], case["gate_column_steps"]), f"{name}: source work")
                require([cost_vector(row) for row in report.evaluations] == case["rows"], f"{name}: hardware counts/timing/status")
                require(report.gate_checks == case["gate_checks"], f"{name}: hardware work")
                require((report.front_is_partial, report.front_reason, report.freshness, source.generation.completion) ==
                        (case["partial"], case["front_reason"], case["freshness"], case["completion"]), f"{name}: coverage/freshness")
                profile_id = digest(profile)
                require((report.profile_id, report.context_id) == (profile_id, digest(context)), f"{name}: target identities")
                placed = {encoding: sites for encoding, sites in case["placements"]}
                expected_placements = []
                for encoding in case["candidates"]:
                    if encoding not in placed:
                        expected_placements.append(None)
                        continue
                    # Reconstruct the documented identity key independently from raw wire inputs.
                    implementation = next(item for item in source.to_dict()["implementations"] if item["candidate_id"] == ids[encoding])
                    key = dict(schema="q3hash.hardware-placement-key", schema_version=1, profile_id=profile_id,
                               candidate_id=ids[encoding], physical_id=implementation["physical_id"], site_indices=placed[encoding])
                    expected_placements.append(digest(key))
                require([row.placement_id for row in report.evaluations] == expected_placements, f"{name}: placement identities")
                require(report.front_ids == tuple(expected_placements[i] for i in case["front_indices"]), f"{name}: conditional front")
                require(report.engine_version == __version__ and report.evidence_origin == source.evidence_origin == "recorded",
                        f"{name}: recorded provenance/version")
                require(all(row.costs is None or row.costs.circuit_error is None for row in report.evaluations), f"{name}: invented circuit fidelity")
                stats["json_reports"] += 1
                if index == 0:
                    if first_bytes is None:
                        first_bytes = result.stdout
                    require(result.stdout == first_bytes, "Module/console bytes disagree")
                    repeated = subprocess.run(command + args + ["--json"], cwd=ROOT, text=True, capture_output=True, timeout=30)
                    require((repeated.returncode, repeated.stdout, repeated.stderr) == (0, first_bytes, ""), "Repeated bytes changed")
                    stats["json_reports"] += 1
                    human = subprocess.run(command + args, cwd=ROOT, text=True, capture_output=True, timeout=30)
                    require(human.returncode == 0 and not human.stderr and all(text in human.stdout for text in
                            ("Freshness: synthetic", "Partial front: no", "Gate-column steps: 21/", "Hardware gate checks: 4/",
                             "no-noise-composition-model", "verified-supplied-placements-under-one-profile")), "Human report scope")
            for option in ("--help", "--version"):
                result = subprocess.run(command + [option], cwd=ROOT, text=True, capture_output=True, timeout=30)
                require(result.returncode == 0 and not result.stderr, "Help/version failed")
                if option == "--version":
                    require(result.stdout.strip() == f"q3hash {__version__}", "Version mismatch")
            required = [str(programs["shift"]), "--profile", str(root / "profile.json"), "--context", str(root / "context.json")]
            bad_utf8 = root / "invalid.q3"
            bad_utf8.write_bytes(b"\xff")
            invalid = ([], [str(root / "missing.q3"), *required[1:]], [str(bad_utf8), *required[1:]],
                       required + ["--tolerance", "nan"], required + ["--placement", str(encodings["native"]), "[true]"])
            for args in invalid:
                result = subprocess.run(command + args + ["--json"], cwd=ROOT, text=True, capture_output=True, timeout=30)
                require(result.returncode == 2 and not result.stdout and "error:" in result.stderr and "Traceback" not in result.stderr,
                        "Invalid input left output or a traceback")
                stats["invalid_inputs"] += 1
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--console", type=Path, help="also audit installed q3hash-hardware")
    parser.add_argument("--isolated", action="store_true", help="use python -I for installed module checks")
    args = parser.parse_args()
    print("Hardware CLI acceptance audit:", json.dumps(audit(args.console, isolated=args.isolated), sort_keys=True))
    print("Fixed source/hardware statuses, ledgers, timing and fronts; all target values are synthetic.")


if __name__ == "__main__":
    main()
