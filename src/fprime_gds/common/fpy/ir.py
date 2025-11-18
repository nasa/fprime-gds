from __future__ import annotations
from dataclasses import dataclass
from typing import Union
from fprime_gds.common.fpy.bytecode.directives import (
    Directive,
    GotoDirective,
    IfDirective,
)
from fprime_gds.common.fpy.error import BackendError
from fprime_gds.common.fpy.syntax import Ast
from fprime_gds.common.fpy.types import (
    MAX_DIRECTIVES_COUNT,
    MAX_STACK_SIZE,
    CompileState,
    is_instance_compat,
)


class Ir:
    pass


class IrLabel(Ir):
    def __init__(self, node: Ast, label: str):
        super().__init__()
        self.label = f"{node.id}.{label}"

    def __hash__(self):
        return hash(self.label)

    def __eq__(self, value):
        return isinstance(value, IrLabel) and value.label == self.label


@dataclass(frozen=True, unsafe_hash=True)
class IrGoto(Ir):
    label: Union[str, IrLabel]


@dataclass(frozen=True, unsafe_hash=True)
class IrIf(Ir):
    goto_if_false_label: Union[str, IrLabel]


class IrPass:
    def run(
        self, ir: list[Directive | Ir], state: CompileState
    ) -> Union[list[Directive | Ir], BackendError]:
        pass


class ResolveLabels(IrPass):
    def run(self, ir, state: CompileState):
        labels: dict[str, int] = {}
        idx = 0
        dirs = []
        for dir in ir:
            if is_instance_compat(dir, IrLabel):
                if dir.label in labels:
                    return BackendError(f"Label {dir.label} already exists")
                labels[dir.label] = idx
                continue
            idx += 1

        # okay, we have all the labels
        for dir in ir:
            if is_instance_compat(dir, IrLabel):
                # drop these from the result
                continue
            elif is_instance_compat(dir, IrGoto):
                label = (
                    dir.label.label
                    if is_instance_compat(dir.label, IrLabel)
                    else dir.label
                )
                if label not in labels:
                    return BackendError(f"Unknown label {label}")
                dirs.append(GotoDirective(labels[label]))
            elif is_instance_compat(dir, IrIf):
                label = (
                    dir.goto_if_false_label.label
                    if is_instance_compat(dir.goto_if_false_label, IrLabel)
                    else dir.goto_if_false_label
                )
                if label not in labels:
                    return BackendError(f"Unknown label {label}")
                dirs.append(IfDirective(labels[label]))
            else:
                dirs.append(dir)

        return dirs


class FinalChecks(IrPass):
    def run(self, ir, state):
        if state.lvar_array_size_bytes > MAX_STACK_SIZE:
            return BackendError(
                f"Stack size too big (expected less than {MAX_STACK_SIZE}, had {state.lvar_array_size_bytes})"
            )
        if len(ir) > MAX_DIRECTIVES_COUNT:
            return BackendError(
                f"Too many directives in sequence (expected less than {MAX_DIRECTIVES_COUNT}, had {len(ir)})"
            )

        for dir in ir:
            # double check we've got rid of all the IR
            assert is_instance_compat(dir, Directive), dir

        return ir
