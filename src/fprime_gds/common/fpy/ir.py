from dataclasses import dataclass

from fprime_gds.common.fpy.bytecode.types import DirectiveOpcode
from fprime_gds.common.fpy.parser import AstCondition
from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime.common.models.serialize.type_base import BaseType


Register = int


@dataclass
class ConstDirective:
    id: DirectiveOpcode
    args: list[tuple[str, FppType]]


@dataclass
class ConstCmd:
    template: CmdTemplate
    args: list[BaseType]


@dataclass
class If:
    conditional: AstCondition
    if_true: "Body"
    if_false: "If" | "Body" | None


Statement = ConstCmd | ConstDirective | If


@dataclass
class Body:
    stmts: list[Statement]
