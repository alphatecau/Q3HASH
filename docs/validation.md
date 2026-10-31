# Validation and reproduction

## Reproduce

From a fresh checkout with Python 3.10 or later:

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m q3hash.cli examples/qutrit.q3
python -m q3hash.cli examples/mixed.q3
python -m q3hash.cli examples/bell.q3 --amplitudes
python -m q3hash.cli examples/qutrit-entangled.q3 --amplitudes
python -m q3hash.cli examples/mixed-entangled.q3 --amplitudes
```

GitHub Actions builds wheel and source distributions on Python 3.10, 3.11, 3.12 and 3.13. Each job tests the full suite and every example against isolated installations of the wheel and a wheel rebuilt from the source archive. A separate job runs the optional NumPy/SciPy comparison. See [build-and-audit.md](build-and-audit.md). Use the run associated with the exact source commit as the evidence for a published change; workflow configuration alone is not a passing result.

## Independent numerical construction

`tests/test_semantics.py` builds small dense matrices by enumerating tensor basis-label tuples with `itertools.product`. The production simulator uses resolved axes and statevector strides. The oracle does not import private production helpers or reuse production gate matrices.

- Every column of small SUM matrices is compared against an independently constructed basis permutation.
- SUM column inner products check the full small operators' unitarity.
- Fourier and shift matrices are compared across each axis of several tensor spaces.
- Seeded compositions exercise interference and compare real and imaginary amplitudes to 11 decimal places.
- Cases cover both control/target orders, unequal dimensions and non-adjacent axes with spectators.
- Bell, qutrit and mixed-dimension examples are checked against known amplitudes and reduced-state purity.
- Invalid source, model and IR inputs are rejected at their public boundaries.
- Original tests retain the statevector cap and single-register regression coverage.

The fixed pseudorandom seed is 20261031. The oracle is intentionally limited to small state spaces so it can build full matrices independently.

## Expected example results

| Example | Nonzero basis labels | Probabilities | Joint state |
| --- | --- | --- | --- |
| `qutrit.q3` | 0, 1, 2 | 1/3 each | Fourier applied after a shift of the initial qutrit |
| `mixed.q3` | (1,1) | 1 | A product basis state |
| `bell.q3` | (0,0), (1,1) | 1/2 each | Positive real amplitudes 1/sqrt(2) |
| `qutrit-entangled.q3` | (0,0), (1,1), (2,2) | 1/3 each | Positive real amplitudes 1/sqrt(3) |
| `mixed-entangled.q3` | (0,0), (1,1) | 1/2 each | Positive real amplitudes 1/sqrt(2) in a 2 x 3 space |

Equal probabilities alone do not establish equal states or entanglement. The first example has nontrivial complex phases. The entanglement tests use pure joint states and trace out one register to test reduced-state purity.

## Limits of the evidence

The dense oracle is independently implemented within the same repository. An optional numerical audit additionally compares against NumPy tensor operations and SciPy DFT matrices across the supported dimensions. Neither is an external review, a comparison with another quantum SDK, or formal verification. Finite examples do not prove correctness for every circuit. These checks establish a reproducible numerical baseline for this milestone.

No performance benchmark, quantum advantage, hardware execution, automatic dimension selection or compiler optimisation is demonstrated.
