from ast import Pass
from dataclasses import dataclass, field, fields
from types import NoneType

from fprime_gds.common.fpy.bytecode.types import (
    FPY_DIRECTIVES,
    StatementData,
    StatementTemplate,
    StatementType,
)
from fprime_gds.common.loaders.ch_json_loader import ChJsonLoader
from fprime_gds.common.loaders.cmd_json_loader import CmdJsonLoader
from fprime_gds.common.loaders.prm_json_loader import PrmJsonLoader
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.prm_template import PrmTemplate
from fprime.common.models.serialize.time_type import TimeType
from fprime.common.models.serialize.numerical_types import (
    U32Type,
    U16Type,
    U64Type,
    U8Type,
    I16Type,
    I32Type,
    I64Type,
    I8Type,
    F32Type,
    F64Type,
)
from fprime.common.models.serialize.string_type import StringType
from fprime.common.models.serialize.bool_type import BoolType
from fprime_gds.common.fpy.parser import (
    AnnAssign,
    Ast,
    ScopedBody,
    Expr,
    FuncDef,
    If,
    Assign,
    Call,
    Name,
    Var,
    Attr,
)
from fprime.common.models.serialize.type_base import BaseType


class CompileException(BaseException):
    def __init__(self, msg, node: Ast):
        self.msg = msg
        self.node = node

    def __str__(self):
        return f"At line {self.node.meta.line}: {self.msg}"


FpySymbol = type[BaseType]


@dataclass
class CompileState:
    symbol_tables: dict[int, dict[str, FpySymbol]]
    """a table containing all function definitions and variables, for each scopedbody. keys are ast node uid"""

    parent_scope: dict[int, int | None]
    """a dict tracking the parent scope of each ast node. keys are ast node uid, values are uid of parent scopedbody"""

    tlms: dict[str, ChTemplate] = field(repr=False)
    prms: dict[str, PrmTemplate] = field(repr=False)
    stmts: dict[str, StatementTemplate] = field(repr=False)
    types: dict[str, type[BaseType]] = field(repr=False)

    errors: list[CompileException]

    def lookup_symbol(self, symbol: str, at_node: Ast) -> FpySymbol | None:
        parent = self.parent_scope[at_node.id]
        while parent is not None:
            table = self.symbol_tables[parent]
            if symbol in table:
                return table[symbol]

            parent = self.parent_scope[parent]
        return None

    def add_symbol(self, symbol_name: str, symbol_type: FpySymbol, at_node: Ast):
        parent_scope = self.parent_scope[at_node.id]
        self.symbol_tables[parent_scope][symbol_name] = symbol_type


class CompilePass:
    def _visit(self, parent: Ast | None, node: Ast, state: CompileState):
        self_type = type(self)
        custom_visit_name = "visit_" + type(node).__name__
        if hasattr(self_type, custom_visit_name):
            # call the custom function
            getattr(self_type, custom_visit_name)(self, parent, node, state)
        else:
            # call the default
            self.visit_default(parent, node, state)

    def visit_default(self, parent: Ast | None, node: Ast, state: CompileState):
        pass

    def run(self, body: ScopedBody, state: CompileState):
        def _descend(node: Ast):
            if not isinstance(node, Ast):
                return
            children = []
            for field in fields(node):
                field_val = getattr(node, field.name)
                if isinstance(field_val, list):
                    children.extend(field_val)
                else:
                    children.append(field_val)

            for child in children:
                if not isinstance(child, Ast):
                    continue
                _descend(child)
                self._visit(node, child, state)

        _descend(body)
        self._visit(None, body, state)


class TopDownCompilePass(CompilePass):

    def run(self, body: ScopedBody, state: CompileState):
        def _descend(node: Ast):
            if not isinstance(node, Ast):
                return
            children = []
            for field in fields(node):
                field_val = getattr(node, field.name)
                if isinstance(field_val, list):
                    children.extend(field_val)
                else:
                    children.append(field_val)

            for child in children:
                if not isinstance(child, Ast):
                    continue
                self._visit(node, child, state)
                _descend(child)

        self._visit(None, body, state)
        _descend(body)


class AssignIds(TopDownCompilePass):

    def __init__(self):
        self.next_id = 0

    def visit_default(self, parent, node, state):
        node.id = self.next_id
        self.next_id += 1


class CreateScopes(TopDownCompilePass):

    def visit_default(self, parent, node, state):
        if isinstance(parent, (ScopedBody, NoneType)):
            state.parent_scope[node.id] = parent.id if parent is not None else None
        else:
            state.parent_scope[node.id] = state.parent_scope[parent.id]

    def visit_ScopedBody(self, parent, node: ScopedBody, state: CompileState):
        state.symbol_tables[node.id] = {}
        state.parent_scope[node.id] = (
            state.parent_scope[parent.id] if parent is not None else None
        )


