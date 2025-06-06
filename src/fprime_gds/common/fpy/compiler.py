from ast import Pass
from dataclasses import dataclass, field, fields
from types import NoneType

from fprime_gds.common.fpy.bytecode.types import (
    FPY_DIRECTIVES,
    StatementData,
    StatementTemplate,
)
from fprime_gds.common.loaders.ch_json_loader import ChJsonLoader
from fprime_gds.common.loaders.cmd_json_loader import CmdJsonLoader
from fprime_gds.common.loaders.prm_json_loader import PrmJsonLoader
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime_gds.common.templates.prm_template import PrmTemplate
from fprime.common.models.serialize.time_type import TimeType
from fprime.common.models.serialize.enum_type import EnumType, REPRESENTATION_TYPE_MAP
from fprime.common.models.serialize.serializable_type import SerializableType
from fprime.common.models.serialize.array_type import ArrayType
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
    Literal,
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

NUMERIC_TYPES = (
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
INTEGER_TYPES = (
    U32Type,
    U16Type,
    U64Type,
    U8Type,
    I16Type,
    I32Type,
    I64Type,
    I8Type,
)
FLOAT_TYPES = (
    F32Type,
    F64Type,
)


class CompileException(BaseException):
    def __init__(self, msg, node: Ast):
        self.msg = msg
        self.node = node

    def __str__(self):
        return f"At line {self.node.meta.line} {self.node}: {self.msg}"


FpyBuiltin = str


@dataclass
class FpyCallable:
    return_type: type[BaseType] | None
    args: list[tuple[str, type[BaseType]]]
    action: CmdTemplate | FpyBuiltin | None


# named symbols can be tlm chans, prms, callables, or directly referenced consts (usually enums)
FpySymbol = ChTemplate | PrmTemplate | FpyCallable | BaseType


@dataclass
class CompileState:
    tlms: dict[str, ChTemplate] = field(repr=False, default_factory=dict)
    prms: dict[str, PrmTemplate] = field(repr=False, default_factory=dict)
    consts: dict[str, BaseType] = field(repr=False, default_factory=dict)
    callables: dict[str, FpyCallable] = field(repr=False, default_factory=dict)

    symbol_tables: dict[int, dict[str, FpySymbol]] = field(default_factory=dict)
    """a table containing all function definitions and variables, for each scopedbody. keys are ast node uid"""

    parent_scope: dict[int, int | None] = field(default_factory=dict)
    """a dict tracking the parent scope of each ast node. keys are ast node uid, values are uid of parent scopedbody"""

    references: dict[int, FpySymbol] = field(default_factory=dict)
    """a dict mapping ast node uid to which symbol it references"""

    types: dict[int, type[BaseType]] = field(default_factory=dict)
    """a dict mapping ast node uid to which BaseType it resolves to"""

    errors: list[CompileException] = field(default_factory=list)

    def lookup_symbol(self, symbol: str, at_node: Ast) -> FpySymbol | None:
        # first check if there's a symbol defined in the sequence
        parent = self.parent_scope[at_node.id]
        while parent is not None:
            table = self.symbol_tables[parent]
            if symbol in table:
                return table[symbol]

            parent = self.parent_scope[parent]

        # check for the symbol in all the global symbol tables
        callable = self.callables.get(symbol, None)
        if callable is not None:
            return callable
        const = self.consts.get(symbol, None)
        if const is not None:
            return const
        tlm = self.tlms.get(symbol, None)
        if tlm is not None:
            return tlm
        prm = self.prms.get(symbol, None)
        if prm is not None:
            return prm

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
            node.variable.value, str
        ):
            state.errors.append(
                CompileException(
                    "Left hand side of assignment must be a simple variable",
                    node.variable,
                )
            )
            return

        if not isinstance(node.ann_type, Var) or not isinstance(
            node.ann_type.value, str
        ):
            state.errors.append(
                CompileException(
                    "Type annotation must be a simple type name", node.ann_type
                )
            )
            return

        # okay we're assigning a variable to something, with an annotation. look it up in the symbol table
        existing_symbol = state.lookup_symbol(node.variable.value, node.variable)
        if not existing_symbol:
            # new symbol. put it in the table under this scope
            sym_type = state.types.get(node.ann_type.value, None)
            if sym_type is None:
                state.errors.append(
                    CompileException(f"Unknown type {node.ann_type.value}", node)
                )
                return
            state.add_symbol(
                node.variable.value,
                sym_type,
                node,
            )
        else:
            # already existing. check the type is consistent
            new_type = state.types[node.ann_type.value]
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
            node.variable.value, str
        ):
            state.errors.append(
                CompileException(
                    "Left hand side of assignment must be a simple variable",
                    node.variable,
                )
            )
            return

        # okay we're assigning a variable to something, without an annotation. look it up in the symbol table
        existing = state.lookup_symbol(node.variable.value, node.variable)
        if not existing:
            # error because this isn't an annotated assignment. right now all assignments must be annotated
            state.errors.append(
                CompileException(
                    "Must provide a type annotation for new variables", node.variable
                )
            )


