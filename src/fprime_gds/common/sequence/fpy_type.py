import ast
from dataclasses import dataclass
from fprime.common.models.serialize.enum_type import EnumType
from fprime.common.models.serialize.type_base import BaseType, BaseType, DictionaryType

from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime_gds.common.sequence.directive import SeqDirectiveTemplate

# name, desc, type
FpyArgTemplate = tuple[str, str, type[BaseType]]


# just for pretty-printing
def value_type_repr(self: BaseType):
    return str(self.val)


BaseType.__repr__ = value_type_repr


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
    value: int


FpyEnumConstant._fields = ["enum_type", "repr_type", "value"]


@dataclass
class FpyCmd(ast.AST):
    namespace: str
    name: str
    cmd_template: CmdTemplate


FpyCmd._fields = ["namespace", "name", "cmd_template"]


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
    

