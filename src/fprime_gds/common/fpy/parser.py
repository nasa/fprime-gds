from dataclasses import dataclass, field, fields
from pprint import pprint
from typing import Any
from lark.indenter import PythonIndenter
from lark import Lark, Transformer, ast_utils, v_args
from lark.tree import Meta


def parse_fpy(text: str):
    parser = Lark.open_from_package(
        "fprime_gds.common.fpy",
        "grammar.lark",
        postlex=PythonIndenter(),
        start="file_input",
        parser="lalr",
    )

    tree = parser.parse(text, on_error=lambda x: print("Error"))
    transformed = FpyTransformer().transform(tree)
    pprint(transformed)
    return transformed


def flatten_ast_node(cls):
    datacls = dataclass(cls)

    def ast_node_ctor(self, value: list):
        for idx, member in enumerate(fields(datacls)):
            setattr(self, member.name, value[idx])

    datacls.__init__ = ast_node_ctor

    return datacls


@dataclass
class _Ast:
    meta: Meta = field(repr=False)


@dataclass
class Root(_Ast):
    stmts: list[_Ast]


@dataclass
class Expr(_Ast):
    value: _Ast


@dataclass
class Call(_Ast):
    func: list[_Ast]
    args: list[_Ast]


@dataclass
class Name(_Ast):
    value: str


@dataclass
class Var(_Ast):
    value: _Ast


@dataclass
class Attr(_Ast):
    value: _Ast
    name: str


@dataclass
class Body(_Ast):
    stmts: list[_Ast]


@dataclass
class If(_Ast):
    condition: _Ast
    body: _Ast
    elifs: _Ast
    els: _Ast


@dataclass
class String(_Ast):
    value: str


@dataclass
class Assign(_Ast):
    variable: Var
    value: _Ast


@dataclass
class Elif(_Ast):
    condition: _Ast
    body: _Ast


@v_args(meta=False, inline=False)
def as_list(self, tree):
    return list(tree)


@v_args(meta=True, inline=True)
class FpyTransformer(Transformer):
    const_true = lambda self, _: True
    const_false = lambda self, _: False
    NAME = str
    # an actual string literal
    STRING = str

    file_input = Root
    expr_stmt = Expr
    funccall = Call
    name = Name
    var = Var
    getattr = Attr
    if_stmt = If
    suite = as_list
    arguments = as_list
    # the string ast node
    string = String
    assign = Assign

    elifs = as_list
    elif_ = Elif
