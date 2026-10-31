import unittest
from q3hash import parse, simulate, probabilities

class Q3Tests(unittest.TestCase):
    def test_initial_basis_state(self):
        self.assertEqual(probabilities(simulate(parse('qutrit q'))), (1, 0, 0))

    def test_qutrit_shift(self):
        self.assertEqual(probabilities(simulate(parse('qutrit q\nshift q'))), (0, 1, 0))

    def test_fourier_uniform(self):
        p = probabilities(simulate(parse('qutrit q\nfourier q')))
        for value in p:
            self.assertAlmostEqual(value, 1 / 3)

    def test_mixed_dimension_and_axis_target(self):
        state = simulate(parse('qubit a\nqutrit b\nshift a\nshift b'))
        self.assertEqual(len(state), 6)
        self.assertAlmostEqual(abs(state[4]), 1)

    def test_orthonormal(self):
        p = probabilities(simulate(parse('qubit a\nqutrit b\nfourier b\nshift a\nfourier a')))
        self.assertAlmostEqual(sum(p), 1)

    def test_duplicate(self):
        with self.assertRaisesRegex(ValueError, 'already exists'):
            parse('qubit x\nqubit x')

    def test_unknown_target(self):
        with self.assertRaisesRegex(ValueError, 'unknown register'):
            parse('qutrit q\nshift z')

    def test_invalid_dimension(self):
        with self.assertRaisesRegex(ValueError, 'dimension'):
            parse('qudit 1 q')

    def test_invalid_instruction(self):
        with self.assertRaisesRegex(ValueError, 'invalid instruction'):
            parse('qubit q\nmeasure q')

    def test_multiple_shifts_return_initial(self):
        p = probabilities(simulate(parse('qutrit q\nshift q\nshift q\nshift q')))
        self.assertEqual(p, (1, 0, 0))

    def test_dimension_upper_bound(self):
        with self.assertRaisesRegex(ValueError, 'dimension'):
            parse('qudit 33 q')

    def test_statevector_limit(self):
        with self.assertRaisesRegex(ValueError, 'statevector too large'):
            simulate(parse('qudit 32 a\nqudit 32 b\nqudit 32 c\nqudit 3 d'))

    def test_empty_program(self):
        with self.assertRaisesRegex(ValueError, 'at least one register'):
            parse('# no circuit')

if __name__ == '__main__':
    unittest.main()
