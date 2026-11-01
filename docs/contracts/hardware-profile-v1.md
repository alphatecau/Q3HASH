# v0.5 contract — hardware profiles and conditional circuit costs

**Status:** v0.5.0.dev3 implements the computed-source producer, HardwareReport
v1/replay and interval fronts, following input models, Cirq and the cost kernel.
The hardware CLI remains pending.
**Date:** 1 November 2026, Australia/Brisbane.
**Baseline:** [ADR 0001](../adr/0001-verified-encoding-first.md),
[encoding search v1](encoding-search-v1.md), Python core v0.4.0.

## 1. Decision and comparison boundary

Assess an explicitly supplied, verified circuit under one declared target snapshot
and one explicit register-to-site placement. Preserve the v0.4 generator, verifier,
structural counts, candidate IDs and CLI. Missing data stays unknown.

The initial model is `direct-ir-v1`: the target explicitly supports existing
parameter-free `shift`, `fourier` and ordered `sum` operations with their current
full-dimensional semantics. A target binding is a modelling assertion, not evidence
that a vendor device implements the operation. Real adapters must establish that
semantic correspondence; a matching gate name alone is insufficient.

There is no automatic placement search, routing, gate decomposition, ancilla
allocation, pulse scheduling, noise simulation or device execution in this first
model. Missing native operations are rejected. Their decomposition overhead is
**unknown**, not zero. A later lowering stage must supply and verify its actual
lowered circuit before claiming native counts or timing for it. A reference matrix
does not become a native gate or synthesised circuit.

Results are conditional on one profile and its declared model ranges. They do not
establish physical superiority, calibrated circuit fidelity, global optimality or
formal correctness. Cross-profile results may be displayed side by side, but cannot
share the first implementation's Pareto front.

## 2. Proposed interfaces and dependency direction

```python
@dataclass(frozen=True)
class TimeRange:
    lower_ps: int
    upper_ps: int

@dataclass(frozen=True)
class ErrorRange:
    metric: str
    lower: float
    upper: float

@dataclass(frozen=True)
class ProfileProvenance:
    kind: str                    # synthetic | reported-device
    provider: str
    device_id: str
    snapshot_id: str
    source_uri: str
    retrieved_at: str            # canonical UTC, second precision
    calibrated_at: str | None
    notes: str

@dataclass(frozen=True)
class NativeBinding:
    kind: GateKind
    sites: tuple[int, ...]        # unary: target; SUM: control, target
    duration: TimeRange | None
    error: ErrorRange | None

@dataclass(frozen=True)
class HardwareProfile:
    name: str
    site_dimensions: tuple[int, ...]
    couplings: tuple[tuple[int, int], ...]
    bindings: tuple[NativeBinding, ...]
    provenance: ProfileProvenance
    # profile_id is derived from canonical profile JSON, not an input field.

@dataclass(frozen=True)
class HardwareContext:
    as_of: str
    max_calibration_age_seconds: int
    max_gate_checks: int = 262144
    objectives: tuple[str, ...] = (
        "active_sites", "native_operations", "two_site_operations",
        "critical_path_ps",
    )

@dataclass(frozen=True)
class HardwarePlacement:
    candidate_id: str
    site_indices: tuple[int, ...]

def assess_hardware(
    source: SearchReport, profile: HardwareProfile,
    placements: tuple[HardwarePlacement, ...], context: HardwareContext,
) -> HardwareReport: ...

def hardware_front(report: HardwareReport) -> tuple[str, ...]: ...
```

