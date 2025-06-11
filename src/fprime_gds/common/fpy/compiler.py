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
    Boolean,
    EnumConst,
    FuncName,
    String,
    TypeName,
    TypedAssign,
    Ast,
    Literal,
    ScopedBody,
    If,
    Assign,
    FuncCall,
    Name,
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


# named variables can be tlm chans, prms, callables, or directly referenced consts (usually enums)
FpyVariable = ChTemplate | PrmTemplate | FpyCallable | BaseType


@dataclass
class CompileState:
    tlms: dict[str, ChTemplate] = field(repr=False, default_factory=dict)
    prms: dict[str, PrmTemplate] = field(repr=False, default_factory=dict)
    consts: dict[str, BaseType] = field(repr=False, default_factory=dict)
    types: dict[str, type[BaseType]] = field(repr=False, default_factory=dict)
    callables: dict[str, FpyCallable] = field(repr=False, default_factory=dict)

    resolved_types: dict[int, type[BaseType]] = field(default_factory=dict)

    resolved_callables: dict[int, FpyCallable] = field(default_factory=dict)
    resolved_enum_consts: dict[int, BaseType] = field(default_factory=dict)

    variable_tables: dict[int, dict[str, type[BaseType]]] = field(default_factory=dict)
    """a table containing all function definitions and variables, for each scopedbody. keys are ast node uid"""

    parent_scope: dict[int, int | None] = field(default_factory=dict)
    """a dict tracking the parent scope of each ast node. keys are ast node uid, values are uid of parent scopedbody"""

    references: dict[int, FpyVariable] = field(default_factory=dict)
    """a dict mapping ast node uid to which symbol it references"""

    errors: list[CompileException] = field(default_factory=list)

    def lookup_variable(self, var: str, at_node: Ast) -> type[BaseType] | None:
        # first check if there's a symbol defined in the sequence
        parent = self.parent_scope[at_node.id]
        while parent is not None:
            table = self.variable_tables[parent]
            if var in table:
                return table[var]

            parent = self.parent_scope[parent]

        return None

        # # check for the symbol in all the global symbol tables
        # callable = self.callables.get(symbol, None)
        # if callable is not None:
        #     return callable
        # const = self.consts.get(symbol, None)
        # if const is not None:
        #     return const
        # tlm = self.tlms.get(symbol, None)
        # if tlm is not None:
        #     return tlm
        # prm = self.prms.get(symbol, None)
        # if prm is not None:
        #     return prm

        # return None

    def add_variable(self, var_name: str, var_type: type[BaseType], at_node: Ast):
        parent_scope = self.parent_scope[at_node.id]
        self.variable_tables[parent_scope][var_name] = var_type

    def get_node_fprime_type(self, node: Ast) -> type[BaseType] | None:
        if isinstance(node, FuncCall):
            callable = self.resolved_callables.get(node.func.id, None)
            if callable is None:
                return None

            return callable.return_type

        if isinstance(node, EnumConst):
            return self.resolved_enum_consts.get(node.id)

        if isinstance(node, Name):
            return self.lookup_variable(node.value, node)

        if isinstance(node, String):
            return StringType

        if isinstance(node, Boolean):
            return BoolType

        # if isinstance(node,)
        # doesn't work for numeric... one numeric node can be multiple fprime types


        


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


class ResolveEnumConsts(CompilePass):
    def visit_EnumConst(self, parent, node: EnumConst, state: CompileState):
        fqn = ".".join(name.value for name in node.names)
        if fqn not in state.consts:
            state.errors.append(CompileException(f"Unknown enum const {fqn}", node))
            return
        state.resolved_enum_consts[node.id] = state.consts[fqn]


class ResolveTypeNames(CompilePass):
    def visit_TypeName(self, parent, node: TypeName, state: CompileState):
        fqn = ".".join(name.value for name in node.names)
        if fqn not in state.types:
            state.errors.append(CompileException(f"Unknown type {fqn}", node))
            return
        state.resolved_types[node.id] = state.types[fqn]


