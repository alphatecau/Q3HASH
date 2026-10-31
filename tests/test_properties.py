"""Independent, small-state regression properties for the experimental simulator."""
import unittest

from q3hash import Circuit, Gate, Register, parse, probabilities, simulate


class SimulatorProperties(unittest.TestCase):
    def test_fourier_four_times_is_identity(self):
        # The implemented positive-exponent DFT has F**4 == identity.
        for dimension in (2, 3, 4, 5, 7):
            with self.subTest(dimension=dimension):
                circuit = parse(
                    f'qudit {dimension} q\nshift q\n' + 'fourier q\n' * 4
                )
                state = simulate(circuit)
                for index, amplitude in enumerate(state):
                    expected = 1.0 if index == 1 else 0.0
                    self.assertAlmostEqual(amplitude.real, expected, places=10)
                    self.assertAlmostEqual(amplitude.imag, 0, places=10)

    def test_mixed_register_order(self):
        circuit = parse('qubit a\nqutrit b\nqudit 4 c\nshift a\nshift c')
        state = simulate(circuit)
        self.assertEqual(len(state), 24)
        self.assertAlmostEqual(state[13].real, 1.0)
        self.assertAlmostEqual(sum(probabilities(state)), 1.0)

    def test_fourier_preserves_norm_in_mixed_system(self):
        circuit = parse('qubit a\nqutrit b\nqudit 5 c\nfourier a\nfourier b\nfourier c')
        state = simulate(circuit)
        self.assertEqual(len(state), 30)
        self.assertAlmostEqual(sum(probabilities(state)), 1.0, places=12)
        for p in probabilities(state):
            self.assertAlmostEqual(p, 1 / 30, places=12)

    def test_comments_whitespace_and_names(self):
        circuit = parse('  # comment\nqutrit _x5   # register\nshift _x5   # operation\n')
        self.assertEqual(circuit, Circuit((Register('_x5', 3),), (Gate('shift', '_x5'),)))

    def test_statevector_upper_limit_is_accepted(self):
        circuit = parse('qudit 32 a\nqudit 32 b\nqudit 32 c\nqubit d')
        self.assertEqual(len(simulate(circuit)), 65536)


if __name__ == '__main__':
    unittest.main()
