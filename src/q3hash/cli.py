"""Command-line runner for Q3# examples."""

import argparse
from pathlib import Path

from .core import parse, probabilities, simulate
from .ir import lower


def _label(index, dimensions):
    labels = []
    for dimension in reversed(dimensions):
        index, value = divmod(index, dimension)
        labels.append(str(value))
    return ",".join(reversed(labels))


def main() -> None:
    parser = argparse.ArgumentParser(description="Experimental Q3# statevector interpreter")
    parser.add_argument("program", type=Path)
    parser.add_argument("--amplitudes", action="store_true", help="include complex state amplitudes")
    args = parser.parse_args()
    try:
        circuit = lower(parse(args.program.read_text(encoding="utf-8")))
        state = simulate(circuit)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print("Q3# experimental simulator | dimensions:", list(circuit.dimensions))
    for index, probability in enumerate(probabilities(state)):
        if probability > 1e-10:
            suffix = ""
            if args.amplitudes:
                amplitude = state[index]
                suffix = f"  amplitude={amplitude.real:+.8f}{amplitude.imag:+.8f}j"
            print(f"|{_label(index, circuit.dimensions)}>: {probability:.8f}{suffix}")


if __name__ == "__main__":
    main()
