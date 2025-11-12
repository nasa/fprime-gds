from __future__ import annotations
from dataclasses import dataclass, field
from typing import Iterator, List, Literal as TypingLiteral, Union
from lark import Token, Transformer, v_args
from lark.tree import Meta
from lark.lark import PostLex
from lark.indenter import DedentError
from decimal import Decimal


class PythonIndenter(PostLex):
    # from lark, but slightly modified to fix a bug
    """This is a postlexer that "injects" indent/dedent tokens based on indentation.

    It keeps track of the current indentation, as well as the current level of parentheses.
    Inside parentheses, the indentation is ignored, and no indent/dedent tokens get generated.
    See also: the ``postlex`` option in `Lark`.
    """
    paren_level: int
    indent_level: List[int]
    NL_type = "_NEWLINE"
    OPEN_PAREN_types = ["LPAR", "LSQB", "LBRACE"]
    CLOSE_PAREN_types = ["RPAR", "RSQB", "RBRACE"]
    INDENT_type = "_INDENT"
    DEDENT_type = "_DEDENT"
    tab_len = 8

    def __init__(self) -> None:
        self.paren_level = 0
        self.indent_level = [0]
        assert self.tab_len > 0

    def handle_NL(self, token: Token) -> Iterator[Token]:
        if self.paren_level > 0:
            return

        yield token

        if not "\n" in token:
            return

        indent_str = token.rsplit("\n", 1)[1]  # Tabs and spaces
        indent = indent_str.count(" ") + indent_str.count("\t") * self.tab_len

        if indent > self.indent_level[-1]:
            self.indent_level.append(indent)
            yield Token.new_borrow_pos(self.INDENT_type, indent_str, token)
        else:
            while indent < self.indent_level[-1]:
                self.indent_level.pop()
                yield Token.new_borrow_pos(self.DEDENT_type, indent_str, token)

            if indent != self.indent_level[-1]:
                raise DedentError(
                    "Unexpected dedent to column %s. Expected dedent to %s"
                    % (indent, self.indent_level[-1])
                )

    def _process(self, stream):
        for token in stream:
            if token.type == self.NL_type:
                yield from self.handle_NL(token)
            else:
                yield token

            if token.type in self.OPEN_PAREN_types:
                self.paren_level += 1
            elif token.type in self.CLOSE_PAREN_types:
                self.paren_level -= 1
                assert self.paren_level >= 0

        while len(self.indent_level) > 1:
            self.indent_level.pop()
            yield Token(self.DEDENT_type, "")

        assert self.indent_level == [0], self.indent_level

    def process(self, stream):
        self.paren_level = 0
        self.indent_level = [0]
        return self._process(stream)


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
    value: int | Decimal


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
    pass  # ha ha
@dataclass
class AstBinaryOp(Ast):
    lhs: AstExpr
    op: str
    rhs: AstExpr


@dataclass
class AstUnaryOp(Ast):
    op: str
    val: AstExpr


@dataclass
class AstRange(Ast):
    lower_bound: AstExpr
    op: str
    upper_bound: AstExpr


AstOp = Union[AstBinaryOp, AstUnaryOp]

AstReference = Union[AstGetAttr, AstGetItem, AstVar]
AstExpr = Union[AstFuncCall, AstLiteral, AstReference, AstOp, AstRange]


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
    range: AstExpr
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


AstStmt = Union[
    AstExpr,
    AstAssign,
    AstPass,
    AstIf,
    AstElif,
    AstFor,
    AstBreak,
    AstContinue,
    AstWhile,
    AstAssert,
]
AstStmtWithExpr = Union[AstExpr, AstAssign, AstIf, AstElif, AstFor, AstWhile, AstAssert]
AstNodeWithSideEffects = Union[
    AstFuncCall,
    AstAssign,
    AstIf,
    AstElif,
    AstFor,
    AstWhile,
    AstAssert,
    AstBreak,
    AstContinue,
]


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
    range = AstRange

    NAME = str
    DEC_NUMBER = int
    FLOAT_NUMBER = Decimal
    COMPARISON_OP = str
    RANGE_OP = str
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
