from dataclasses import dataclass, field, fields
from pathlib import Path
from pprint import pprint
from typing import Literal as TypingLiteral, Union
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
    transformed = FpyTransformer().transform(tree)
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


AstLiteral = AstString | AstNumber | AstBoolean


@dataclass
class AstGetAttr(Ast):
    parent: "AstExpr"
    attr: str


@dataclass
class AstGetItem(Ast):
    parent: "AstExpr"
    item: AstNumber


@dataclass
class AstFuncCall(Ast):
    func: "AstExpr"
    args: list["AstExpr"] | None


@dataclass
class AstInfixOp(Ast):
    value: str


@dataclass()
class AstPass(Ast):
    pass


@dataclass
class AstComparison(Ast):
    lhs: "AstExpr"
    op: AstInfixOp
    rhs: "AstExpr"


@dataclass
class AstNot(Ast):
    value: "AstExpr"


@dataclass
class AstAnd(Ast):
    values: list["AstExpr"]


@dataclass
class AstOr(Ast):
    values: list["AstExpr"]


AstTest = AstOr | AstAnd | AstNot | AstComparison


AstExpr = Union[AstGetAttr, AstGetItem, AstFuncCall, AstTest, AstLiteral, AstVar]
AstAtomExpr = AstExpr
AstAtom = AstExpr


@dataclass
class AstAssign(Ast):
    variable: AstExpr
    var_type: AstExpr | None
    value: AstExpr


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


AstStmt = Union[AstExpr, AstAssign, AstPass, AstIf]


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


@v_args(meta=True, inline=True)
class FpyTransformer(Transformer):
    input = no_inline(AstBody)
    pass_stmt = AstPass

    assign = AstAssign

    if_stmt = AstIf
    elifs = no_inline(AstElifs)
    elif_ = AstElif
    body = no_inline(AstBody)
    or_test = no_inline(AstOr)
    and_test = no_inline(AstAnd)
    not_test = AstNot
    comparison = AstComparison
    comp_op = AstInfixOp

    func_call = AstFuncCall
    arguments = no_inline_or_meta(list)

    string = AstString
    number = AstNumber
    boolean = AstBoolean
    name = no_meta(str)
    get_attr = AstGetAttr
    get_item = AstGetItem
    var = AstVar

    NAME = str
    DEC_NUMBER = int
    FLOAT_NUMBER = float
    COMPARISON_OP = str
    CONST_TRUE = lambda a, b: True
    CONST_FALSE = lambda a, b: False
