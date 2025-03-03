from dataclasses import dataclass
from fprime.common.models.serialize.type_base import BaseType
from fprime.common.models.serialize.time_type import TimeType
from enum import Enum


class SeqDirectiveId(Enum):
    WAIT_ABS = 0
    WAIT_REL = 1


@dataclass
class SeqDirectiveTemplate:
    id: SeqDirectiveId
    name: str
    # name, desc, arg type
    args: list[tuple[str, str, type[BaseType]]]


seq_directive_templates = [
    SeqDirectiveTemplate(
        SeqDirectiveId.WAIT_ABS,
        "sleep_abs",
        [("time", "The absolute time to wait until", TimeType)],
    ),
    SeqDirectiveTemplate(
        SeqDirectiveId.WAIT_REL,
        "sleep_rel",
        [("timeDelta", "The time to wait for", TimeType)],
    ),
]

# convert it to a fqn: directive dict
seq_directive_name_dict = {
    seq_dir.name: seq_dir
    for seq_dir in seq_directive_templates
}