class ResolveReferences(TopDownCompilePass):
    def visit_Attr(self, parent, node: Attr, state: CompileState):
        def get_fqn(attr: Attr):
            if isinstance(attr.value, Var):
                return attr.value.value + "." + attr.name
            return get_fqn(attr.value) + "." + attr.name

        fqn = get_fqn(node)
        symbol = state.lookup_symbol(fqn, node)
        if symbol is not None:
            state.references[node.id] = symbol
            print(fqn, symbol)


class TypeCheckCalls(CompilePass):
    def visit_Call(self, parent, node: Call, state: CompileState):
        ref = state.references.get(node.func.id, None)
        if ref is None:
            state.errors.append(CompileException("Unknown reference", node))
            return

        if not isinstance(ref, FpyCallable):
            # calling something that isn't callable
            state.errors.append(CompileException("Invalid syntax (not callable)", node))
            return

        node_arg_count = len(node.args) if node.args is not None else 0
        if node_arg_count != len(ref.args):
            if len(node.args) < len(ref.args):
                state.errors.append(CompileException("Missing arguments", node))
                return
            state.errors.append(CompileException("Too many arguments", node))
            return

        if node_arg_count == 0:
            # no args. good 2 go
            return

        for value, arg_template in zip(node.args, ref.args):
            arg_name, arg_type = arg_template
            # check type of value matches expected type of template

            if isinstance(value, Literal):
                if not is_literal_compatible(value.value, arg_type):
                    state.errors.append(
                    CompileException(
                        f"Wrong type for arg {arg_name} ({type(value)} cannot be converted to {arg_type})",
                        node,
                    )
                    )
                    return
                # literal value, compatible with expected type
                continue

            if isinstance(value, Call):
                # a call's type is defined by its function
                ref = state.references.get(value.func.id, None)
            else:
                # some ast node. get what type it references
                ref = state.references.get(value.id, None)

            if ref is None:
                state.errors.append(
                    CompileException("Invalid syntax (unknown reference)", value)
                )
                return

            if isinstance(ref, FpyCallable):
                existing_value_type = ref.return_type
            elif isinstance(ref, BaseType):
                existing_value_type = type(ref)
            else:
                state.errors.append(
                    CompileException("Invalid syntax (invalid argument)", value)
                )
                return

            if existing_value_type != arg_type:
                state.errors.append(
                    CompileException(
                        f"Wrong type for arg {arg_name} (expected {arg_type} found {existing_value_type})",
                        node,
                    )
                )
                return


def is_literal_compatible(literal, typ):
    if isinstance(literal, int) and issubclass(typ, NUMERIC_TYPES):
        # fine to coerce an int to a float
        return True
    if isinstance(literal, float) and issubclass(typ, FLOAT_TYPES):
        # can't convert float to int
        return True
    if isinstance(literal, str) and typ == StringType:
        return True
    if isinstance(literal, bool) and typ == BoolType:
        return True

    return False


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
    type_name_dict.update(prm_json_dict_loader.parsed_types)

    enum_consts: dict[str, BaseType] = {}

    for name, typ in type_name_dict.items():
        if issubclass(typ, EnumType):
            for enum_const_name, val in typ.ENUM_DICT.items():
                enum_consts[name + "." + enum_const_name] = typ(enum_const_name)

    # insert the implicit types into the dict
    type_name_dict["Fw.Time"] = TimeType
    for typ in NUMERIC_TYPES:
        type_name_dict[typ.get_canonical_name()] = typ
        print(typ, typ.get_canonical_name())
    type_name_dict["bool"] = BoolType
    type_name_dict["str"] = StringType

    callable_name_dict = {}
    for name, cmd in cmd_name_dict.items():
        cmd: CmdTemplate
        args = []
        for arg_name, _, arg_type in cmd.arguments:
            args.append((arg_name, arg_type))
        callable_name_dict[name] = FpyCallable(None, args, cmd)

    for name, typ in type_name_dict.items():
        args = []
        if issubclass(typ, SerializableType):
            for arg_name, arg_type, _, _ in typ.MEMBER_LIST:
                args.append((arg_name, arg_type))
        elif issubclass(typ, ArrayType):
            for i in range(0, typ.LENGTH):
                args.append(("e" + str(i), typ.MEMBER_TYPE))
        elif issubclass(typ, TimeType):
            args.append(("time_base", U16Type))
            args.append(("time_context", U8Type))
            args.append(("seconds", U32Type))
            args.append(("useconds", U32Type))
        else:
            # bool, enum, string or numeric type
            # none of these have callable ctors
            continue

        callable_name_dict[name] = FpyCallable(typ, args, None)

    state = CompileState(
        tlms=ch_name_dict,
        prms=prm_name_dict,
        consts=enum_consts,
        callables=callable_name_dict,
    )
    return state


def compile(body: ScopedBody, dictionary: str) -> list[StatementData]:
    state = get_base_compile_state(dictionary)
    passes: list[CompilePass] = [
        AssignIds(),
        CreateScopes(),
        CreateSymbolTables(),
        ResolveReferences(),
        TypeCheckCalls(),
    ]
    for compile_pass in passes:
        compile_pass.run(body, state)
        print(state)
        for error in state.errors:
            raise error
