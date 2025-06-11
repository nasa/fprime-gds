from dataclasses import dataclass

from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime.common.models.serialize.type_base import BaseType


Register = int


@dataclass
class ConstCmd:
    template: CmdTemplate
    args: list[BaseType]


@dataclass
class ConstDirective:
    id: int
    args: list[BaseType]

@dataclass
class If:
    conditional: Register
    if_true: "Body"
    if_false: "If" | "Body" | None


Statement = ConstCmd | ConstDirective | If


@dataclass
class Body:
    stmts: list[Statement]
