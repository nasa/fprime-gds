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
class FuncName(Ast):
    names: list[Name]


@dataclass()
class FuncCall(Ast):
    func: FuncName
    args: list["Argument"]


@dataclass
class EnumConst(Ast):
    names: list[Name]


Argument = FuncCall | EnumConst | Literal


@dataclass
class Condition:
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


AssignValue = Literal | EnumConst


@dataclass()
class Assign(Ast):
    variable: Name
    value: AssignValue


@dataclass
class TypeName(Ast):
    names: list[Name]


@dataclass()
class TypedAssign(Ast):
    var: Name
    var_type: TypeName
    value: AssignValue


@dataclass()
class Pass(Ast):
    pass


@v_args(meta=False, inline=False)
def as_list(self, tree):
    return list(tree)


@v_args(meta=True, inline=False)
def as_scoped_body(self, meta, tree):
    return ScopedBody(meta, tree)


@v_args(meta=True, inline=False)
def as_type_name(self, meta, tree):
    return TypeName(meta, tree)


@v_args(meta=True, inline=False)
def as_func_name(self, meta, tree):
    return FuncName(meta, tree)


@v_args(meta=True, inline=False)
def as_enum_const(self, meta, tree):
    return EnumConst(meta, tree)


@v_args(meta=False, inline=True)
def as_str(self, value):
    return str(value)


@v_args(meta=True, inline=True)
class FpyTransformer(Transformer):
    input = as_scoped_body
    pass_stmt = Pass

    type_name = as_type_name
    typed_assign = TypedAssign
    assign = Assign

    if_stmt = If
    elifs = Elifs
    elif_ = Elif
    suite = as_list

    func_name = as_func_name
    func_call = FuncCall
    arguments = as_list
    enum_const = as_enum_const

    string = String
    number = Number
    boolean = Boolean
    name = Name

    NAME = str
    DEC_NUMBER = int
    FLOAT_NUMBER = float
