# Hardware CLI — v0.5.0

`q3hash-hardware` verifies explicitly supplied circuits, then assesses their
declared placements under one profile and context. The equivalent module command
is `python -m q3hash.hardware_cli`. Install the tagged source checkout with
`python -m pip install -e .`; the core has no third-party runtime dependencies.

## Run the included synthetic comparison

```bash
q3hash-hardware examples/logical-qutrit-shift.q3 \
  --constraints examples/qutrit-search.constraints.json \
  --profile examples/qutrit-hybrid.hardware.json \
  --context examples/qutrit-hardware.context.json \
  --implementation examples/qutrit-native.encoding.json examples/logical-qutrit-shift.q3 \
  --implementation examples/qutrit-binary.encoding.json examples/physical-qutrit-shift-binary.q3 \
  --placement examples/qutrit-native.encoding.json '[0]' \
  --placement examples/qutrit-binary.encoding.json '[1,2]'
```

The second placement operand is a **literal JSON array**, quoted for the shell.
It maps each physical register, in declaration order, to a profile site. The
encoding file supplies candidate identity; callers need not calculate hashes.
Site integers must be exact and distinct. Both profile and context files are
required. The context explicitly fixes the as-of instant, permitted calibration
age, objectives and hardware-work budget; the command never reads the current clock.

Both circuits pass the existing complete-subspace verifier. The run uses two
verification calls, 21 gate-column steps and four hardware gate checks. Under the
included **synthetic** profile:

| Placement | Active sites | Native operations | Two-site operations | Critical-path range |
| --- | ---: | ---: | ---: | --- |
| Native qutrit on site 0 | 1 | 1 | 0 | 40,000–60,000 ps |
| Binary circuit on sites 1,2 | 2 | 3 | 2 | 390,000–490,000 ps |

The native placement dominates for the context's four selected objectives. This
is conditional arithmetic from fictitious inputs, not a device benchmark or a
claim that ternary encoding is generally superior. Per-gate error records retain
their metric and occurrence count. Circuit error remains unknown because no
noise-composition model is defined.

## Inputs and coverage

`LOGICAL_Q3` is the positional logical source. Repeat `--implementation
ENCODING_JSON PHYSICAL_Q3` for supplied circuits, `--placement ENCODING_JSON
SITE_INDICES_JSON` for their target mappings, and `--seed ENCODING_JSON` for
explicit generation seeds. An implementation or placement does not implicitly
add a seed. A placement requires a retained encoding and a supplied circuit;
duplicate placements or implementations are errors.

`--constraints FILE` selects strict SearchConstraints JSON; without it the
documented defaults apply, often leaving candidates without supplied circuits.
`--tolerance` defaults to 1e-10 and `--max-dimension` to 64. Source verification
call/work caps are separate from the context's cumulative hardware gate checks.
A skipped oversized operation sequence leaves room for a later smaller circuit.

Every file and literal JSON value has a 1 MiB UTF-8 limit. Each repeated input
category accepts at most 4096 entries. The command validates all files, options,
bindings, placement membership/arity/site bounds and available fingerprint inputs
before numerical work. A valid site-dimension mismatch or unavailable native gate
is an assessment outcome. No routing, synthesis, gate decomposition, device fetch,
automatic placement or dimension inference occurs. Inputs are never rewritten.

Source failures, unsupported/skipped verification and missing circuits remain
explicit, with no hardware costs. Unplaced passing circuits remain unplaced.
Unknown/stale selected timing excludes an incomplete objective vector and marks
the front partial; count-only objectives may still rank it with timing diagnostics.
Known target rejections alone do not make coverage partial. Interval overlap and
ties remain on the front. See the [hardware contract](contracts/hardware-profile-v1.md).

## Output and exit codes

Human output includes coverage and status counts, both work ledgers, source
numerical metrics, profile/provenance/freshness, explicit instants, selected
objectives, placement IDs, exact counts, duration ranges and unknown-data reasons.
The ranking and scheduling scopes are printed explicitly.

Add `--json` for the exact canonical `HardwareReport.to_json()` bytes with no
trailing newline. Both modes buffer and validate the complete wire report before
writing stdout. Representation failures therefore leave no partial report.

| Exit | Meaning, in precedence order |
| --- | --- |
| 2 | Invalid arguments, files, data or wire representation; diagnostics on stderr and no report. |
| 1 | At least one upstream numerical failure; a complete valid report is emitted, even when coverage is also partial. |
| 3 | Partial or inconclusive assessment, including missing evidence, unplaced/skipped rows, unknown selected timing, truncation or an empty domain. |
| 4 | Complete assessment with every placed verified circuit rejected by the target and no supported placement. |
| 0 | A nonempty complete conditional front and no numerical failures. Known rejected alternatives can coexist with supported rows. |

Valid reports may be emitted with exits 1, 3 or 4, so shell scripts should preserve
stdout before handling the status. `--help` and `--version` require no input files.

## Recorded reports and reproducibility

```python
from pathlib import Path
from q3hash import HardwareReport

recorded = HardwareReport.from_json(Path("hardware-report.json").read_text())
assert recorded.evidence_origin == "recorded"
assert recorded.source_report.evidence_origin == "recorded"
```

Decoding validates structure, identities, costs, budgets and fronts without
repeating numerical verification. Historical metadata and calibration provenance
are not authenticated. The CLI accepts original inputs and always obtains fresh
computed source evidence through `evaluate_candidates`; it cannot relabel a saved
report as fresh. Repeated runs in the same recorded numerical environment produce
the same canonical bytes; environment metadata can differ across machines.

The 28 CLI tests and 23 fixed process cases cover statuses, both ledgers, timing,
fronts, preflight errors and all exit classes. Clean wheel and source installations
exercise both module and console commands. Run `python tools/check_hardware_cli.py`
or add `--console /absolute/path/to/q3hash-hardware --isolated` in an installed
environment. The [command contract](contracts/hardware-cli-v1.md) and
[validation guide](validation.md) define the full release gates. The website's
separate web v0.1 runtime remains a v0.6 integration target.