class ResolveFuncNames(CompilePass):
    def visit_FuncName(self, parent, node: FuncName, state: CompileState):
        fqn = ".".join(name.value for name in node.names)
        if fqn not in state.callables:
            state.errors.append(CompileException(f"Unknown function {fqn}", node))
            return
        state.resolved_callables[node.id] = state.callables[fqn]


class CreateScopes(TopDownCompilePass):

    def visit_default(self, parent, node, state):
        if isinstance(parent, (ScopedBody, NoneType)):
            state.parent_scope[node.id] = parent.id if parent is not None else None
        else:
            state.parent_scope[node.id] = state.parent_scope[parent.id]

    def visit_ScopedBody(self, parent, node: ScopedBody, state: CompileState):
        state.variable_tables[node.id] = {}
        state.parent_scope[node.id] = (
            state.parent_scope[parent.id] if parent is not None else None
        )


class CreateVariables(CompilePass):

    def visit_TypedAssign(self, parent, node: TypedAssign, state: CompileState):
        var_type = state.resolved_types.get(node.var_type, None)
        if var_type is None:
            state.errors.append(CompileException(f"Unknown type {node.var_type}", node))
            return

        # okay, type exists

        # okay we're assigning a variable to something, with an annotation. look it up in the symbol table
        existing_variable = state.lookup_variable(node.var.value, node.var)
        if not existing_variable:
            # new var. put it in the table under this scope
            state.add_variable(
                node.var.value,
                var_type,
                node,
            )
        else:
            # already existing. check the type is consistent
            if existing_variable != var_type:
                state.errors.append(
                    CompileException(
                        f"Inconsistent type. Was {existing_variable}, but annotation was {var_type}",
                        node.var_type,
                    )
                )
                return
            # okay, type is consistent.

    def visit_Assign(self, parent, node: Assign, state: CompileState):
        # okay we're assigning a variable to something, without an annotation. look it up in the variable table
        existing = state.lookup_variable(node.variable.value, node.variable)
        if not existing:
            # error because this isn't an annotated assignment. right now all assignments must be annotated
            state.errors.append(
                CompileException(
                    "Must provide a type annotation for new variables", node.variable
                )
            )


class TypeCheckCalls(CompilePass):
    def visit_Call(self, parent, node: FuncCall, state: CompileState):
        func = state.resolved_callables.get(node.func.id, None)
        if func is None:
            state.errors.append(CompileException("Unknown function", node.func))
            return

        node_arg_count = len(node.args) if node.args is not None else 0
        if node_arg_count != len(func.args):
            if len(node.args) < len(func.args):
                state.errors.append(CompileException("Missing arguments", node))
                return
            state.errors.append(CompileException("Too many arguments", node))
            return

        if node_arg_count == 0:
            # no args. good 2 go
            return

        for value, arg_template in zip(node.args, func.args):
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

            if isinstance(value, FuncCall):
                # a call's type is defined by its function
                func = state.references.get(value.func.id, None)
            else:
                # some ast node. get what type it references
                func = state.references.get(value.id, None)

            if func is None:
                state.errors.append(
                    CompileException("Invalid syntax (unknown reference)", value)
                )
                return

            if isinstance(func, FpyCallable):
                existing_value_type = func.return_type
            elif isinstance(func, BaseType):
                existing_value_type = type(func)
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
        types=type_name_dict,
    )
    return state


def compile(body: ScopedBody, dictionary: str) -> list[StatementData]:
    state = get_base_compile_state(dictionary)
    passes: list[CompilePass] = [
        AssignIds(),
        # resolve everything defined in the dict
        ResolveEnumConsts(),
        ResolveFuncNames(),
        ResolveTypeNames(),
        CreateScopes(),
        CreateVariables(),
        # resolve everything defined in the seq (vars, funcs, etc)
        ResolveSymbols(),
        TypeCheckCalls(),
    ]
    for compile_pass in passes:
        compile_pass.run(body, state)
        print(state)
        for error in state.errors:
            raise error