`hardware_models.py` owns input models, field validation and canonical IDs;
it imports existing IR/serialization only. `hardware_costs.py` owns internal pure
feasibility, budget and timing arithmetic; it allocates no quantum matrices.
`hardware_report.py` owns immutable outputs, interval fronts and strict snapshot replay.
`hardware.py` adapts the complete SearchReport, retaining all candidates.
Neither the existing IR, encoding, verifier nor generator imports this layer.
The seven input models and objective constants are public imports. The
`assess_hardware`, HardwareReport, HardwareEvaluation and `hardware_front` interfaces are implemented.
See the [input guide](../hardware-profiles.md) for delivered methods.
The [cost kernel guide](../hardware-costs.md) describes the implemented arithmetic
and its private integration boundary. Its input source-status fields do not
establish public verification evidence; the complete producer must validate that.

The producer accepts a SearchReport with `evidence_origin == "computed"`.
Recorded JSON evidence must be numerically reevaluated through the existing API
before it can produce newly verified hardware assessments. Strict HardwareReport
decoding instead preserves recorded evidence and replays only pure calculations;
it never invokes a numerical verifier or upgrades a snapshot to fresh evidence.
Private replay helpers avoid a report/orchestrator import cycle.

## 3. Input validation and canonical ordering

Use exact built-in tuple/int types, excluding bool. Wrong public object/container
types raise TypeError; invalid values and nested wire types raise ValueError.
Validate every input, placement and fingerprint before beginning cost work.

| Input | Validation |
| --- | --- |
| TimeRange | Exact integers `0 <= lower_ps <= upper_ps <= 16384 * 10**15`; unit is picoseconds. Each NativeBinding duration additionally has upper_ps at most `10**15`; the larger range accommodates aggregate program times. Equal endpoints represent a declared point model. Zero is an explicit zero-duration assertion, not missing data. |
| ErrorRange | Metric is `average-gate-infidelity`, `process-infidelity` or `reported-unspecified-error`. Endpoints are finite built-in int/float, normalised to float with negative zero normalised to 0.0; `0 <= lower <= upper <= 1`. Bools and overflowing numbers are invalid. |
| Name and provenance identifiers | Nonempty UTF-8 strings; name/provider/device/snapshot at most 128 characters; notes may be empty and are at most 4096 characters. |
| source_uri | Nonempty UTF-8 URI, at most 2048 characters: absolute HTTPS without userinfo, or `urn:q3hash:synthetic:...` for synthetic data. It is metadata, never fetched by evaluation. |
| Timestamps | Real calendar instants, `YYYY-MM-DDTHH:MM:SSZ`, years 1970–9999. No local zone, offsets, fractional seconds, leap seconds or hidden current-clock defaults. |
| Provenance kind | `synthetic` requires null calibrated_at. `reported-device` may have null calibrated_at; otherwise calibration must not be later than retrieval. Synthetic names/numbers must not be presented as device measurements. |
| site_dimensions | Exact tuple, 1–64 entries, each an exact integer 2–32. This is the dimension model for each indexed site, not a promise about unmodelled device levels. Never allocate the product of all device dimensions. |
| couplings | Exact tuple of distinct directed `(control, target)` index pairs, sorted lexicographically; distinct sites, both in range. At most 4032 edges. Reverse direction is a different edge. Empty is valid. |
| bindings | Exact tuple, at most 8192 entries, sorted by kind order `(shift, fourier, sum)`, then site tuple. Unique `(kind, sites)` keys. Empty is valid. |
| NativeBinding kind/sites | Direct kind is an existing GateKind instance; wire kind is its exact lowercase string. One site for shift/fourier; two distinct sites in control/target order for sum. Indices are exact integers in range. Every sum binding must have its directed coupling edge; otherwise the profile is inconsistent. |
| Context age | Exact integer 0–31,536,000 seconds. `as_of` is explicit and cannot precede profile retrieval or a known calibration instant. |
| Context work cap | Exact integer 1–4,194,304 gate checks; default 262,144. Independent of v0.4 numerical call/work budgets. |
| Objectives | Nonempty exact tuple of distinct names from section 7; order is retained for display. Never remove an objective automatically to fit missing data. |
| Placements | Exact tuple, at most 4096 items, at most one per retained candidate; each candidate must have a supplied circuit. Site index tuple length equals physical register count; indices are distinct exact integers in range. Reject unrelated/duplicate bindings, even identical repeats. |

