from ast import Pass
from collections import defaultdict
from dataclasses import dataclass, field, fields
from types import NoneType
from typing import TypeVar, overload

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
    Argument,
    AstBoolean,
    AstComparison,
    AstInfixOp,
    AstNumber,
    AstReference,
    AstString,
    AstTypedAssign,
    Ast,
    Literal,
    AstScopedBody,
    AstIf,
    AstAssign,
    AstFuncCall,
    AstName,
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


# mock type, used as a placeholder for a func/op that takes any numeric
# type
class AnyNumericType:
    pass


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
    args: list[tuple[str, type[BaseType]]] | None
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
    callables: dict[str, list[FpyCallable]] = field(repr=False, default_factory=dict)
    infix_operators: dict[str, list[FpyCallable]] = field(
        repr=False, default_factory=dict
    )

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

    def lookup_ref(self, node: AstReference, error_if_none=False) -> list[FpyReference]:
        refs = self.resolved_references.get(node.id, [])
        if len(refs) == 0 and error_if_none:
            self.errors.append(CompileException("Unknown reference", node))
        return refs

    T = TypeVar("T")

    def lookup_ref_with_type(
        self, node: AstReference, type: type[T], error_if_none=True
    ) -> list[T]:
        refs = self.lookup_ref(node, error_if_none)

        if len(refs) > 0:
            refs_of_type = [ref for ref in refs if isinstance(ref, type)]
            if len(refs_of_type) == 0 and error_if_none:
                self.errors.append(
                    CompileException(
                        f"Expecting reference to {type}, found {refs}", node
                    )
                )

            refs = refs_of_type

        return refs

    def lookup_single_ref_with_type(
        self, node: AstReference, type: type[T], dont_create_errors=False
    ) -> T | None:
        refs = self.lookup_ref_with_type(node, type, not dont_create_errors)
        if len(refs) > 1:
            if not dont_create_errors:
                self.errors.append(
                    CompileException(f"Ambiguous reference to {type}, found {refs}")
                )
            return None
        return refs[0]

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

    if isinstance(literal, AstString) and not issubclass(typ, StringType):
        return None

    if isinstance(literal, AstBoolean) and typ != BoolType:
        return None

    if isinstance(literal, AstNumber) and typ not in NUMERIC_TYPES:
        return None

    if isinstance(literal.value, float) and typ not in FLOAT_TYPES:
        return None

    if isinstance(literal.value, int) and typ not in INTEGER_TYPES:
        return None

    return typ(literal.value)


def check_reference_type(ref: FpyReference, typ: type[BaseType]) -> bool:
    if isinstance(ref, ChTemplate):
        return ref.ch_type_obj == typ
    if isinstance(ref, PrmTemplate):
        return ref.prm_type_obj == typ
    if isinstance(ref, BaseType):
        return type(ref) == typ
    if isinstance(ref, FpyCallable):
        return ref.return_type == typ
    if isinstance(ref, type):
        return ref == typ
    assert False, ref


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

    def run(self, body: AstScopedBody, state: CompileState):
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

    def run(self, body: AstScopedBody, state: CompileState):
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

    def visit_AstReference(self, parent, node: AstReference, state: CompileState):
        fqn = ".".join(name.value for name in node.names)

        tlm = state.tlms.get(fqn, None)
        prm = state.prms.get(fqn, None)
        const = state.consts.get(fqn, None)
        type = state.types.get(fqn, None)
        callables = state.callables.get(fqn, [])
        var = state.lookup_variable(fqn, node)

        possible_resolutions = callables + [tlm, prm, const, type, var]

        possible_resolutions = [ref for ref in possible_resolutions if ref is not None]

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
        if isinstance(parent, (AstScopedBody, NoneType)):
            state.parent_scope[node.id] = parent.id if parent is not None else None
        else:
            state.parent_scope[node.id] = state.parent_scope[parent.id]

    def visit_AstScopedBody(self, parent, node: AstScopedBody, state: CompileState):
        state.variable_tables[node.id] = {}
        state.parent_scope[node.id] = (
            state.parent_scope[parent.id] if parent is not None else None
        )


