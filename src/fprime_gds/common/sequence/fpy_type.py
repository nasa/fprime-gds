import ast
from dataclasses import dataclass
from fprime.common.models.serialize.enum_type import EnumType
from fprime.common.models.serialize.time_type import TimeType
from fprime.common.models.serialize.type_base import (
    BaseType,
    BaseType,
    ValueType,
)

from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime_gds.common.sequence.directive import SeqDirectiveTemplate

# name, desc, type
FpyArgTemplate = tuple[str, str, type[BaseType]]


# just for pretty-printing
def base_type_repr(self: BaseType):
    if isinstance(self, ValueType):
        return str(self.val)
    return self.__class__.__name__


BaseType.__repr__ = base_type_repr


@dataclass
class FpyType(ast.AST):
    namespace: str
    name: str
    fprime_type: type[BaseType]


# this just helps the ast find what fields to pretty-print
FpyType._fields = ["namespace", "name", "fprime_type"]


@dataclass
class FpyEnumConstant(ast.AST):
    enum_type: type[EnumType]
    repr_type: type[BaseType]
    const_name: str
    const_val: int


FpyEnumConstant._fields = ["enum_type", "repr_type", "const_name"]


@dataclass
class FpyCmd(ast.AST):
    namespace: str
    name: str
    cmd_template: CmdTemplate

    # added in AddTimestamps step
    time: TimeType = None
    is_time_relative: bool = None


FpyCmd._fields = ["namespace", "name", "cmd_template", "time"]


@dataclass
class FpyCh(ast.AST):
    namespace: str
    name: str
    ch_template: ChTemplate


FpyCh._fields = ["namespace", "name", "ch_template"]


@dataclass
class FpySeqDirective(ast.AST):
    namespace: str
    name: str
    seq_directive_template: SeqDirectiveTemplate


@dataclass
class FpyArg(ast.AST):
    name: str
    type: type[BaseType]
    node: ast.AST

    # added in ConstructFpyTypes step
    type_instance: BaseType = None


FpyArg._fields = ["name", "type", "node", "type_instance"]


@dataclass
class FpyCall(ast.expr):
    func: FpyType | FpyCmd | FpySeqDirective
    args: list[FpyArg]

    def get_arg(self, name: str):
        matching = [a for a in self.args if a.name == name]
        if len(matching) != 1:
            raise RuntimeError("Error finding arg " + str(name) + ": found " + str(len(matching)) + " matching args")
        return matching[0]

FpyCall._fields = ["func", "args"]