Logical register order, encoding order and site order are significant. A placement
maps physical register axis `i` to `site_indices[i]`; it does not change the basis
encoding or reorder the physical program. Placements may arrive in any order and
are normalised to source candidate order. Stored arrays must already have that
order; decoders reject rearranged evidence.

A valid placement onto an incompatible site dimension is an `unsupported` outcome,
not a malformed-program exception. Out-of-range, repeated or wrong-arity placement
indices are invalid input. A higher-dimensional site does not implicitly realise
a lower-dimensional register; exact equality is required in this first model.

## 4. Freshness, provenance and unknown data

Freshness is computed from explicit instants, with no wall-clock calls:

- Synthetic: `synthetic`, with scenario values available under their stated ranges.
- Reported and calibrated: `fresh` iff `0 <= as_of - calibrated_at <= max_age`;
  otherwise `stale`. Equality at the age limit is fresh.
- Reported without a calibration instant: `unknown`.

For a nonempty supported circuit, aggregate time is unknown when calibration is
stale/unknown or any used binding has null duration. Keep supplied ranges and error
records in the profile; do not erase the source evidence. Freshness does not turn
an absent value into a value. A missing *unused* binding duration is irrelevant.

Empty circuits have critical-path and serial time `[0,0]` even with missing/stale
calibration: there are no modelled operations. This excludes preparation, readout,
idle/decoherence and application overhead. It does not predict physical fidelity.

Model intervals are declared ranges, **not statistical confidence intervals or
certified device bounds**. A reported point with no error bars remains a point
model with uncertainty unreported in provenance notes. Do not invent confidence
levels or extra significant figures. Adapters preserve original units, source,
retrieval/calibration instants and interpretation in their reproducibility record.

Qiskit uses seconds for instruction durations. A future importer converts the
recorded decimal value to integer picoseconds with outward floor/ceiling using
exact decimal arithmetic, retaining the original record. That conversion encloses
the recorded number; it does not supply a physical measurement uncertainty.

## 5. Eligibility, feasibility and bounded work

The complete producer retains exactly one HardwareEvaluation per source candidate
in source order. The kernel retains every private input in the same order.
Precedence is normative:

1. Source evaluation is not pass: `ineligible`, reason `source-` plus its source
   status (`unimplemented`, `fail`, `unsupported`, `not-evaluated`). No costs/checks.
2. No placement for a passing source circuit: `unplaced`, `no-placement`. No costs.
3. Any placed site dimension disagrees: `unsupported`, `site-dimension`. Retain
   all mismatching-axis rejections; no gate checks or cost vector.
4. The circuit's entire operation count would exceed remaining gate checks:
   `not-evaluated`, `hardware-operation-budget`; charge nothing and continue.
5. Charge the full operation count. Inspect every operation, retaining one rejection
   per failing operation: absent SUM edge first (`directed-coupling`), otherwise
   absent exact native binding (`native-gate`). Any rejection yields `unsupported`,
   reason `target-rejections`, with null costs.
6. Otherwise `supported`, `native-model-supported`. Derive counts and timing.

SUM sites are `(placement[control], placement[target])`; unary sites are
`(placement[target],)`. Connectivity never implies native support, and native
support in one direction never implies its reverse. Numerical failure cannot be
rescued by cheap/available hardware. Exceptions are not converted to unsupported.

Whole-row reservation bounds work deterministically: an assessed row charges all
its operations even if an early rejection exists, because all are inspected.
Dimension rejection, missing placement, source ineligibility and a skipped row
charge zero. Identity charges zero gate checks. A later smaller row can fit after
a budget skip. Record `gate_checks`; do not count these as numerical verifications.
Numerical calls/work remain the unchanged totals in the embedded SearchReport.

