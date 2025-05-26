from dataclasses import dataclass, fields
from pprint import pprint
from typing import Any
from lark.indenter import PythonIndenter
from lark import Lark, Transformer


def parse_fpy(text: str):
    parser = Lark.open_from_package(
        "fprime_gds.common.fpy",
        "grammar.lark",
        postlex=PythonIndenter(),
        start="file_input",
        parser="lalr",
    )

    tree = parser.parse(text, on_error=lambda x: print("Error"))
    print(tree.pretty())
    pprint(FpyTransformer().transform(tree))


def flatten_ast_node(cls):
    datacls = dataclass(cls)

    def ast_node_ctor(self, value: list):
        for idx, member in enumerate(fields(datacls)):
            setattr(self, member.name, value[idx])

    datacls.__init__ = ast_node_ctor

    return datacls


@dataclass
class Root:
    stmts: list


@flatten_ast_node
class Expr:
    value: Any


@flatten_ast_node
class Call:
    func: list
    args: list


@flatten_ast_node
class Name:
    value: str


@flatten_ast_node
class Var:
    value: Any


@flatten_ast_node
class Attr:
    value: Any
    name: str


@dataclass
class Body:
    stmts: list


@flatten_ast_node
class If:
    condition: Any
    body: Any
    elifs: Any
    els: Any


@flatten_ast_node
class String:
    value: str


@flatten_ast_node
class Assign:
    assignment: Any


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
    suite = list
    arguments = list
    # the string ast node
    string = String
    assign_stmt = Assign
