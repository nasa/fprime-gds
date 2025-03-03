from dataclasses import dataclass
from fprime.common.models.serialize.type_base import BaseType


@dataclass
class StatementTemplate:
    opcode: int
    name: str
    args: list[type[BaseType]]

@dataclass
class StatementData:
    template: StatementTemplate
    arg_values: list[BaseType]