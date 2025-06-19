from dataclasses import dataclass
from typing import Union

from fprime_gds.common.fpy.bytecode.types import DirectiveOpcode
from fprime_gds.common.fpy.parser import AstCondition
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime.common.models.serialize.type_base import BaseType as FppType

from fprime_gds.common.templates.prm_template import PrmTemplate


Register = str
Variable = str


@dataclass
class ConstDirective:
    id: DirectiveOpcode
    args: list[tuple[str, FppType]]


@dataclass
class If:
    conditional: AstCondition
    if_true: "Body"
    if_false: Union["If", "Body", None]


Statement = ConstDirective | If


@dataclass
class Body:
    stmts: list[Statement]


@dataclass
class ValueToRegister:
    value: ChTemplate | PrmTemplate | FppType
    register: Register