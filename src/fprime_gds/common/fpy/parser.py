from dataclasses import dataclass, field, fields
from pathlib import Path
from pprint import pprint
from typing import Literal as TypingLiteral
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


@dataclass()
class Ast:
    meta: Meta = field(repr=False)
    id: int = field(init=False, repr=False, default=None)


@dataclass()
class ScopedBody(Ast):
    stmts: list[Ast]


@dataclass()
class Name(Ast):
    value: str


@dataclass()
class String(Ast):
    value: str


@dataclass
class Number(Ast):
    value: int | float


@dataclass
class Boolean(Ast):
    value: TypingLiteral[True] | TypingLiteral[False]


Literal = String | Number | Boolean


@dataclass
class Reference(Ast):
    names: list[Name]


@dataclass()
class FuncCall(Ast):
    func: Reference
    args: list["Argument"]


Argument = FuncCall | Reference | Literal


@dataclass
class Condition(Ast):
    value: Ast


@dataclass
class Elif(Ast):
    condition: Condition
    body: list[Ast]


@dataclass
class Elifs(Ast):
    cases: list[Elif]


@dataclass()
class If(Ast):
    condition: Condition
    body: list[Ast]
    elifs: Elifs
    els: list[Ast] | None


AssignValue = Literal | Reference


@dataclass()
class Assign(Ast):
    variable: Name
    value: AssignValue


@dataclass()
class TypedAssign(Ast):
    var: Name
    var_type: Reference
    value: AssignValue


@dataclass()
class Pass(Ast):
    pass


@dataclass
class Or(Ast):
    values: list[Ast]


@dataclass
class And(Ast):
    values: list[Ast]


@dataclass
class Not(Ast):
    values: list[Ast]


@dataclass
class Comparison(Ast):
    values: list[Ast]

@dataclass
class ComparisonOp(Ast):
    value: Ast


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
class FpyTransformer(Transformer):
    input = no_inline(ScopedBody)
    pass_stmt = Pass

    reference = no_inline(Reference)
    typed_assign = TypedAssign
    assign = Assign

    if_stmt = If
    elifs = no_inline(Elifs)
    elif_ = Elif
    suite = no_inline_or_meta(list)
    condition = no_inline(Condition)
    or_test = no_inline(Or)
    and_test = no_inline(And)
    not_test = no_inline(Not)
    comparison = no_inline(Comparison)
    comp_op = ComparisonOp

    func_call = FuncCall
    arguments = no_inline_or_meta(list)

    string = String
    number = Number
    boolean = Boolean
    name = Name

    NAME = str
    DEC_NUMBER = int
    FLOAT_NUMBER = float
    COMPARISON_OP = str
