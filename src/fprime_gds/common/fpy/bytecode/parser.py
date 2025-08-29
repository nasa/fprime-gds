from __future__ import annotations
from dataclasses import dataclass, field, fields
from pathlib import Path
from pprint import pprint
from typing import Union
from lark.indenter import PythonIndenter
from lark import Lark, Transformer, ast_utils, v_args
from lark.tree import Meta

fpy_grammar_str = (Path(__file__).parent / "grammar.lark").read_text()

input_text = None


def parse(text: str):
    parser = Lark(
        fpy_grammar_str,
        start="input",
        parser="lalr",
        postlex=PythonIndenter(),
        propagate_positions=True,
        maybe_placeholders=True,
    )

    global input_text
    input_text = text
    tree = parser.parse(text, on_error=lambda x: print("Error"))
    transformed = FpyBytecodeTransformer().transform(tree)
    return transformed


@dataclass
class Ast:
    meta: Meta = field(repr=False)
    id: int = field(init=False, repr=False, default=None)
    node_text: str = field(init=False, repr=False, default=None)

    def __post_init__(self):
        if not hasattr(self.meta, "start_pos"):
            self.node_text = ""
            return
        self.node_text = (
            input_text[self.meta.start_pos : self.meta.end_pos]
            .replace("\n", " ")
            .strip()
        )

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return f"{self.__class__.__name__}({self.node_text})"


@dataclass
class AstGotoTagStmt(Ast):
    tag: str


@dataclass
class AstBinaryRegOpCall:
    op: str
    lhs: int
    rhs: int
    res: int


@dataclass
class AstUnaryRegOpCall:
    op: str
    src: int
    res: int


@dataclass
class AstGotoCall(Ast):
    dest: str | int


@dataclass
class AstWaitRelCall(Ast):
    seconds: int
    useconds: int


@dataclass
class AstWaitAbsCall(Ast):
    time_context: int
    time_base: int
    seconds: int
    useconds: int


@dataclass
class AstSetSerRegCall(Ast):
    ser_reg: int
    value: list[int] | None


@dataclass
class AstIfCall(Ast):
    conditional_reg: int
    false_goto: int | str


@dataclass
class AstNoOpCall(Ast):
    pass


@dataclass
class AstGetTlmCall(Ast):
    value_reg: int
    time_reg: int
    chan_id: int


@dataclass
class AstGetPrmCall(Ast):
    value_reg: int
    prm_id: int


@dataclass
class AstCmdCall(Ast):
    opcode: int
    value: list[int] | None


@dataclass
class AstDeserSerRegCall(Ast):
    src_ser_reg: int
    src_offset: int
    dest_reg: int
    deser_size: int


@dataclass
class AstSetRegCall(Ast):
    reg: int
    value: int


@dataclass
class AstExitCall(Ast):
    success: bool


AstDirStmt = Union[
    AstWaitRelCall
    , AstWaitAbsCall
    , AstGotoCall
    , AstBinaryRegOpCall
    , AstUnaryRegOpCall
    , AstSetSerRegCall
    , AstSetRegCall
    , AstIfCall
    , AstNoOpCall
    , AstGetPrmCall
    , AstGetTlmCall
    , AstCmdCall
    , AstDeserSerRegCall
    , AstExitCall
]

AstStmt = Union[AstGotoTagStmt, AstDirStmt]


@dataclass
class AstBody(Ast):
    stmts: list[AstStmt]


for cls in Ast.__subclasses__():
    cls.__hash__ = Ast.__hash__
    # cls.__repr__ = Ast.__repr__


@v_args(meta=False, inline=False)
def as_list(self, tree):
    return list(tree)


def no_inline_or_meta(type):
    @v_args(meta=False, inline=False)
    def wrapper(self, tree):
        return type(tree)

    return wrapper


def no_inline(type):
    @v_args(meta=True, inline=False)
    def wrapper(self, meta, tree):
        return type(meta, tree)

    return wrapper


def no_meta(type):
    @v_args(meta=False, inline=True)
    def wrapper(self, tree):
        return type(tree)

    return wrapper


def handle_str(meta, s: str):
    return s.strip("'").strip('"')


@v_args(meta=True, inline=True)
class FpyBytecodeTransformer(Transformer):
    input = no_inline(AstBody)
    goto_tag_stmt = AstGotoTagStmt
    binary_reg_op_call = AstBinaryRegOpCall
    unary_reg_op_call = AstUnaryRegOpCall
    goto_call = AstGotoCall
    wait_rel_call = AstWaitRelCall
    wait_abs_call = AstWaitAbsCall
    set_ser_reg_call = AstSetSerRegCall
    if_call = AstIfCall
    no_op_call = AstNoOpCall
    get_tlm_call = AstGetTlmCall
    get_prm_call = AstGetPrmCall
    cmd_call = AstCmdCall
    deser_ser_reg_call = AstDeserSerRegCall
    set_reg_call = AstSetRegCall
    exit_call = AstExitCall
    binary_reg_op = no_meta(str)
    name = no_meta(str)
    NAME = str
    DEC_NUMBER = int
    FLOAT_NUMBER = float
    COMPARISON_OP = str
    STRING = handle_str
    CONST_TRUE = lambda a, b: True
    CONST_FALSE = lambda a, b: False
