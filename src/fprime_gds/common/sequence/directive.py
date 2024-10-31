from dataclasses import dataclass
from fprime.common.models.serialize.string_type import StringType
from fprime.common.models.serialize.type_base import BaseType
from fprime.common.models.serialize.time_type import TimeType
from enum import Enum


class SeqDirectiveId(Enum):
    SLEEP_ABS = 0
    SLEEP_REL = 1


@dataclass
class SeqDirectiveTemplate:
    id: SeqDirectiveId
    namespace: str
    name: str
    # name, desc, arg type
    args: list[tuple[str, str, type[BaseType]]]


seq_directive_templates = [
    SeqDirectiveTemplate(
        SeqDirectiveId.SLEEP_ABS,
        "seq",
        "sleep_until",
        [("time", "The absolute time to sleep until", TimeType)],
    ),
    SeqDirectiveTemplate(
        SeqDirectiveId.SLEEP_REL,
        "seq",
        "sleep",
        [("timeDelta", "The time to sleep for", TimeType)],
    ),
]

# convert it to a fqn: directive dict
seq_directive_name_dict = {
    seq_dir.namespace + "." + seq_dir.name: seq_dir
    for seq_dir in seq_directive_templates
}