class CreateVariables(CompilePass):

    def visit_AstTypedAssign(self, parent, node: AstTypedAssign, state: CompileState):
        var_type = state.lookup_single_ref_with_type(node.var_type, type)
        if not var_type:
            # error is generated in the above method
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

    def visit_AstAssign(self, parent, node: AstAssign, state: CompileState):
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

    def check_args_compatible(
        self,
        node: Ast,
        node_args: list[Argument],
        func: FpyCallable,
        state: CompileState,
    ) -> tuple[dict[str, BaseType], CompileException]:
        if len(node_args) < len(func.args):
            return dict(), CompileException(
                f"Missing arguments (expected {len(func.args)} found {len(node_args)})",
                node,
            )
        if len(node_args) > len(func.args):
            return dict(), CompileException(
                f"Too many arguments (expected {len(func.args)} found {len(node_args)})",
                node,
            )

        arg_values: dict[str, BaseType] = {}

        for value_node, arg_template in zip(node_args, func.args):
            arg_name, arg_type = arg_template
            # check type of value matches expected type of template

            if isinstance(value_node, Literal):
                try:
                    coerced_value = coerce_literal_to_type(value_node, arg_type)
                except BaseException as e:
                    return dict(), CompileException(
                        f"For arg {arg_name}: literal {type(value_node)} cannot be converted to {arg_type} ({e})",
                        value_node,
                    )
                if coerced_value is None:
                    return dict(), CompileException(
                        f"For arg {arg_name}: literal {type(value_node)} cannot be converted to {arg_type}",
                        value_node,
                    )
                # literal value, compatible with expected type
                state.values[value_node.id] = coerced_value
                arg_values[arg_name] = coerced_value
                continue

            elif isinstance(value_node, AstReference):
                refs = state.lookup_ref(value_node)
                if len(refs) == 0:
                    return dict(), CompileException(
                        f"For arg {arg_name}: Unknown reference", value_node
                    )
                # only reference that is allowed is a const rn
                const_refs = [r for r in refs if isinstance(r, BaseType)]
                if len(const_refs) == 0:
                    return dict(), CompileException(
                        f"For arg {arg_name}: Expecting reference to BaseType, found {refs}",
                        value_node,
                    )
                if len(const_refs) > 1:
                    return dict(), CompileException(
                        f"For arg {arg_name}: Ambiguous reference to BaseType, found {const_refs}",
                        value_node,
                    )
                const_ref = const_refs[0]
                state.values[value_node.id] = const_ref
                arg_values[arg_name] = const_ref
                continue

            # otherwise, it's a callable
            assert isinstance(value_node, AstFuncCall), value_node

            existing_value = state.values.get(value_node.id, None)
            # we should have already figured out the value of this node
            assert existing_value is not None

            if not isinstance(existing_value, arg_type):
                return dict(), CompileException(
                    f"For arg {arg_name}: {existing_value} cannot be converted to {arg_type}"
                )

            arg_values[arg_name] = existing_value

        # got thru all args successfully

        return arg_values, None

    def visit_AstComparison(self, parent, node: AstComparison, state: CompileState):
        # op exists at syntax level, coding error if no exist
        funcs = state.infix_operators[node.op.value]
        self.resolve_polymorphic_funcs(node, [node.lhs, node.rhs], funcs, state)

    def resolve_polymorphic_funcs(
        self,
        node: Ast,
        node_args: list[Argument],
        funcs: list[FpyCallable],
        state: CompileState,
    ):
        if len(funcs) == 0:
            # error is generated in lookup
            return

        # resolve polymorphic funcs by trying each possible func

        # tuples of all funcs that we checked, their arg vals if they were compatible, and exception if not
        checked_funcs: list[tuple[FpyCallable, list[BaseType], CompileException]] = []
        # tuples of all matching funcs, arg vals
        matching_funcs: list[tuple[FpyCallable, list[BaseType]]] = []

        for func in funcs:
            arg_values, exception = self.check_args_compatible(
                node, node_args, func, state
            )
            checked_funcs.append((func, arg_values, exception))
            if exception is None:
                matching_funcs.append((func, arg_values))

        if len(matching_funcs) == 0:
            state.errors.append(f"No matching function. Tried {checked_funcs}")
            return

        if len(matching_funcs) > 1:
            state.errors.append(f"Ambiguous functions {matching_funcs}")
            return

        func, arg_values = matching_funcs[0]

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

    def visit_AstFuncCall(self, parent, node: AstFuncCall, state: CompileState):
        funcs = state.lookup_ref_with_type(node.func, FpyCallable)
        self.resolve_polymorphic_funcs(
            node, node.args if node.args else [], funcs, state
        )


class CheckComparisons(CompilePass):
    def visit_AstComparison(self, parent, node: AstComparison, state: CompileState):
        # what are we comparing?
        stmts = []
        if isinstance(node.lhs, AstReference):
            ref = state.lookup_ref(node.lhs)


class CheckIfStatements(CompilePass):
    def visit_AstIf(self, parent, node: AstIf, state: CompileState):
        # so we want to make sure that the condition converts to a bool
        # print(node)
        pass


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
    type_name_dict["bool"] = BoolType
    type_name_dict["str"] = StringType

    callable_name_dict = defaultdict(list)
    for name, cmd in cmd_name_dict.items():
        cmd: CmdTemplate
        args = []
        for arg_name, _, arg_type in cmd.arguments:
            args.append((arg_name, arg_type))
        callable_name_dict[name].append(FpyCallable(None, args, cmd))

    infix_callable_name_dict = defaultdict(list)

    numeric_infix_ops = ["<", ">", "<=", ">=", "==", "!="]
    for op in numeric_infix_ops:
        infix_callable_name_dict[op].append(
            FpyCallable(
                BoolType, [("lhs", AnyNumericType), ("rhs", AnyNumericType)], None
            )
        )

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

        callable_name_dict[name].append(FpyCallable(typ, args, None))

    state = CompileState(
        tlms=ch_name_dict,
        prms=prm_name_dict,
        consts=enum_consts,
        callables=callable_name_dict,
        types=type_name_dict,
        infix_operators=infix_callable_name_dict,
    )
    return state


def compile(body: AstScopedBody, dictionary: str) -> list[StatementData]:
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
        CheckComparisons(),
        CheckIfStatements(),
    ]
    for compile_pass in passes:
        compile_pass.run(body, state)
        print(state)
        for error in state.errors:
            print(error)
            raise error
