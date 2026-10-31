"""Q3# experimental quantum language prototype."""
from .core import apply_state, parse, probabilities, simulate
from .ir import Circuit, CircuitIR, Gate, GateKind, Operation, Register, lower
from .encoding import BasisEncoding
from .equivalence import ReferenceOperator
from .logical_ir import LogicalProgram, logical_from_source
from .verification import VerificationReport, verify_equivalence
from .search import DimensionRejections, EncodingCandidate, GenerationReport, SearchConstraints, generate_encodings

__all__ = [
    'Circuit', 'CircuitIR', 'Gate', 'GateKind', 'Operation', 'Register',
    'lower', 'parse', 'simulate', 'probabilities',
    'apply_state', 'LogicalProgram', 'logical_from_source', 'BasisEncoding',
    'ReferenceOperator', 'VerificationReport', 'verify_equivalence',
    'SearchConstraints', 'EncodingCandidate', 'DimensionRejections', 'GenerationReport', 'generate_encodings',
]
