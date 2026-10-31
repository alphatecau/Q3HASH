"""Dimension-defined logical programs with canonical, fail-closed v1 JSON."""

from dataclasses import dataclass

from . import _serialization as wire
from .core import parse
from .ir import CircuitIR, Operation, Register, lower


SCHEMA = "q3hash.logical-program"
_FIELDS = ("schema", "schema_version", "registers", "operations")


@dataclass(frozen=True)
class LogicalProgram:
    ir: CircuitIR

    def __post_init__(self):
        if not isinstance(self.ir, CircuitIR):
            raise TypeError("Q3-LIR-001: ir must be a CircuitIR")

    @property
    def dimensions(self):
        return self.ir.dimensions

    @property
    def state_size(self):
        return self.ir.state_size

    def to_dict(self):
        return {
            "schema": SCHEMA,
            "schema_version": 1,
            "registers": [{"name": register.name, "dimension": register.dimension}
                          for register in self.ir.registers],
            "operations": [{"kind": operation.kind.value, "target": operation.target,
                            "control": operation.control} for operation in self.ir.operations],
        }

    def to_json(self):
        return wire.write_json(self.to_dict())

    @classmethod
    def from_dict(cls, value):
        wire.header(value, SCHEMA, _FIELDS)
        registers = []
        for item in wire.array(value["registers"]):
            wire.fields(item, ("name", "dimension"))
            if type(item["name"]) is not str or type(item["dimension"]) is not int:
                raise ValueError("Q3-SER-003: incorrect register field types")
            registers.append(Register(item["name"], item["dimension"]))
        operations = []
        for item in wire.array(value["operations"]):
            wire.fields(item, ("kind", "target", "control"))
            if (type(item["kind"]) is not str or type(item["target"]) is not int or
                    (item["control"] is not None and type(item["control"]) is not int)):
                raise ValueError("Q3-SER-003: incorrect operation field types")
            operations.append(Operation(item["kind"], item["target"], item["control"]))
        return cls(CircuitIR(tuple(registers), tuple(operations)))

    @classmethod
    def from_json(cls, text):
        return cls.from_dict(wire.read_json(text))


def logical_from_source(source):
    return LogicalProgram(lower(parse(source)))
