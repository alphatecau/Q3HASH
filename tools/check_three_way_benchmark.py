"""v0.6 three-way same-workload contract, against public Q3HASH APIs.

Run from repository root after installing package: python -I tools/check_three_way_benchmark.py
All hardware costs are conditional on an existing SYNTHETIC profile.
"""

from __future__ import annotations

import cmath
import json
import math
from pathlib import Path

from q3hash import (
    BasisEncoding, CircuitImplementation, HardwareContext, HardwarePlacement,
    HardwareProfile, ReferenceOperator, SearchConstraints, assess_hardware,
    count_resources, evaluate_candidates, generate_encodings, logical_from_source,
    verify_equivalence,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "benchmarks/three-way-qutrit-shift-v1.json"


def _load(path):
    return (ROOT / path).read_text(encoding="utf-8")


def _verify_negative_controls(logical):
    # A |0>-only probe would falsely accept this relative-phase error.
    qubit = logical_from_source("qubit q")
    phase_error = logical_from_source("qubit q\nfourier q\nshift q\nfourier q")
    result = verify_equivalence(qubit, phase_error.ir, BasisEncoding((2,), (2,), (0, 1)))
    assert result.status == "fail" and result.subspace_residual > 1, result
    assert result.physical_unitarity_error <= 1e-10, result

    # Physical shift leaks from |2> into unused |3>; |0> alone cannot detect it.
    leaky = logical_from_source("qudit 4 q\nshift q")
    result = verify_equivalence(logical, leaky.ir, BasisEncoding((3,), (4,), (0, 1, 2)))
    assert result.status == "fail" and math.isclose(result.leakage_norm, 1), result

    # Matching encoded columns are insufficient if the unused complement is nonunitary.
    identity = logical_from_source("qutrit q")
    nonunitary = ReferenceOperator((2, 2), tuple(tuple(
        int(row == column and row < 3) for column in range(4)) for row in range(4)))
    result = verify_equivalence(identity, nonunitary, BasisEncoding((3,), (2, 2), (0, 1, 2)))
    assert result.status == "fail" and result.physical_unitarity_error == 1, result
    assert result.subspace_residual == 0 and result.leakage_norm == 0, result

    # A harmless *single* global phase must not cause a false rejection.
    phase = cmath.exp(0.7j)
    phased_identity = ReferenceOperator((2,), ((phase, 0), (0, phase)))
    result = verify_equivalence(qubit, phased_identity, BasisEncoding((2,), (2,), (0, 1)))
    assert result.status == "pass" and abs(result.global_phase - phase) <= 1e-10, result

    # Strict map validity: repeated and out-of-range target indices are rejected.
    for indices in ((0, 0, 2), (0, 1, 6)):
        try:
            BasisEncoding((3,), (2, 3), indices)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid mapping accepted: {indices}")


def run():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    logical = logical_from_source(_load(fixture["logical_source"]))
    constraints = SearchConstraints.from_json(_load(fixture["constraints"]))
    assert logical.dimensions == (3,) and constraints.max_physical_size == 6
    assert constraints.max_registers == 2
    assert fixture["tolerance"] == 1e-10

    cases = {}
    for spec in fixture["cases"]:
        encoding = BasisEncoding.from_json(_load(spec["encoding"]))
        physical = logical_from_source(_load(spec["physical_source"])).ir
        assert encoding.logical_dimensions == logical.dimensions
        assert list(encoding.physical_dimensions) == spec["dimensions"]
        assert encoding.physical_basis_indices == (0, 1, 2)
        assert physical.dimensions == encoding.physical_dimensions
        verification = verify_equivalence(logical, physical, encoding, tolerance=fixture["tolerance"])
        assert verification.status == "pass" and verification.evidence == "q3hash-circuit", (spec["id"], verification)
        for key in ("subspace_residual", "leakage_norm", "logical_unitarity_error", "physical_unitarity_error"):
            result = getattr(verification, key)
            assert result is not None and math.isfinite(result) and result <= fixture["tolerance"], (spec["id"], key, result)
        counts = count_resources(physical, logical_size=logical.state_size)
        assert list(counts.as_tuple()) == spec["resources"], (spec["id"], counts)
        cases[encoding] = (spec, physical)
    assert len(cases) == 3 and {v[0]["id"] for v in cases.values()} == {"native", "binary", "mixed"}
    _verify_negative_controls(logical)

    generation = generate_encodings(logical.dimensions, constraints)
    assert generation.completion == "exhausted" and generation.stop_reason is None, generation
    actual_dimensions = {c.encoding.physical_dimensions for c in generation.candidates}
    expected_dimensions = {(3,), (2, 2), (2, 3), (3, 2)}
    assert actual_dimensions == expected_dimensions, actual_dimensions
    assert len(generation.candidates) == 4, generation

    implementations = tuple(CircuitImplementation(enc, ir) for enc, (_, ir) in cases.items())
    source = evaluate_candidates(logical, generation, implementations, tolerance=fixture["tolerance"])
    assert source.evidence_origin == "computed"
    assert source.verification_calls == 3
    assert source.status_counts["pass"] == 3 and source.status_counts["unimplemented"] == 1, source.status_counts
    assert source.front_is_partial, "Remaining (3,2) dimension must not be hidden"
    for row in source.evaluations:
        if row.candidate.encoding.physical_dimensions in expected_dimensions - {(3, 2)}:
            assert row.status == "pass", (row.candidate.encoding.physical_dimensions, row.status)
        else:
            assert row.candidate.encoding.physical_dimensions == (3, 2) and row.status == "unimplemented"

    profile = HardwareProfile.from_json(_load(fixture["hardware_profile"]))
    context = HardwareContext.from_json(_load(fixture["hardware_context"]))
    assert profile.provenance.kind == "synthetic", "The profile must remain synthetic"
    placements = tuple(
        HardwarePlacement(row.candidate_id, tuple(cases[row.candidate.encoding][0]["placement"]))
        for row in source.evaluations if row.candidate.encoding in cases
    )
    hardware = assess_hardware(source, profile, placements, context)
    assert hardware.evidence_origin == "computed" and hardware.freshness == "synthetic", hardware
    assert hardware.gate_checks == 5 and hardware.front_is_partial, hardware
    assert hardware.status_counts["supported"] == 3 and hardware.status_counts["ineligible"] == 1, hardware.status_counts
    assert hardware.ranking_scope == "verified-supplied-placements-under-one-profile"
    assert hardware.schedule_scope == "exclusive-sites-critical-path-v1"

    front_by_name = set()
    for source_row, row in zip(source.evaluations, hardware.evaluations):
        item = cases.get(source_row.candidate.encoding)
        if item is None:
            assert row.status == "ineligible" and row.costs is None
            continue
        spec, _ = item
        assert row.status == "supported" and row.costs is not None, (spec["id"], row.status, row.reason_code)
        cost = row.costs
        assert cost.circuit_error is None and cost.circuit_error_reason == "no-noise-composition-model"
        assert cost.timing_reason == "model-range"
        assert (cost.critical_path_ps.lower_ps, cost.critical_path_ps.upper_ps) == tuple(spec["critical_path_ps"]), spec["id"]
        assert (cost.active_sites, cost.native_operations, cost.two_site_operations) == (
            spec["resources"][0], spec["resources"][3], spec["resources"][4]), spec["id"]
        if row.placement_id in hardware.front_ids:
            front_by_name.add(spec["id"])
    assert front_by_name == set(fixture["expected_front"]), front_by_name
    assert hardware.front_is_partial == fixture["expected_partial_front"]
    # Strict report replay is structural, not re-execution of numerical evidence.
    from q3hash import HardwareReport
    recorded = HardwareReport.from_json(hardware.to_json())
    assert recorded.to_json() == hardware.to_json() and recorded.evidence_origin == "recorded"
    print("PASS: three equivalent qutrit-shift operators, full subspace/leakage/unitarity, six negative/phase controls")
    print("PASS: 3/3 supplied circuits; one (3,2) candidate correctly unimplemented; front explicitly partial")
    for spec in fixture["cases"]:
        lo, hi = spec["critical_path_ps"]
        print(f"PASS: {spec['id']}: structural={spec['resources']}, synthetic critical path=[{lo},{hi}] ps")
    print("PASS: synthetic front={native,mixed}; binary dominated; report round-trip strict; no device measurements")


if __name__ == "__main__":
    run()