class CreateSymbolTables(TopDownCompilePass):

    def visit_AnnAssign(self, parent, node: AnnAssign, state: CompileState):
        if not isinstance(node.variable, Var) or not isinstance(
            node.variable.value, Name
        ):
            state.errors.append(
                CompileException(
                    "Left hand side of assignment must be a simple variable",
                    node.variable,
                )
            )
            return

        if not isinstance(node.ann_type, Var) or not isinstance(
            node.ann_type.value, Name
        ):
            state.errors.append(
                CompileException(
                    "Type annotation must be a simple type name", node.ann_type
                )
            )
            return

        # okay we're assigning a variable to something, with an annotation. look it up in the symbol table
        existing_symbol = state.lookup_symbol(node.variable.value.value, node.variable)
        if not existing_symbol:
            # new symbol. put it in the table under this scope
            sym_type = state.types.get(node.ann_type.value.value, None)
            if sym_type is None:
                state.errors.append(
                    CompileException(f"Unknown type {node.ann_type.value.value}", node)
                )
                return
            state.add_symbol(
                node.variable.value.value,
                sym_type,
                node,
            )
        else:
            # already existing. check the type is consistent
            new_type = state.types[node.ann_type.value.value]
            if existing_symbol != new_type:
                state.errors.append(
                    CompileException(
                        f"Inconsistent type. Was {existing_symbol}, but annotation was {new_type}",
                        node.ann_type,
                    )
                )
                return
            # okay, type is consistent.

    def visit_Assign(self, parent, node: Assign, state: CompileState):
        if not isinstance(node.variable, Var) or not isinstance(
            node.variable.value, Name
        ):
            state.errors.append(
                CompileException(
                    "Left hand side of assignment must be a simple variable",
                    node.variable,
                )
            )
            return

        # okay we're assigning a variable to something, without an annotation. look it up in the symbol table
        existing = state.lookup_symbol(node.variable.value.value, node.variable)
        if not existing:
            # error because this isn't an annotated assignment. right now all assignments must be annotated
            state.errors.append(
                CompileException(
                    "Must provide a type annotation for new variables", node.variable
                )
            )

class CompileBodies(CompilePass):
    def visit_ScopedBody(self, parent, node: ScopedBody, state: CompileState):
        for stmt in node.stmts:
            print(stmt)


def get_base_compile_state(dictionary: str) -> CompileState:
    cmd_json_dict_loader = CmdJsonLoader(dictionary)
    (cmd_id_dict, cmd_name_dict, versions) = cmd_json_dict_loader.construct_dicts(
        dictionary
    )

    ch_json_dict_loader = ChJsonLoader(dictionary)
    (ch_id_dict, ch_name_dict, versions) = ch_json_dict_loader.construct_dicts(
        dictionary
    )
    prm_json_dict_loader = PrmJsonLoader(dictionary)
    (prm_id_dict, prm_name_dict, versions) = prm_json_dict_loader.construct_dicts(
        dictionary
    )
    type_name_dict = cmd_json_dict_loader.parsed_types
    type_name_dict.update(ch_json_dict_loader.parsed_types)
    # insert the implicit types into the dict
    type_name_dict["Fw.Time"] = TimeType
    type_name_dict["U64"] = U64Type
    type_name_dict["U32"] = U32Type
    type_name_dict["U16"] = U16Type
    type_name_dict["U8"] = U8Type
    type_name_dict["I64"] = I64Type
    type_name_dict["I32"] = I32Type
    type_name_dict["I16"] = I16Type
    type_name_dict["I8"] = I8Type
    type_name_dict["F64"] = F64Type
    type_name_dict["F32"] = F32Type
    type_name_dict["bool"] = BoolType
    type_name_dict["str"] = StringType

    stmt_name_dict = {directive.name: directive for directive in FPY_DIRECTIVES}
    for cmd_template in cmd_name_dict.values():
        stmt_template = StatementTemplate(
            StatementType.CMD,
            cmd_template.opcode,
            cmd_template.get_full_name(),
            [arg[2] for arg in cmd_template.arguments],
        )
        stmt_name_dict[cmd_template.get_full_name()] = stmt_template

    state = CompileState(
        {},
        {},
        tlms=ch_name_dict,
        prms=prm_name_dict,
        stmts=stmt_name_dict,
        types=type_name_dict,
        errors=[],
    )
    return state


def compile(body: ScopedBody, dictionary: str) -> list[StatementData]:
    state = get_base_compile_state(dictionary)
    passes: list[CompilePass] = [AssignIds(), CreateScopes(), CreateSymbolTables(), CompileBodies()]
    for compile_pass in passes:
        compile_pass.run(body, state)
        for error in state.errors:
            raise error
