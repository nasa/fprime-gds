from dataclasses import dataclass, field, fields
from pathlib import Path
from pprint import pprint
from typing import Any
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
class Expr(Ast):
    value: Ast


@dataclass()
class Call(Ast):
    func: list[Ast]
    args: list[Ast]


@dataclass()
class Name(Ast):
    value: str


@dataclass()
class Var(Ast):
    value: Ast


@dataclass()
class Attr(Ast):
    value: Ast
    name: str


@dataclass()
class If(Ast):
    condition: Ast
    body: ScopedBody
    elifs: Ast
    els: ScopedBody | None


@dataclass()
class String(Ast):
    value: str


@dataclass()
class Assign(Ast):
    variable: Var
    value: Ast


@dataclass()
class AnnAssign(Ast):
    variable: Var
    ann_type: Var
    value: Ast


@dataclass()
class Elif(Ast):
    condition: Ast
    body: ScopedBody


@dataclass()
class Pass(Ast):
    pass


@dataclass()
class FuncDef(Ast):
    name: str
    parameters: list[Ast]
    return_type: Ast
    body: ScopedBody


@v_args(meta=False, inline=False)
def as_list(self, tree):
    return list(tree)


@v_args(meta=True, inline=False)
def as_body(self, meta, tree):
    return ScopedBody(meta, tree)


@v_args(meta=True, inline=True)
class FpyTransformer(Transformer):
    const_true = lambda self, _: True
    const_false = lambda self, _: False
    NAME = str
    # an actual string literal
    STRING = str

    input = as_body
    expr_stmt = Expr
    funccall = Call
    name = Name
    var = Var
    getattr = Attr
    if_stmt = If
    suite = as_body
    arguments = as_list
    # the string ast node
    string = String
    assign = Assign
    annassign = AnnAssign

    elifs = as_list
    elif_ = Elif
    pass_stmt = Pass
    funcdef = FuncDef
