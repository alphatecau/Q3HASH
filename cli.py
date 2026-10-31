"""Command-line runner for Q3# examples."""
import argparse
from pathlib import Path
from .core import parse, probabilities, simulate

def main() -> None:
    parser = argparse.ArgumentParser(description='Experimental Q3# statevector interpreter')
    parser.add_argument('program', type=Path)
    args = parser.parse_args()
    circuit = parse(args.program.read_text(encoding='utf-8'))
    dims = [r.dimension for r in circuit.registers]
    print('Q3# experimental simulator | dimensions:', dims)
    for index, probability in enumerate(probabilities(simulate(circuit))):
        if probability > 1e-10:
            print(f'|{index}>: {probability:.8f}')

if __name__ == '__main__':
    main()
