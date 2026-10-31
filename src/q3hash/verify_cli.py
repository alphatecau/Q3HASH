"""Human-readable full small-subspace verification; report wire format is deferred."""

import argparse
import hashlib
from pathlib import Path

from .encoding import BasisEncoding
from .logical_ir import logical_from_source
from .verification import verify_equivalence


def _identifier(value):
    return hashlib.sha256(value.to_json().encode("utf-8")).hexdigest()


def _size_text(value):
    # Valid model dimensions may exceed Python's decimal integer-printing budget.
    bits = value.bit_length()
    return str(value) if bits <= 4096 else f"an integer with {bits} bits"


def main():
    parser = argparse.ArgumentParser(description="Q3# complete small encoded-subspace verification")
    parser.add_argument("logical", type=Path)
    parser.add_argument("physical", type=Path)
    parser.add_argument("--encoding", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=1e-10)
    parser.add_argument("--max-dimension", type=int, default=64, help="dense physical dimension budget (1–64)")
    args = parser.parse_args()
    try:
        logical = logical_from_source(args.logical.read_text(encoding="utf-8"))
        physical = logical_from_source(args.physical.read_text(encoding="utf-8"))
        encoding = BasisEncoding.from_json(args.encoding.read_text(encoding="utf-8"))
        report = verify_equivalence(logical, physical.ir, encoding, tolerance=args.tolerance,
                                    max_dimension=args.max_dimension)
        identifiers = {"Logical": _identifier(logical), "Physical": _identifier(physical),
                       "Encoding": _identifier(encoding)}
    except (OSError, TypeError, ValueError) as error:
        parser.error(str(error))
    print("Q3# complete small-subspace verification:", report.status)
    print(report.reason)
    print("Evidence:", report.evidence, "| no hardware backend or formal proof")
    print("Dimensions:", _size_text(report.logical_size), "logical ->", _size_text(report.physical_size), "physical")
    print("Tolerance:", report.tolerance)
    if report.global_phase is not None:
        print("Global phase:", report.global_phase)
        print("Subspace Frobenius residual:", report.subspace_residual)
        print("Leakage Frobenius norm:", report.leakage_norm)
        print("Logical unitarity error:", report.logical_unitarity_error)
        print("Physical unitarity error:", report.physical_unitarity_error)
    for name, identifier in identifiers.items():
        print(name + " semantic SHA-256:", identifier)
    raise SystemExit({"pass": 0, "fail": 1, "unsupported": 3}[report.status])


if __name__ == "__main__":
    main()