Costs use a complete supplied physical circuit after source verification. Routing,
decomposition and synthesis are `not-applied`; a rejected unlowered gate's overhead
is unknown. Future lowered implementations must be actual CircuitIR inputs, with
their gates, encoding, basis order and correctness checked rather than discounted.

## 6. Timing and error mathematics

All time arithmetic uses exact nonnegative integer picoseconds. For operations
in program order, create a predecessor edge from each earlier operation sharing
a touched physical site. Disjoint site operations may overlap in this **exclusive
sites, zero extra latency** model. It does not model shared drive/readout channels,
crosstalk, scheduling granularity, alignment, communication or setup latency.

For operation `g` with supplied range `[l_g,u_g]`, let its predecessor set be P(g):

```text
L(g) = l_g + max({L(p): p in P(g)} union {0})
U(g) = u_g + max({U(p): p in P(g)} union {0})
critical_path_ps = [max_g L(g), max_g U(g)]
serial_duration_ps = [sum_g l_g, sum_g u_g]
```

Empty maxima/sums are zero. Nonnegative durations make these exact extrema of the
declared duration box under this DAG model; no statistical independence is claimed.
They are dependency-path timing estimates, not measured device execution times.
Unknown required timing makes both aggregates null, with `timing_reason` chosen
in this order: `stale-calibration`, `unknown-calibration`, `missing-duration`.
Known timing uses `model-range`; empty timing uses `empty-circuit`.

Retain each used binding's error record and occurrence count in profile-binding
order. Null records stay null. Metrics with different definitions are not merged.
No circuit error/success estimate is produced: `circuit_error` is null and
`circuit_error_reason` is `no-noise-composition-model`, including for empty programs.
Neither `1-product(1-error)` nor a sum of gate infidelities is asserted to be a
circuit failure probability. Noise/channel composition needs a separate contract.

## 7. Cost vectors and conservative Pareto fronts

| Objective | Value and unit |
| --- | --- |
| `active_sites` | Physical register count under injective placement; exact count. |
| `native_operations` | Actual supplied IR operation count after exact native support; exact count. |
| `two_site_operations` | Actual SUM count; exact count. |
| `critical_path_ps` | Section 6 interval, or unknown. |
| `serial_duration_ps` | Section 6 interval, or unknown; optional objective, not in default tuple. |

Keep existing six structural ResourceCounts separately in the source report. Do
not change their meanings or call logical blocks physical hardware costs.

An eligible vector requires source pass, a placement, native-model support and
known values for **every selected objective**. Unknown unselected timing remains
visible but does not prevent an explicitly requested count-only comparison.
Treat exact counts as point ranges. For minimised objective ranges, A dominates B
only when every `upper(A_j) <= lower(B_j)` and at least one is strictly `<`.
Overlap, endpoint contact without any strict separation and ties do not establish
dominance. Preserve all ties and source order; use no epsilon or weighted sum.

Compare only the exact same logical program, profile snapshot, source settings,
as-of/age policy, scheduling model and objective tuple. A changed calibration or
duration changes the profile ID and comparison group. Cross-profile dominance is
an error, not a scientific inference. Front IDs are placement IDs, not reused
encoding-only candidate IDs.

`ranking_scope` is `verified-supplied-placements-under-one-profile` and
`schedule_scope` is `exclusive-sites-critical-path-v1`.
The front is partial when source coverage is partial, any passing candidate is
unplaced, any hardware row is budget-skipped, or any otherwise supported row has
an unknown selected objective. Known target rejection is a completed infeasibility
assessment, not missing work. All omissions/status counts remain beside the front.

Empty-front reasons, in priority order, are `no-candidates`,
`no-verified-supplied-circuits`, `no-placed-verified-circuits`,
`no-supported-placements`, `no-complete-objective-vectors`. A nonempty front uses
the ranking-scope string. An empty front is never a passing hardware recommendation.

## 8. Identity, strict wire schemas and report replay

