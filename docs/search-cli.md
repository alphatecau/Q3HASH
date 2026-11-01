# Bounded encoding search

Install the repository with `python -m pip install -e .` using Python 3.10 or later.
The search command generates a finite set of encoding maps and checks physical
circuits you explicitly supply. It does not synthesise a circuit from a map.

## Compare the supplied qutrit implementations

Run from the repository root:

```bash
q3hash-search examples/logical-qutrit-shift.q3 \
  --constraints examples/qutrit-search.constraints.json \
  --implementation examples/qutrit-native.encoding.json examples/logical-qutrit-shift.q3 \
  --implementation examples/qutrit-binary.encoding.json examples/physical-qutrit-shift-binary.q3
```

Both candidates pass the complete-subspace verifier. The run consumes two calls
and 21 gate-column steps. Both are on the default front: the native qutrit circuit
uses fewer registers/gates, while the binary circuit requires fewer local levels.
These are exact structural trade-offs, not hardware cost estimates.

Use `python -m q3hash.search_cli` for the module equivalent. `--help` lists options;
`--version` reports the installed package version.

## Inputs and limits

| Argument | Meaning |
| --- | --- |
| `LOGICAL_Q3` | Existing Q3# source with explicit register dimensions. |
| `--constraints FILE` | Complete strict SearchConstraints JSON v1. If omitted, use the documented defaults. |
| `--seed FILE` | Encoding JSON v1; repeat in the order seeds should be considered. |
| `--implementation ENCODING_JSON PHYSICAL_Q3` | Bind a retained encoding to an explicitly supplied physical circuit; repeat as needed. |
| `--max-dimension N` | Dense verifier limit, 1–64. Independent of generation's physical-size limit. |
| `--tolerance NUMBER` | Positive finite verification tolerance; default 1e-10. |
| `--json` | Emit only the strict canonical aggregate report. |

The constraints file controls physical alphabets/register counts, map families,
generation caps, per-program operations, cumulative verifier calls/work and
selected objectives. Edit it through the public SearchConstraints model to preserve
all required fields; see the [contract](contracts/encoding-search-v1.md).

An implementation does not implicitly add a seed. If a custom map is outside the
generated families, supply it with `--seed` as well. Bindings may arrive in any
order, but all are validated before numerical work and reported in generation order.
Missing circuits remain unimplemented. Files are UTF-8 with a 1 MiB transport cap;
at most 4096 seeds and 4096 bindings are accepted. The command changes no files.

## Results and exit codes

Human output shows completion and rejection/duplicate counters, all candidate
statuses/reasons, verification metrics, budget totals, selected resource counts
and front membership. A partial front remains explicitly labelled partial.

| Exit | Meaning |
| --- | --- |
| 0 | Nonempty exhausted candidate set; every supplied candidate check passes. |
| 1 | At least one actual numerical failure; takes precedence over partial coverage. |
| 2 | Invalid input/options, unreadable file or representation/transport limit. No report on stdout. |
| 3 | Valid partial/inconclusive result: missing, unsupported or skipped circuits, truncated generation, or zero candidates. |

Statuses 1 and 3 still emit a valid report. An empty front is never a passing run.
A failed check consumes its call/work budget. A skipped check consumes neither;
a later smaller circuit may still fit. Identity checks consume a call even with
zero gate-column steps. No exit code establishes global encoding optimality.

## Save and read a report

Add `--json` and redirect stdout to a new file you choose. Shell redirection can
overwrite an existing file; use a fresh report path. The command writes exactly
SearchReport.to_json(), without a trailing newline or other output, within the
strict 1 MiB wire cap. Diagnostics go to stderr.

```python
from pathlib import Path
from q3hash import SearchReport

recorded = SearchReport.from_json(Path("search-report.json").read_text(encoding="utf-8"))
assert recorded.evidence_origin == "recorded"
print(recorded.status_counts, recorded.front_is_partial, recorded.front_ids)
```

Decoding checks bounded generation replay, content IDs, statuses, budgets,
resource counts and front membership. It does not rerun numerical verification or
authenticate recorded version/environment metadata. Reports rank
`passing-supplied-circuits-only`; they do not establish hardware performance.
