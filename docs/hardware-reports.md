# Verified hardware reports — v0.5.0.dev3

`assess_hardware` connects a computed SearchReport to an explicit hardware profile,
placements and context. It retains every source candidate, derives conditional
costs and interval fronts, and emits a strict portable HardwareReport.
The hardware CLI and final 0.5 release gates remain pending.

## Compare supplied circuits

Run this example from the development checkout after installing the package:

```python
import json
from pathlib import Path
from q3hash import (
    CircuitImplementation, HardwareContext, HardwarePlacement, HardwareProfile,
    HardwareReport, SearchConstraints, assess_hardware, evaluate_candidates,
    generate_encodings, hardware_front, logical_from_source,
)

logical = logical_from_source("qutrit q\nshift q")
generation = generate_encodings(
    (3,), SearchConstraints(max_registers=2, max_physical_size=4)
)
native, binary = generation.candidates
binary_ir = logical_from_source(
    "qubit a\nqubit b\nsum a b\nsum b a\nshift b"
).ir
source = evaluate_candidates(logical, generation, (
    CircuitImplementation(native.encoding, logical.ir),
    CircuitImplementation(binary.encoding, binary_ir),
))
fixture = json.loads(Path("benchmarks/hardware-cost-v1.json").read_text())
profile = HardwareProfile.from_dict(fixture["profiles"]["hybrid"])
context = HardwareContext.from_dict(fixture["context"])
report = assess_hardware(source, profile, (
    HardwarePlacement(native.candidate_id, (0,)),
    HardwarePlacement(binary.candidate_id, (1, 2)),
), context)
assert report.status_counts["supported"] == 2
assert report.gate_checks == 4
assert hardware_front(report) == (report.evaluations[0].placement_id,)
assert not report.front_is_partial
recorded = HardwareReport.from_json(report.to_json())
assert recorded == report
assert recorded.evidence_origin == recorded.source_report.evidence_origin == "recorded"
```

Both circuits pass the upstream numerical checks. Under this synthetic profile's
declared objectives, the native circuit dominates the supplied binary circuit.
This is a conditional scenario result; the numbers are not measured device costs
or evidence of ternary superiority. General synthesis, routing and noise/channel
composition are outside this model.

## Evidence and comparison scope

The producer requires `source.evidence_origin == "computed"`. It structurally
validates the complete source snapshot and all placements/identity inputs before
cost work, including collision checks. It does not repeat numerical verification.
A recorded source must be reevaluated with the upstream API first.

Placements may arrive in any order and are normalised to source order. Every
retained source candidate receives a row. Missing, failed, unsupported or skipped
source evidence is ineligible; passing unplaced candidates and hardware work
skips remain visible. Known target rejection is a complete infeasibility result.
The [kernel guide](hardware-costs.md) defines work and unknown-data precedence.

An interval vector enters the front only when every selected objective is known.
For each minimised objective, A's upper endpoint must be at most B's lower endpoint,
with at least one strict separation. Overlap, contact without strict separation
and ties retain candidates. Count-only objectives can retain rows with unknown
timing, with those diagnostics still present. The front compares one source,
one exact profile and one context; `hardware_front` accepts one HardwareReport.

`front_is_partial` includes upstream missing coverage, unplaced passes, hardware
budget skips and unknown selected objectives. `front_reason` and `status_counts`
are derived properties. Empty fronts identify the first applicable cause:
no candidates, no verified supplied circuits, no placed passes, no supported
placements, or no complete objective vectors.

## Strict recorded replay

The `q3hash.hardware-report` v1 schema embeds the full source report, profile,
context, ordered placements, derived evaluations, fingerprints, work totals,
front IDs and declared comparison/schedule scopes. HardwareReport and
HardwareEvaluation constructors accept no caller-supplied status/cost/front claims.

Decoding validates nested source evidence structurally, recomputes identities,
freshness, rejections, work, costs and front membership, and rejects inconsistent
claims or order. It makes no numerical calls and never captures a current
environment or clock. Historical metadata is preserved. Decoded evidence remains
recorded; hashes identify content and do not authenticate calibration or snapshots.

Input/derived field inventories, strict numeric types, duplicate-key and UTF-8
handling, and the symmetric 1 MiB JSON limit follow the
[v1 contract](contracts/hardware-profile-v1.md). Large valid in-memory reports
can exceed the wire cap and must raise rather than truncate evidence.

## Reproduce validation

`tests/test_hardware_report.py` adds 28 tests to the preserved 232, for 260 total.
The independent report audit checks 1,116 assessments and recorded replays across
31 objective subsets, four synthetic profiles, three work caps and three placement
coverage choices. It uses three upstream circuit verifications, independent
remaining-work/path/all-pairs oracles and separately constructed placement keys.

```bash
python -m unittest discover -s tests -v
python -I tools/check_hardware_reports.py
```

CI and both clean wheel/source installations run the audit. Existing numerical,
Cirq, generation, resource, search CLI and kernel audits remain required.
The next work package is the explicit hardware CLI contract and implementation.
