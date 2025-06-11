from ast import Pass
from dataclasses import dataclass, field, fields
from types import NoneType
from typing import TypeVar

from fprime_gds.common.data_types.cmd_data import CmdData
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
    Number,
    Reference,
    String,
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
UNSIGNED_INTEGER_TYPES = (
    U32Type,
    U16Type,
    U64Type,
    U8Type,
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


FpyBuiltin = int


@dataclass
class FpyCallable:
    return_type: type[BaseType] | None
    args: list[tuple[str, type[BaseType]]]
    action: CmdTemplate | FpyBuiltin | None


# named variables can be tlm chans, prms, callables, or directly referenced consts (usually enums)
@dataclass
class FpyVariable:
    type: type[BaseType]


FpyReference = ChTemplate | PrmTemplate | BaseType | FpyCallable | type[BaseType]


@dataclass
class CompileState:
    tlms: dict[str, ChTemplate] = field(repr=False, default_factory=dict)
    prms: dict[str, PrmTemplate] = field(repr=False, default_factory=dict)
    consts: dict[str, BaseType] = field(repr=False, default_factory=dict)
    types: dict[str, type[BaseType]] = field(repr=False, default_factory=dict)
    callables: dict[str, FpyCallable] = field(repr=False, default_factory=dict)

    resolved_references: dict[int, list[FpyReference]] = field(default_factory=dict)

    values: dict[int, BaseType] = field(default_factory=dict)

    commands: dict[int, tuple[CmdTemplate, list[BaseType]]] = field(
        default_factory=dict
    )

    directives: dict[int, tuple[FpyBuiltin, list[BaseType]]] = field(
        default_factory=dict
    )

    variable_tables: dict[int, dict[str, FpyVariable]] = field(default_factory=dict)
    """a table containing all function definitions and variables, for each scopedbody. keys are ast node uid"""

    parent_scope: dict[int, int | None] = field(default_factory=dict)
    """a dict tracking the parent scope of each ast node. keys are ast node uid, values are uid of parent scopedbody"""

    errors: list[CompileException] = field(default_factory=list)

    T = TypeVar("T")

    def lookup_reference(self, node: Ast, interpret_as: type[T]) -> T | None:
        possible_refs = self.resolved_references.get(node.id, None)
        if possible_refs is None:
            return None

        for interpretation in possible_refs:
            if isinstance(interpretation, interpret_as):
                return interpretation

        return None

    def lookup_variable(self, var: str, at_node: Ast) -> FpyVariable | None:
        # first check if there's a symbol defined in the sequence
        parent = self.parent_scope[at_node.id]
        while parent is not None:
            table = self.variable_tables[parent]
            if var in table:
                return table[var]

            parent = self.parent_scope[parent]

        return None

    def add_variable(self, var_name: str, var_type: type[BaseType], at_node: Ast):
        parent_scope = self.parent_scope[at_node.id]
        self.variable_tables[parent_scope][var_name] = FpyVariable(var_type)


def coerce_literal_to_type(literal: Literal, typ: type[BaseType]) -> BaseType | None:
    if isinstance(literal, String) and typ == StringType:
        return StringType(literal.value)

    if isinstance(literal, Boolean) and typ == BoolType:
        return BoolType(literal.value)

    if isinstance(literal, Number) and typ in NUMERIC_TYPES:
        if isinstance(literal.value, float) and typ in FLOAT_TYPES:
            return typ(literal.value)

        if isinstance(literal.value, float) and typ in FLOAT_TYPES:
            return typ(literal.value)

        if isinstance(literal.value, int) and typ in INTEGER_TYPES:
            return typ(literal.value)

    return None


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


class ResolveReferences(CompilePass):

    def __init__(self, fail_if_unknown: bool = False):
        self.fail_if_unknown = fail_if_unknown

    def visit_Reference(self, parent, node: Reference, state: CompileState):
        fqn = ".".join(name.value for name in node.names)

        tlm = state.tlms.get(fqn, None)
        prm = state.prms.get(fqn, None)
        const = state.consts.get(fqn, None)
        type = state.types.get(fqn, None)
        callable = state.callables.get(fqn, None)
        var = state.lookup_variable(fqn, node)

        possible_resolutions = (tlm, prm, const, type, callable, var)
        possible_resolutions = list(
            ref for ref in possible_resolutions if ref is not None
        )

        if node.id in state.resolved_references:
            # already resolved previously
            # make sure we're resolving it the same way now
            assert (
                state.resolved_references[node.id] == possible_resolutions
            ), state.resolved_references[node.id]
            # okay all good, same resolution
            return

        if len(possible_resolutions) == 0:
            if self.fail_if_unknown:
                state.errors.append(CompileException(f"Unknown reference {fqn}", node))
            return

        state.resolved_references[node.id] = possible_resolutions


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
        var_type = state.lookup_reference(node.var_type, type)
        if var_type is None:
            state.errors.append(CompileException(f"Unknown type", node.var_type))
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
            if existing_variable.type != var_type:
                state.errors.append(
                    CompileException(
                        f"Inconsistent type. Was {existing_variable.type}, but annotation was {var_type}",
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


class CheckCalls(CompilePass):
    def visit_FuncCall(self, parent, node: FuncCall, state: CompileState):
        func = state.lookup_reference(node.func, FpyCallable)
        if func is None:
            state.errors.append(CompileException("Unknown function", node.func))
            return

        node_args = node.args if node.args is not None else []

        if len(node_args) != len(func.args):
            if len(node_args) < len(func.args):
                state.errors.append(
                    CompileException(
                        f"Missing arguments (expected {len(func.args)} found {len(node_args)})",
                        node,
                    )
                )
                return
            state.errors.append(
                CompileException(
                    f"Too many arguments (expected {len(func.args)} found {len(node_args)})",
                    node,
                )
            )
            return

        arg_values: dict[str, BaseType] = {}

        for value_node, arg_template in zip(node_args, func.args):
            arg_name, arg_type = arg_template
            # check type of value matches expected type of template

            if isinstance(value_node, Literal):
                try:
                    coerced_value = coerce_literal_to_type(value_node, arg_type)
                except BaseException as e:
                    state.errors.append(
                        CompileException(
                            f"For arg {arg_name}: literal {type(value_node)} cannot be converted to {arg_type} ({e})",
                            value_node,
                        )
                    )
                    return
                if coerced_value is None:
                    state.errors.append(
                        CompileException(
                            f"For arg {arg_name}: literal {type(value_node)} cannot be converted to {arg_type}",
                            value_node,
                        )
                    )
                    return
                # literal value, compatible with expected type
                state.values[value_node.id] = coerced_value
                arg_values[arg_name] = coerced_value
                continue

            elif isinstance(value_node, Reference):
                # only reference that is allowed is a const rn
                ref = state.lookup_reference(value_node, BaseType)
                if ref is None:
                    state.errors.append(
                        CompileException(f"Unknown constant reference", value_node)
                    )
                    return
                state.values[value_node.id] = ref
                arg_values[arg_name] = ref
                continue

            # otherwise, it's a callable
            assert isinstance(value_node, FuncCall), value_node

            existing_value = state.values.get(value_node.id, None)
            # we should have already figured out the value of this node
            assert existing_value is not None

            if not isinstance(existing_value, arg_type):
                state.errors.append(
                    CompileException(
                        f"For arg {arg_name}: {existing_value} cannot be converted to {arg_type}"
                    )
                )
                return

            arg_values[arg_name] = existing_value

        assert len(arg_values) == len(func.args), len(arg_values)

        # if it has a return type, it doesn't have an action
        # if it has an action, it doesn't have a return type
        assert (func.return_type is None and func.action is not None) or (
            func.return_type is not None and func.action is None
        ), (func.return_type, func.action)

        # okay we have all arg values

        # if it is a type ctor call, instantiate it
        if func.return_type is not None:
            if issubclass(func.return_type, SerializableType):
                # pass in args as a dict
                instance = func.return_type()
                instance._val = arg_values
                state.values[node.id] = instance

            elif issubclass(func.return_type, ArrayType):
                state.values[node.id] = func.return_type(tuple(arg_values.values()))

            elif func.return_type == TimeType:
                state.values[node.id] = TimeType(**arg_values)

            else:
                assert False, func.return_type

            return

        # if it is an action, save it in state
        if func.action is not None:
            if isinstance(func.action, CmdTemplate):
                state.commands[node.id] = (func.action, list(arg_values.values()))
                return

            assert isinstance(func.action, FpyBuiltin)
            state.directives[node.id] = (func.action, list(arg_values.values()))
            return


class CheckIfStatements(CompilePass):
    def visit_If(self, parent, node: If, state: CompileState):
        print(node.condition)


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
        CreateScopes(),
        ResolveReferences(),
        CreateVariables(),
        # now that variables have been defined, try resolving references
        # again and fail if anything isn't found
        ResolveReferences(fail_if_unknown=True),
        # resolve everything defined in the seq (vars, funcs, etc)
        CheckCalls(),
        CheckIfStatements(),
    ]
    for compile_pass in passes:
        compile_pass.run(body, state)
        print(state)
        for error in state.errors:
            raise error