Reuse duplicate-key rejection, finite JSON, exact fields, sorted object keys,
UTF-8 validation and the symmetric 1 MiB cap. Arrays retain declared order. Integer
time totals remain lossless integers; clients must not round them through floating
point. A valid large in-memory report may exceed the wire cap and must fail
serialization rather than truncate evidence.

Profiles and contexts implement the following exact `schema` and integer
`schema_version: 1` headers. The hardware-report schema is implemented as well:

| Schema | Additional fields |
| --- | --- |
| `q3hash.hardware-profile` | `name`, `site_dimensions`, `couplings`, `bindings`, `provenance` |
| `q3hash.hardware-context` | `as_of`, `max_calibration_age_seconds`, `max_gate_checks`, `objectives` |
| `q3hash.hardware-report` | `source_report`, `source_id`, `profile`, `profile_id`, `context`, `context_id`, `placements`, `evaluations`, `freshness`, `gate_checks`, `front_ids`, `ranking_scope`, `schedule_scope`, `engine_version` |

Nested inventories are exact:

- TimeRange: `lower_ps`, `upper_ps`.
- ErrorRange: `metric`, `lower`, `upper`.
- Provenance: every ProfileProvenance field in section 2, including null calibration.
- NativeBinding: `kind` (existing lowercase gate literal), `sites`, `duration`, `error`.
- HardwarePlacement: `candidate_id`, `site_indices`.
- HardwareEvaluation: `candidate_id`, `placement_id`, `status`, `reason_code`,
  `rejections`, `gate_checks`, `costs`.
- Rejection: `code`, `operation_index`, `axis_index`, `sites`; dimension rejection
  has an axis and null operation; gate rejection has an operation and null axis.
- Costs, present only for supported rows: `active_sites`, `native_operations`,
  `two_site_operations`, `critical_path_ps`, `serial_duration_ps`, `timing_reason`,
  `used_errors`, `circuit_error`, `circuit_error_reason`.
- Used error: `kind`, `sites`, `occurrences`, `error` (null or ErrorRange).

Profile/context/source IDs are lowercase SHA-256 of their entire canonical JSON,
without trailing newline. The source ID uses SearchReport.to_json(), including
its recorded provenance. Preflight must reject unrepresentable fingerprints before
hardware work. Hashes identify content, not authenticated calibration.

A placement ID hashes the canonical object with exactly `schema`:
`q3hash.hardware-placement-key`, `schema_version: 1`, `profile_id`, `candidate_id`,
`physical_id` (the existing physical-program ID), and `site_indices`. It is null
only when no placement was supplied. A source candidate without an implementation
cannot have a placement. Detect collisions by comparing complete identity inputs.

HardwareReport retains immutable inputs and producer-derived rows. Its constructor
accepts no cost/front/status claims. `from_dict`/`from_json` validate the complete
nested source report, profile/context/placement IDs and order, eligibility,
freshness, every rejection/check counter, exact cost arithmetic and the front.
Decode as `evidence_origin="recorded"`, never numerically verify or substitute the
current clock/environment. Status counts, partial flag and front reason are derived
properties, not extra wire fields. Reports from identical complete inputs/settings
repeat byte-for-byte; numerical source-report platform differences retain v0.4's
documented qualification.

## 9. Errors and acceptance gates

| Prefix | Meaning |
| --- | --- |
| `Q3-HARD-001` | Wrong public types or invalid context/objective values. |
| `Q3-HARD-002` | Invalid profile fields, ordering, bounds, connectivity or provenance. |
| `Q3-HARD-003` | Placement membership, uniqueness, index or arity error. |
| `Q3-HARD-004` | Digest collision with unequal identity inputs. |
| `Q3-HARD-005` | Untrusted producer input or inconsistent constructed/decoded report. |
| Existing `Q3-SER-*` and source-report errors | Preserve applicable strict-wire and v0.4 diagnostics. |

