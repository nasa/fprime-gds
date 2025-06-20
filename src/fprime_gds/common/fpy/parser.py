from dataclasses import dataclass, field, fields
from pathlib import Path
from pprint import pprint
from typing import Literal as TypingLiteral, Union
from lark.indenter import PythonIndenter
from lark import Lark, Transformer, ast_utils, v_args
from lark.tree import Meta

fpy_grammar_str = (Path(__file__).parent / "grammar.lark").read_text()


def parse(text: str):
    parser = Lark(
        fpy_grammar_str,
        start="input",
        parser="lalr",
        postlex=PythonIndenter(),
        propagate_positions=True,
    )

    tree = parser.parse(text, on_error=lambda x: print("Error"))
    transformed = FpyTransformer().transform(tree)
    return transformed


def flatten_ast_node(cls):
    datacls = dataclass(cls)

    def ast_node_ctor(self, value: list):
        for idx, member in enumerate(fields(datacls)):
            setattr(self, member.name, value[idx])

    datacls.__init__ = ast_node_ctor

    return datacls


@dataclass
class Ast:
    meta: Meta = field(repr=False)
    id: int = field(init=False, repr=False, default=None)

    def __hash__(self):
        return hash(self.id)


@dataclass()
class AstName(Ast):
    value: str


@dataclass()
class AstString(Ast):
    value: str


@dataclass
class AstNumber(Ast):
    value: int | float


@dataclass
class AstBoolean(Ast):
    value: TypingLiteral[True] | TypingLiteral[False]


Literal = AstString | AstNumber | AstBoolean


@dataclass
class AstReference(Ast):
    names: list[AstName]


@dataclass
class AstInfixOp(Ast):
    value: str


@dataclass
class AstFuncCall(Ast):
    func: AstReference | AstInfixOp
    args: list["AstArgument"]


AstArgument = AstFuncCall | AstReference | Literal


AstAssignValue = Literal | AstReference


@dataclass()
class AstAssign(Ast):
    variable: AstName
    var_type: AstReference | None
    value: AstAssignValue


@dataclass()
class AstPass(Ast):
    pass


@dataclass
class AstComparison(Ast):
    lhs: AstArgument
    op: AstInfixOp
    rhs: AstArgument


@dataclass
class AstNot(Ast):
    value: Union["AstNot", AstComparison, AstArgument]


@dataclass
class AstAnd(Ast):
    values: list[AstNot | AstComparison | AstArgument]


@dataclass
class AstOr(Ast):
    values: list[AstAnd | AstNot | AstComparison | AstArgument]


AstCondition = AstOr | AstAnd | AstNot | AstComparison | AstArgument


AstStmt = Union[AstFuncCall, AstAssign, AstPass, "AstIf"]


@dataclass
class AstUnscopedBody(Ast):
    stmts: list[AstStmt]


@dataclass
class AstScopedBody(Ast):
    stmts: list[AstStmt]


@dataclass
class AstElif(Ast):
    condition: AstCondition
    body: AstUnscopedBody


@dataclass
class AstElifs(Ast):
    cases: list[AstElif]


@dataclass()
class AstIf(Ast):
    condition: AstCondition
    body: AstUnscopedBody
    elifs: AstElifs | None
    els: AstUnscopedBody | None


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


@v_args(meta=True, inline=True)
def infix_func(self, meta, lhs, op, rhs):
    return AstFuncCall(meta, op, [lhs, rhs])


@v_args(meta=True, inline=True)
class FpyTransformer(Transformer):
    input = no_inline(AstScopedBody)
    pass_stmt = AstPass

    reference = no_inline(AstReference)
    assign = AstAssign

    if_stmt = AstIf
    elifs = no_inline(AstElifs)
    elif_ = AstElif
    body = no_inline(AstUnscopedBody)
    or_test = no_inline(AstOr)
    and_test = no_inline(AstAnd)
    not_test = no_inline(AstNot)
    comparison = AstComparison
    comp_op = AstInfixOp

    func_call = AstFuncCall
    arguments = no_inline_or_meta(list)

    string = AstString
    number = AstNumber
    boolean = AstBoolean
    name = AstName

    NAME = str
    DEC_NUMBER = int
    FLOAT_NUMBER = float
    COMPARISON_OP = str
    CONST_TRUE = lambda a, b: True
    CONST_FALSE = lambda a, b: False
