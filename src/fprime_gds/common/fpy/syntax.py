from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal as TypingLiteral, Union
from lark import Lark, LarkError, Transformer, v_args
from lark.tree import Meta

from fprime_gds.common.fpy.error import handle_lark_error



@dataclass
class Ast:
    meta: Meta = field(repr=False)
    id: int = field(init=False, repr=False, default=None)

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, value):
        if not isinstance(value, Ast):
            return False
        assert self.id is not None
        return self.id == value.id


@dataclass
class AstVar(Ast):
    var: str


@dataclass()
class AstString(Ast):
    value: str


@dataclass
class AstNumber(Ast):
    value: int | float


@dataclass
class AstBoolean(Ast):
    value: TypingLiteral[True] | TypingLiteral[False]


AstLiteral = Union[AstString, AstNumber, AstBoolean]


@dataclass
class AstGetAttr(Ast):
    parent: "AstExpr"
    attr: str


@dataclass
class AstGetItem(Ast):
    parent: "AstExpr"
    item: AstExpr


@dataclass
class AstFuncCall(Ast):
    func: "AstExpr"
    args: list["AstExpr"] | None


@dataclass
class AstPass(Ast):
    pass # ha ha


@dataclass
class AstEllipsis(Ast): ... # this is my way of being funny


@dataclass
class AstBinaryOp(Ast):
    lhs: AstExpr
    op: str
    rhs: AstExpr


@dataclass
class AstUnaryOp(Ast):
    op: str
    val: AstExpr


AstOp = Union[AstBinaryOp, AstUnaryOp]

AstReference = Union[AstGetAttr, AstGetItem, AstVar]
AstExpr = Union[AstFuncCall, AstLiteral, AstReference, AstOp]


@dataclass
class AstAssign(Ast):
    lhs: AstExpr
    type_ann: AstExpr | None
    rhs: AstExpr


@dataclass
class AstElif(Ast):
    condition: AstExpr
    body: "AstBody"


@dataclass
class AstElifs(Ast):
    cases: list[AstElif]


@dataclass()
class AstIf(Ast):
    condition: AstExpr
    body: "AstBody"
    elifs: AstElifs | None
    els: Union["AstBody", None]


@dataclass
class AstFor(Ast):
    loop_var: AstVar
    loop_var_type: AstExpr
    lower_bound: AstExpr
    upper_bound: AstExpr
    body: AstBody

@dataclass
class AstWhile(Ast):
    condition: AstExpr
    body: AstBody

@dataclass
class AstAssert(Ast):
    condition: AstExpr
    exit_code: Union[AstExpr, None]

@dataclass
class AstBreak(Ast):
    pass

@dataclass
class AstContinue(Ast):
    pass

AstStmt = Union[AstExpr, AstAssign, AstPass, AstIf, AstElif, AstFor, AstBreak, AstContinue, AstWhile, AstAssert, AstEllipsis]
AstStmtWithExpr = Union[AstExpr, AstAssign, AstIf, AstElif, AstFor, AstWhile, AstAssert]
AstNodeWithSideEffects = Union[AstFuncCall, AstAssign, AstIf, AstElif, AstFor, AstWhile, AstAssert, AstBreak, AstContinue]


@dataclass
class AstBody(Ast):
    stmts: list[AstStmt]


@dataclass
class AstScopedBody(Ast):
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


def handle_assign(meta, args):
    # for some stupid reason i cannot get this to work without
    # this hacky function
    value = args[-1]
    var = args[0]
    if len(args) > 2:
        type = args[1]
    else:
        type = None
    return AstAssign(meta, var, type, value)

def handle_assert(meta, args):
    condition = args[0]
    if len(args) > 1:
        exit_code = args[1]
    else:
        exit_code = None
    return AstAssert(meta, condition, exit_code)


@v_args(meta=True, inline=True)
class FpyTransformer(Transformer):
    input = no_inline(AstScopedBody)
    pass_stmt = AstPass

    assign = no_inline(handle_assign)

    for_stmt = AstFor
    while_stmt = AstWhile
    scoped_body = no_inline(AstScopedBody)
    break_stmt = AstBreak
    continue_stmt = AstContinue

    assert_stmt = no_inline(handle_assert)

    if_stmt = AstIf
    elifs = no_inline(AstElifs)
    elif_ = AstElif
    body = no_inline(AstBody)
    binary_op = AstBinaryOp
    unary_op = AstUnaryOp

    func_call = AstFuncCall
    arguments = no_inline_or_meta(list)

    string = AstString
    number = AstNumber
    boolean = AstBoolean
    name = no_meta(str)
    get_attr = AstGetAttr
    get_item = AstGetItem
    var = AstVar
    ellipsis = AstEllipsis

    NAME = str
    DEC_NUMBER = int
    FLOAT_NUMBER = float
    COMPARISON_OP = str
    STRING = handle_str
    CONST_TRUE = lambda a, b: True
    CONST_FALSE = lambda a, b: False
    ADD_OP: str
    SUB_OP: str
    DIV_OP: str
    MUL_OP: str
    FLOOR_DIV_OP: str
    MOD_OP: str
    POW_OP: str