| ID | Required production behaviour |
| --- | --- |
| HVAL-01 | Reject bool/float indices/times, unordered/duplicate tuples, inconsistent SUM bindings and invalid time/error intervals before work. |
| HVAL-02 | Reject a malformed later placement and a recorded SearchReport producer input before cost work. |
| HFEAS-01 | Exact dimensions and directed edges matter; a reverse SUM or absent native gate is unsupported, without implicit routing/decomposition. |
| HFEAS-02 | Every source candidate retains a row; missing circuits, numerical failures/unsupported/skips and unplaced passes cannot get costs. |
| HTIME-01 | Empty, serial, disjoint and joining dependency paths match independent path enumeration; zero duration differs from null. |
| HTIME-02 | A missing used duration or stale/unknown calibration yields null timing; unused missing data does not. Identity timing stays zero. |
| HFRESH-01 | Exact age boundary is fresh; an older snapshot is stale; missing calibration is unknown; future/as-of inconsistencies are invalid. |
| HBUD-01 | All-operation reservation/charging, dimension rejection, unsupported rows, identity and later-small-after-skip accounting are exact. |
| HPAR-01 | Point vectors reduce to strict integer dominance; overlapping/contacting ranges retain candidates; unknown selected metrics cannot enter the front. |
| HPAR-02 | Count-only requests retain unknown timing diagnostics; cross-profile or workload/settings comparisons are rejected. |
| HERR-01 | Error records retain their definitions and missing data; no independent-success product, sum-to-failure conversion or hidden error objective is produced. |
| HSER-01 | Replay rejects altered identities, metrics, freshness, front order, counts, unknown keys, malformed Unicode/numbers and oversized wire data, without numerical calls. |
| HREF-01 | Frozen workloads agree at full operator/subspace level with an independently constructed reference; state-preparation agreement alone is insufficient. |
| HREG-01 | All 186 v0.4 tests, examples, original audits, installed distributions, existing CLIs and stable tags remain intact. |

The [reference vectors](../../benchmarks/hardware-cost-v1.json) and
[tools/check_hardware_contract.py](../../tools/check_hardware_contract.py) check
tiny fixed mathematical cases. The input-model tests and
`tools/check_external_operators.py` separately validate delivered inputs and the
Cirq composition baseline. `tools/check_hardware_costs.py` compares the implemented
kernel with independent paths/ledgers. The public verified-assessment producer, report replay and interval fronts
have additional tests/audits; the hardware CLI remains pending.
Use the [work packages](../plans/v0.5-implementation.md) for implementation gates.

## 10. External references and interpretation

Reviewed 1 November 2026. These references inform interface conventions; Q3# does
not import their cost assumptions or claim device interoperability from a URL.

- [Qiskit Target](https://quantum.cloud.ibm.com/docs/en/api/qiskit/qiskit.transpiler.Target):
  instruction availability/properties are associated with ordered target operands.
- [InstructionProperties](https://quantum.cloud.ibm.com/docs/en/api/qiskit/qiskit.transpiler.InstructionProperties):
  optional instruction durations are specified in seconds. Unknown properties do
  not imply zero-cost operations.
- [Qiskit quantum information measures](https://quantum.cloud.ibm.com/docs/en/api/qiskit/quantum_info):
  average gate fidelity is a channel measure; its `gate_error` uses average gate
  infidelity. Preserve a reported metric's definition rather than treating every
  provider's field as a circuit-failure probability.
- [Cirq qudits](https://quantumai.google/cirq/build/qudits),
  [MatrixGate](https://quantumai.google/reference/python/cirq/MatrixGate) and
  [Circuit.unitary](https://quantumai.google/reference/python/cirq/Circuit):
  dimensioned Qids and explicit qid shapes support the planned independent
  composition baseline. Set operand order and spectator sites explicitly.

The restriction on aggregating error values and the separated-interval comparison
rule are conservative Q3# design decisions. They are not claims that these sources
provide a physical confidence guarantee or a native implementation of every Q3# gate.
