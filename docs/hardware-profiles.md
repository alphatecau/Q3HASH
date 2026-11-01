# Hardware inputs — v0.5

Input models/strict JSON and the independent Cirq baseline are available since
v0.5.0.dev1. v0.5.0.dev2 adds the [internal cost kernel](hardware-costs.md).
The stable source release remains v0.4.0. Use the current development checkout
for these imports.

The [verified report API](hardware-reports.md), interval fronts and recorded replay
are implemented in v0.5.0.dev3. The hardware CLI remains pending. A valid profile or matching identifier does not establish device support,
source verification or measured performance.

## Construct and identify a synthetic profile

```python
import hashlib
from q3hash import (
    GateKind, HardwareContext, HardwarePlacement, HardwareProfile, NativeBinding,
    ProfileProvenance, SearchConstraints, TimeRange,
    generate_encodings, logical_from_source,
)

profile = HardwareProfile(
    name="Synthetic qutrit",
    site_dimensions=(3,),
    couplings=(),
    bindings=(NativeBinding(GateKind.SHIFT, (0,), TimeRange(40_000, 60_000), None),),
    provenance=ProfileProvenance(
        kind="synthetic", provider="Q3# examples", device_id="one-qutrit",
        snapshot_id="scenario-1", source_uri="urn:q3hash:synthetic:one-qutrit",
        retrieved_at="2026-11-01T00:00:00Z", calibrated_at=None,
        notes="Scenario values only; no measured device data.",
    ),
)
context = HardwareContext("2026-11-01T01:00:00Z", 3600)
context.validate_profile(profile)
assert HardwareProfile.from_json(profile.to_json()) == profile

physical = logical_from_source("qutrit q\nshift q")
candidate, = generate_encodings(
    (3,), SearchConstraints(allowed_dimensions=(3,), max_registers=1, max_physical_size=3)
).candidates
placement = HardwarePlacement(candidate.candidate_id, (0,))
placement.validate_for(profile, physical.dimensions)
physical_id = hashlib.sha256(physical.to_json().encode("utf-8")).hexdigest()
placement_id = placement.identifier(profile.profile_id, physical_id)
assert len(placement_id) == len(context.context_id) == 64
```

The declared 40,000–60,000 ps range is 40–60 ns. It is a synthetic range, not a
measurement or confidence interval. `None` represents missing duration/error data;
`TimeRange(0, 0)` is an explicit zero-duration model. Gate error definitions remain
separate and do not provide an aggregate circuit success probability.

## Input and wire rules

| Model | Validation and serialization |
| --- | --- |
| `TimeRange` | Exact integer picoseconds, including totals above JavaScript's exact floating-point integer range. Native bindings cap the upper endpoint at `10**15`; aggregate ranges cap it at `16384 * 10**15`. |
| `ErrorRange` | A declared error metric and finite endpoints in `[0,1]`; integer endpoints normalise to float and negative zero becomes `0.0`. |
| `ProfileProvenance` | Explicit UTC timestamps, bounded UTF-8 metadata and absolute HTTPS or synthetic Q3# URNs. URIs are metadata and are not fetched. Synthetic data has null calibration. |
| `NativeBinding` | An existing `GateKind`, exact ordered site tuple and optional ranges. SUM uses `(control, target)`. |
| `HardwareProfile` | Up to 64 sites, directed edges, unique canonical native bindings and matching site indices. A SUM binding requires its directed edge. Profile validation never allocates the product state space. |
| `HardwareContext` | Explicit as-of instant, age/work caps and ordered known objectives. `validate_profile` rejects an as-of instant before retrieval/calibration without consulting the current clock. |
| `HardwarePlacement` | A lowercase SHA-256 candidate ID and distinct site indices. `validate_for` checks profile bounds and physical arity. Exact dimension mismatch is a valid unsupported kernel outcome. |

Every model exposes `to_dict`, `from_dict`, `to_json` and `from_json`. Only profiles
and contexts have top-level schema headers; nested objects and placements retain
the inventories in the [v1 contract](contracts/hardware-profile-v1.md). Decoders
require exact fields/types and canonical array order. Bools cannot substitute for
integers. Duplicate keys, nonfinite numbers, malformed Unicode and payloads over
the symmetric 1 MiB UTF-8 limit are rejected.

`profile_id` and `context_id` hash the entire canonical JSON. They are derived
properties, not accepted wire claims. Computing them enforces the same wire cap.
`placement.identifier(profile_id, physical_id)` hashes the contract's complete
placement key. These hashes identify content; they do not authenticate provenance.
Serializers return fresh containers and preserve integer time values exactly.

Wrong direct public types raise `TypeError` with `Q3-HARD-001`. Invalid profile
values use `Q3-HARD-002`, invalid placements use `Q3-HARD-003`, and context values
use `Q3-HARD-001`. Strict JSON mechanics retain `Q3-SER-*` diagnostics.

Source candidate membership, duplicate placement bindings, recorded-source rejection
and digest collision checks are implemented by the [complete report producer](hardware-reports.md).
Standalone input helpers do not perform circuit verification.

## Run the independent framework baseline

The runtime package still has no third-party dependencies. External validation
requires Python 3.11+ and pins `cirq-core==1.7.0`:

```bash
python -m pip install ".[external-validation]"
python -I tools/check_external_operators.py
```

Missing Cirq, a different version or a numerical mismatch fails the check; none
is treated as a skipped pass. A separate required CI job runs this baseline.
The four Python 3.10–3.13 distribution jobs remain independent of Cirq.

The audit independently reads the fixed source subset, creates dimensioned Qids
and local gate matrices, and lets Cirq compose the complete operator. It sets
declaration order and spectator sites explicitly, uses `complex128`, and rejects
terminal measurements. Binary gates use Cirq X/H/CNOT. Custom qudit matrices
implement the mathematical rules without importing Q3# gate/stride/operator helpers.

Recorded local coverage is 523 distinct programs, 15,321 complete basis columns
and 2,092 arbitrary states. It includes every single-gate dimension 2–32, all
153 SUM dimension pairs fitting 64 states in both axis orders, 36 spectator
circuits, 120 seeded compositions and all 13 frozen workload cases. Duplicate
generated sources are checked once. Of the frozen cases, nine pass, two fail,
one is unsupported under its original limit and one has no supplied physical circuit.

Output records framework/dependency versions, seed, dtype, basis order, tolerance,
fixture digest, coverage, maximum errors and individual workload statuses.
This establishes a reproducible SDK composition comparison. It does not establish
native hardware availability, external peer review, a binary entangling synthesis
or measured hardware costs. The [cost kernel guide](hardware-costs.md) covers
conditional arithmetic; the [work packages](plans/v0.5-implementation.md) define
the remaining CLI and release gates.
