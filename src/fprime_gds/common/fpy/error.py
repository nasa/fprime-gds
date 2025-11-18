# compiler debug flag
from dataclasses import dataclass
import traceback
from typing import Any

from lark import LarkError, Token, UnexpectedToken
from lark.indenter import DedentError

# assigned in compiler_main
file_name = None
# assigned in compiler_main
debug = False
# assigned in text_to_ast
input_text = None
# assigned in text_to_ast
input_lines = None


# the number of lines to show around a compiler error
COMPILER_ERROR_CONTEXT_LINE_COUNT = 1


@dataclass
class CompileError:
    msg: str
    node: Any = None

    def __post_init__(self):
        self.stack_trace = "\n".join(traceback.format_stack(limit=8)[:-1])

    def __repr__(self):

        stack_trace_optional = f"{self.stack_trace}\n" if debug else ""
        file_name_optional = (
            f"{file_name}" if file_name is not None else "<unknown file>"
        )

        if self.node is None:
            return f"{stack_trace_optional}{file_name_optional}: {self.msg}"

        meta = self.node if isinstance(self.node, Token) else self.node.meta

        source_start_line = meta.line - 1 - COMPILER_ERROR_CONTEXT_LINE_COUNT
        source_start_line = max(0, source_start_line)
        source_end_line = meta.end_line - 1 + COMPILER_ERROR_CONTEXT_LINE_COUNT
        source_end_line = min(len(input_lines), source_end_line)

        # this is the list of all the src lines we will display
        source_to_display: list[str] = input_lines[
            source_start_line : source_end_line + 1
        ]

        # reserve this much space for the line numbers
        line_number_space = 4 if source_end_line < 998 else 8

        # prefix all the lines with the prefix and line number
        # right justified line number, then a |, then the line
        source_to_display = [
            str(source_start_line + line_idx + 1).rjust(line_number_space)
            + " | "
            + line
            for line_idx, line in enumerate(source_to_display)
        ]

        node_lines = meta.end_line - meta.line

        if node_lines > 1:
            source_to_display_str = "\n".join(source_to_display)
            # it's a multiline node. don't try to highlight the whole thing
            # just print the err and the offending text
            return f"{stack_trace_optional}{file_name_optional}:{meta.line}-{meta.end_line} {self.msg}\n{source_to_display_str}"

        node_start_line_in_ctx = meta.line - 1 - source_start_line
        error_highlight = " " * (meta.column - 1 + line_number_space + 3) + "^" * (
            meta.end_column - meta.column
        )
        source_to_display.insert(node_start_line_in_ctx + 1, error_highlight)
        result = f"{stack_trace_optional}{file_name_optional}:{meta.line} {self.msg}\n"
        result += "\n".join(source_to_display)

        return result

@dataclass
class BackendError:
    msg: str


def handle_lark_error(err):
    assert isinstance(err, LarkError), err
    if isinstance(err, UnexpectedToken):
        print(str(CompileError("Invalid syntax", err.token)))
    elif isinstance(err, DedentError):
        print(str(CompileError(err.args[0])))
    exit(1)
