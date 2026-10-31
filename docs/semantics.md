# Executable gate semantics (v0.2)

This document fixes the conventions used by this prototype. All gates act linearly on complex amplitudes. Registers keep their declared dimensions throughout a circuit.

## Registers and basis order

For ordered register dimensions d0, ..., d(n-1), the state space is their tensor product. Every register starts in computational basis state 0; the joint initial state is |0,...,0>.

The flat index of a basis label (j0, ..., j(n-1)) is

    index = sum(jk * product(d_l for l > k) for k in register order).

Thus for dimensions (2, 3), the order is |0,0>, |0,1>, |0,2>, |1,0>, |1,1>, |1,2>. The last register varies fastest. All unmentioned registers are spectators of a gate.

## Shift

For a target of dimension d:

    X_d |k> = |(k + 1) mod d>.

This is a cyclic basis permutation and is unitary. Applying it d times gives identity.

## Fourier

For a target of dimension d:

    F_d |k> = (1 / sqrt(d)) sum(exp(2*pi*i*j*k/d) |j>, j=0,...,d-1).

The exponent is positive. The normalisation factor is essential. For d=2 this is the Hadamard matrix. For d>2 its phases matter even when basis probabilities happen to agree.

The finite geometric sum makes distinct columns orthogonal and gives each column unit norm, so this matrix is unitary. Its fourth power is identity.

## Controlled SUM

Source syntax is `sum control target`. Let the control label be c with dimension d_c, and the target label be t with dimension d_t:

    SUM |c,t> = |c,(t+c) mod d_t>.

The control and target must be different registers. Either can appear earlier in declaration order. Spectator labels do not change.

When both dimensions are 2 this is CNOT. For two qutrits it is the dimension-3 controlled-addition gate. With unequal dimensions, this prototype explicitly defines addition modulo the target dimension, using the control's integer computational label. This convention is part of Q3#'s prototype semantics; it is not an assertion that a hardware platform supplies that gate.

For every fixed c, adding c modulo d_t is bijective. The full mapping therefore permutes the joint computational basis, so its linear extension is unitary for all supported dimension pairs. The inverse subtracts c modulo d_t; d_t repetitions give identity. No assumption that dimensions are equal, prime or coprime is needed for this permutation argument.

The equal-dimension convention follows the SUM definition in Daniel Gottesman, [Fault-Tolerant Quantum Computation with Higher-Dimensional Systems](https://arxiv.org/abs/quant-ph/9802007), equation (12). The mixed-dimension rule above is defined explicitly here; the paper's fault-tolerance results are not claims about this simulator.

## Entanglement demonstrations

Applying Fourier to the control of two equal-dimension registers, followed by SUM, produces

    (1 / sqrt(d)) sum(|j,j>, j=0,...,d-1).

The qubit example has nonzero flat amplitudes at 0 and 3; the qutrit example at 0, 4 and 8. All those amplitudes are positive real with value 1/sqrt(d). For these pure joint states, the reduced density matrix of either register is I/d and its purity is 1/d, below 1.

A qubit control and qutrit target instead give (|0,0> + |1,1>)/sqrt(2), a state in a 2 x 3 space. Reversing the dimensions does not imply the same Schmidt coefficients: Fourier on a qutrit control with a qubit target gives (|0,0> + |1,1> + |2,0>)/sqrt(3), whose reduced purity is 5/9.

Tests check the complex amplitudes and reduced purity, not just probability correlations. These are classical simulations of mathematical states. No measurement sampling, noise or physical quantum device is involved.

## Numerical interpretation

Amplitudes use Python double-precision complex arithmetic. Tests use numerical tolerances, not symbolic proofs. The CLI suppresses basis probabilities at or below 1e-10 and rounds displayed values to eight decimal places; `simulate` returns the complete statevector without that display filtering.
