from ast import Pass
from collections import defaultdict
from dataclasses import dataclass, field, fields
from enum import Enum
import traceback
from types import NoneType
from typing import TypeVar, Union

from fprime_gds.common.data_types.cmd_data import CmdData
from fprime_gds.common.fpy.bytecode.types import (
    FPY_DIRECTIVES,
    StatementData,
    StatementTemplate,
)
from fprime_gds.common.fpy.bytecode.directives import (
    SIGNED_INEQUALITY_DIRECTIVES,
    UNSIGNED_INEQUALITY_DIRECTIVES,
    AndDirective,
    CmdDirective,
    DeserLocalVar1Directive,
    DeserLocalVar2Directive,
    DeserLocalVar4Directive,
    DeserLocalVar8Directive,
    Directive,
    DirectiveOpcode,
    EqualDirective,
    GetPrmDirective,
    GetTlmDirective,
    IfDirective,
    NotDirective,
    NotEqualDirective,
    OrDirective,
    SetLocalVarDirective,
    SetRegDirective,
    WaitRelDirective,
)
from fprime_gds.common.fpy.ir import ConstDirective
from fprime_gds.common.loaders.ch_json_loader import ChJsonLoader
from fprime_gds.common.loaders.cmd_json_loader import CmdJsonLoader
from fprime_gds.common.loaders.prm_json_loader import PrmJsonLoader
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime_gds.common.templates.prm_template import PrmTemplate
from fprime.common.models.serialize.time_type import TimeType
from fprime.common.models.serialize.type_exceptions import TypeException
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
    AstAnd,
    AstArgument,
    AstBoolean,
    AstComparison,
    AstCondition,
    AstElif,
    AstInfixOp,
    AstNot,
    AstNumber,
    AstOr,
    AstReference,
    AstStmt,
    AstString,
    Ast,
    AstUnscopedBody,
    Literal,
    AstScopedBody,
    AstIf,
    AstAssign,
    AstFuncCall,
    AstName,
)
from fprime.common.models.serialize.type_base import BaseType as FppType

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
SIGNED_INTEGER_TYPES = (
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

FppTypeClass = type[FppType]


# mock type, used as a placeholder for a func/op that takes any numeric
# type
class AnyNumericType:
    pass


DISCARD_LVAR = -1


class CompileException(BaseException):
    def __init__(self, msg, node: Ast):
        self.msg = msg
        self.node = node
        self.stack_trace = "\n".join(traceback.format_stack(limit=6)[:-1])

    def __str__(self):
        return (
            f"{self.stack_trace}\nAt line {self.node.meta.line} {self.node}: {self.msg}"
        )


FpyGenericType = FppTypeClass | type[AnyNumericType]


@dataclass
class FpyCallable:
    return_type: FppTypeClass | None
    args: list[tuple[str, FpyGenericType]] | None


@dataclass
class FpyCmd(FpyCallable):
    cmd: CmdTemplate


@dataclass
class FpyBuiltin(FpyCallable):
    dir: type[Directive]


@dataclass
class FpyTypeCtor(FpyCallable):
    type: FppTypeClass


@dataclass
class FpyOperator(FpyCallable):
    op: str


# named variables can be tlm chans, prms, callables, or directly referenced consts (usually enums)
@dataclass
class FpyVariable:
    type_ref: AstReference
    type: FppTypeClass | None = None
    """type of the variable. None if type unsure at the moment"""


FpyReference = ChTemplate | PrmTemplate | FppType | FpyCallable | FppTypeClass


@dataclass
class CompileState:
    tlms: dict[str, ChTemplate] = field(repr=False, default_factory=dict)
    prms: dict[str, PrmTemplate] = field(repr=False, default_factory=dict)
    global_consts: dict[str, FppType] = field(repr=False, default_factory=dict)
    types: dict[str, FppTypeClass] = field(repr=False, default_factory=dict)
    callables: dict[str, list[FpyCallable]] = field(repr=False, default_factory=dict)
    infix_operators: dict[str, list[FpyCallable]] = field(
        repr=False, default_factory=dict
    )

    parent_scope: dict[Ast, AstScopedBody | None] = field(
        repr=False, default_factory=dict
    )
    """a dict tracking the parent scope of each ast node. keys are ast node uid, values are uid of parent scopedbody"""

    variable_tables: dict[AstScopedBody, dict[str, FpyVariable]] = field(
        repr=False, default_factory=dict
    )
    """a table containing all function definitions and variables, for each scopedbody. keys are ast node uid"""

    resolved_references: dict[AstReference, list[FpyReference]] = field(
        default_factory=dict
    )

    runtime_consts: dict[Ast, FppType] = field(default_factory=dict)

    next_register: int = 0
    next_lvar: int = 0

    conditionals: dict[AstComparison, "ConditionalAnalysis"] = field(
        default_factory=dict
    )
    ifs: dict[AstIf, "IfAnalysis"] = field(default_factory=dict)

    prerequisite_nodes: dict[Ast, list[Ast]] = field(default_factory=dict)
    generated_directives: dict[Ast, list[Union[Directive, "IfAnalysis"]]] = field(
        default_factory=dict
    )

    body_directives: dict[
        AstScopedBody | AstUnscopedBody, list[Union[Directive, "IfAnalysis"]]
    ] = field(default_factory=dict)

    linearized_directives: list[Directive] = field(default_factory=list)

    errors: list[CompileException] = field(default_factory=list)

    def lookup_ref(self, node: AstReference, error_if_none=False) -> list[FpyReference]:
        refs = self.resolved_references.get(node, [])
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
        if len(refs) == 0:
            return None
        return refs[0]

    def lookup_variable(self, var: str, at_node: Ast) -> FpyVariable | None:
        # first check if there's a symbol defined in the sequence
        parent = self.parent_scope[at_node]
        while parent is not None:
            table = self.variable_tables[parent]
            if var in table:
                return table[var]

            parent = self.parent_scope[parent]

        return None


def check_literal_converts_to_type(literal: Literal, type: FpyGenericType) -> bool:

    if isinstance(literal, AstString):
        return issubclass(type, StringType)
    if isinstance(literal, AstBoolean):
        return type == BoolType
    if isinstance(literal, AstNumber):
        if type == AnyNumericType:
            return True
        if isinstance(literal.value, float):
            return type in FLOAT_TYPES
        if isinstance(literal.value, int):
            if literal.value < 0:
                return type in SIGNED_INTEGER_TYPES
            return type in INTEGER_TYPES

    assert False, literal


def check_reference_converts_to_type(ref: FpyReference, typ: FpyGenericType) -> bool:
    base_type = None

    if isinstance(ref, ChTemplate):
        base_type = ref.ch_type_obj
    elif isinstance(ref, PrmTemplate):
        base_type = ref.prm_type_obj
    elif isinstance(ref, FppType):
        base_type = type(ref)
    elif isinstance(ref, FpyCallable):
        # a reference to a callable isn't a type in and of itself
        # it has a return type but you have to call it
        base_type = None
    elif isinstance(ref, type):
        base_type = ref
    else:
        assert False, ref

    if base_type in NUMERIC_TYPES and typ == AnyNumericType:
        return True

    return base_type == typ


def unsafe_coerce_literal_to_value(literal: Literal, typ: FpyGenericType) -> FppType:
    if isinstance(literal, AstBoolean):
        return BoolType(literal.value)
    if isinstance(literal, AstString):
        return typ(literal.value)
    if isinstance(literal, AstNumber):
        if typ == AnyNumericType:
            # we get to choose
            if isinstance(literal.value, float):
                return F64Type(literal.value)
            return I64Type(literal.value)
        return typ(literal.value)

    assert False, (literal, typ)


def resolve_polymorphic_funcs(
    node: Ast,
    node_args: list[AstArgument],
    funcs: list[FpyCallable],
    state: CompileState,
) -> FpyCallable | None:
    # resolve polymorphic funcs by trying each possible func

    # tuples of all funcs that we checked, their arg vals if they were compatible, and exception if not
    checked_funcs: list[tuple[FpyCallable, bool, CompileException]] = []
    matching_funcs: list[FpyCallable] = []

    for func in funcs:
        compatible, exception = check_args_compatible(func, node, node_args, state)
        checked_funcs.append((func, compatible, exception))
        if compatible:
            matching_funcs.append(func)

    if len(matching_funcs) == 0:
        state.errors.append(
            CompileException(f"No matching function. Tried {checked_funcs}", node)
        )
        return None

    if len(matching_funcs) > 1:
        state.errors.append(
            CompileException(f"Ambiguous functions {matching_funcs}", node)
        )
        return None

    func = matching_funcs[0]

    return func


def check_args_compatible(
    func: FpyCallable, node: Ast, node_args: list[AstArgument], state: CompileState
) -> tuple[bool, CompileException]:
    if len(node_args) < len(func.args):
        return False, CompileException(
            f"Missing arguments (expected {len(func.args)} found {len(node_args)})",
            node,
        )
    if len(node_args) > len(func.args):
        return False, CompileException(
            f"Too many arguments (expected {len(func.args)} found {len(node_args)})",
            node,
        )

    for value_node, arg_template in zip(node_args, func.args):
        arg_name, arg_type = arg_template
        arg_type: FpyGenericType

        # check type of value matches expected type of template
        compatible = False
        if isinstance(value_node, Literal):
            compatible = check_literal_converts_to_type(value_node, arg_type)
        elif isinstance(value_node, (AstFuncCall, AstComparison)):
            fpy_callable = state.lookup_single_ref_with_type(
                value_node.func, FpyCallable
            )
            if fpy_callable is None:
                # this function could not be resolved to a single callable
                # error was already generated by lookup
                return
            compatible = fpy_callable.return_type == arg_type
        elif isinstance(value_node, AstReference):
            # if any reference converts to this type, we're good
            for ref in state.lookup_ref(value_node):
                compatible = check_reference_converts_to_type(ref, arg_type)
                if compatible:
                    break

        if not compatible:
            return False, CompileException(
                f"Cannot interpret {value_node} as {arg_type}"
            )

    # got thru all args successfully

    return True, None


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


class ResolveReferencesByName(CompilePass):

    def visit_AstReference(self, parent, node: AstReference, state: CompileState):
        fqn = ".".join(name.value for name in node.names)

        tlm = state.tlms.get(fqn, None)
        prm = state.prms.get(fqn, None)
        const = state.global_consts.get(fqn, None)
        type = state.types.get(fqn, None)
        callables = state.callables.get(fqn, [])
        var = state.lookup_variable(fqn, node)

        possible_resolutions = callables + [tlm, prm, const, type, var]

        possible_resolutions = [ref for ref in possible_resolutions if ref is not None]

        if node in state.resolved_references:
            # already resolved previously
            # make sure we're resolving it the same way now
            assert (
                state.resolved_references[node] == possible_resolutions
            ), state.resolved_references[node]
            # okay all good, same resolution
            return

        if len(possible_resolutions) == 0:
            state.errors.append(CompileException(f"Unknown reference {fqn}", node))
            return

        state.resolved_references[node] = possible_resolutions


class CreateScopes(TopDownCompilePass):

    def visit_default(self, parent, node, state):
        if isinstance(parent, (AstScopedBody, NoneType)):
            state.parent_scope[node] = parent if parent is not None else None
        else:
            state.parent_scope[node] = state.parent_scope[parent]

    def visit_AstScopedBody(self, parent, node: AstScopedBody, state: CompileState):
        state.variable_tables[node] = {}
        state.parent_scope[node] = (
            state.parent_scope[parent] if parent is not None else None
        )


class CreateVariables(CompilePass):

    def visit_AstAssign(self, parent, node: AstAssign, state: CompileState):
        # okay we're assigning a variable to something. look it up in the variable table
        existing = state.lookup_variable(node.variable.value, node.variable)
        if not existing:
            # idk what this var is. make sure it's a valid declaration
            if node.var_type is None:
                # error because this isn't an annotated assignment. right now all declarations must be annotated
                state.errors.append(
                    CompileException(
                        "Must provide a type annotation for new variables",
                        node.variable,
                    )
                )
                return

            # new var. put it in the table under this scope
            parent_scope = state.parent_scope[node]
            state.variable_tables[parent_scope][node.variable.value] = FpyVariable(
                node.var_type, None
            )


class CheckVariableTypesAndValues(CompilePass):

    def visit_AstAssign(self, parent, node: AstAssign, state: CompileState):
        existing_var = state.lookup_variable(node.variable.value, node)
        # should already have been put in var table
        assert existing_var is not None

        # start by checking the type node is a reference to a valid type

        if node.var_type is not None:
            # lookup whatever the var type node refers to
            ref = state.lookup_single_ref_with_type(node.var_type, type)
            # if it is not a FppTypeClass, error
            if ref is None:
                # error is generated in lookup
                return

            # okay, type node is a valid type

            if existing_var.type == None:
                # we haven't resolved this variable's type ref before
                existing_var.type = ref
            else:
                # we have resolved this variable's type ref before
                # make sure consistent resolution
                if existing_var.type != ref:
                    state.errors.append(
                        CompileException(
                            f"Inconsistent type. Was {existing_var.type}, but annotation was {ref}",
                            node.var_type,
                        )
                    )
                    return

        assert existing_var.type is not None

        # okay we now have type information about our variable
        # check the value

        value_type_compatible = False
        value = None

        if isinstance(node.value, AstReference):
            # lookup whatever the value node refers to
            ref = state.lookup_single_ref_with_type(node.value, FppType)
            # if it is not an fpptype, error
            if ref is None:
                # error is generated in lookup
                return
            value_type_compatible = type(ref) == existing_var.type
            value = ref
        else:
            assert isinstance(node.value, Literal), node.value
            value_type_compatible = check_literal_converts_to_type(
                node.value, existing_var.type
            )
            if value_type_compatible:
                value = unsafe_coerce_literal_to_value(node.value, existing_var.type)
                state.runtime_consts[node.value] = value

        if not value_type_compatible:
            state.errors.append(
                CompileException(
                    f"Variable is of type {existing_var.type}, but value {node.value} could not be converted to this",
                    node.value,
                )
            )
            return

        # type of value is compatible
        # something like...
        # state.instructions[node] = FpyInstruction(node.variable.value, value)
        # state.generated_directives[node] = ConstDirective(DirectiveOpcode.)


class ResolvePolymorphicCallsByArgType(CompilePass):

    def visit_AstComparison(self, parent, node: AstComparison, state: CompileState):
        # op exists at syntax level, coding error if no exist
        funcs = state.infix_operators[node.op.value]
        func = resolve_polymorphic_funcs(node, [node.lhs, node.rhs], funcs, state)
        if func is None:
            # error is handled in resolve_poly
            return
        state.resolved_references[node.op] = [func]

    def visit_AstFuncCall(self, parent, node: AstFuncCall, state: CompileState):
        funcs = state.lookup_ref_with_type(node.func, FpyCallable)
        func = resolve_polymorphic_funcs(
            node, node.args if node.args else [], funcs, state
        )
        if func is None:
            # error is handled in resolve_poly
            return
        state.resolved_references[node.func] = [func]


def construct_runtime_consts(
    node: AstComparison | AstFuncCall,
    func: FpyCallable,
    args: list[AstArgument],
    state: CompileState,
):

    # try gathering arg values. if we fail to gather an arg value, assume it is not a
    # runtime constant and skip it

    # gather arg values
    arg_values: list[tuple[str, FppType]] = []
    for arg_node, arg_template in zip(args, func.args):
        arg_name, arg_type = arg_template
        # we can already be assured that the node converts to our desired type because of
        # the previous compiler pass
        # but it might not have a constant value. if it doesn't, skip it and skip this type
        arg_value = None
        if isinstance(arg_node, Literal):
            # should not error, if it does, coding error
            arg_value = unsafe_coerce_literal_to_value(arg_node, arg_type)
            state.runtime_consts[arg_node] = arg_value
        elif isinstance(arg_node, AstFuncCall):
            # if it's a func call with a constant result we should already
            # have calculated its value at this point in the traverse. try to get it
            arg_value = state.runtime_consts.get(arg_node, None)
        elif isinstance(arg_node, AstReference):
            arg_value = state.lookup_single_ref_with_type(
                arg_node, FppType, dont_create_errors=True
            )
        else:
            assert False, arg_node

        if not check_literal_converts_to_type()
            # do not have a runtime constant value for this node
            # skip on constructing this type

            # right now this is an error. all function calls must have const args
            # in the future this shouldn't be an error
            state.errors.append(
                CompileException(
                    f"Unable to call {func} because {arg_name}'s value was not known at compile time",
                    arg_node,
                )
            )

            return

        arg_values.append((arg_name, arg_value))

    if isinstance(func, FpyTypeCtor):
        # actually construct the type
        if issubclass(func.type, SerializableType):
            # pass in args as a dict
            instance = func.type()
            instance._val = arg_values
            state.runtime_consts[node] = instance

        elif issubclass(func.return_type, ArrayType):
            state.runtime_consts[node] = func.return_type(arg_values)

        elif func.return_type == TimeType:
            state.runtime_consts[node] = TimeType(**arg_values)

        else:
            # no other FppTypeClasses have ctors
            assert False, func.return_type
    elif isinstance(func, FpyCmd):
        # convert the cmd to a cmd directive
        serialized_arg_values = bytes()
        for arg_name, arg_value in arg_values:
            serialized_arg_values += arg_value.serialize()
        state.generated_directives[node] = [
            CmdDirective(func.cmd.get_op_code(), serialized_arg_values)
        ]
    elif isinstance(func, FpyBuiltin):
        directive_args = [a for a, n in arg_values]
        state.generated_directives[node] = [func.dir(*directive_args)]
    # require that all node argument directives are included before this directive
    state.prerequisite_nodes[node] = node.args


class ConstructRuntimeConstants(CompilePass):

    def visit_AstFuncCall(self, parent, node: AstFuncCall, state: CompileState):
        func = state.lookup_single_ref_with_type(node.func, FpyCallable)
        if func is None:
            # error generated in lookup
            return
        construct_runtime_consts(node, func, node.args, state)

    def visit_AstComparison(self, parent, node: AstComparison, state: CompileState):
        func = state.lookup_single_ref_with_type(node.op, FpyCallable)
        if func is None:
            # error generated in lookup
            return
        construct_runtime_consts(node, func, [node.lhs, node.rhs], state)


def put_const_in_register(
    node: Ast, const: FppType, register: int, state: CompileState
) -> list[Directive] | None:
    const_type = type(const)
    # is it too big to fit in a register?
    type_size = const_type.getMaxSize()
    if type_size > 8:
        state.errors.append(
            CompileException(
                f"{const_type} cannot fit in a register (it is {type_size} bytes long, which is greater than 8)",
                node,
            )
        )
        return None

    serialized_const = const.serialize()

    assert len(serialized_const) <= 8, len(serialized_const)

    # reinterpret as an I64
    const_as_i64 = I64Type()
    const_as_i64.deserialize(serialized_const, 0)

    set_reg_directive = SetRegDirective(register, const_as_i64.val)

    return [set_reg_directive]


def put_reference_in_lvar(
    node: AstReference, lvar: int, secondary_lvar: int, state: CompileState
) -> list[Directive]:
    resolved_refs = state.lookup_ref(node)
    if len(resolved_refs) != 1:
        state.errors.append(CompileException("Unknown reference", node))
        return None

    ref = resolved_refs[0]

    if not isinstance(ref, (ChTemplate, PrmTemplate, FppType)):
        state.errors.append(CompileException("Reference has no value", node))
        return None

    put_in_lvar_directive = None

    if isinstance(ref, ChTemplate):
        put_in_lvar_directive = GetTlmDirective(lvar, secondary_lvar, ref.get_id())

    elif isinstance(ref, PrmTemplate):
        put_in_lvar_directive = GetPrmDirective(state.next_lvar, ref.get_id())

    elif isinstance(ref, FppType):
        put_in_lvar_directive = SetLocalVarDirective(lvar, ref.serialize())

    else:
        assert False, ref

    return [put_in_lvar_directive]


def put_reference_in_register(
    node: AstReference, register: int, state: CompileState
) -> list[Directive] | None:
    directives = []
    lvar_idx = state.next_lvar
    secondary_lvar_idx = state.next_lvar + 1
    state.next_lvar += 2
    ref_in_lvar = put_reference_in_lvar(node, lvar_idx, secondary_lvar_idx, state)
    if ref_in_lvar is None:
        return
    directives.extend(ref_in_lvar)

    lvar_type = get_argument_type(node, state)

    # okay now pull from this lvar into a register

    # is it too big to fit in a register?
    type_size = lvar_type.getMaxSize()
    if type_size > 8:
        state.errors.append(
            CompileException(
                f"{lvar_type} cannot fit in a register (it is {type_size} bytes long, which is greater than 8)",
                node,
            )
        )
        return None

    put_in_reg_directive = None
    if type_size > 4:
        put_in_reg_directive = DeserLocalVar8Directive(lvar_idx, 0, register)
    elif type_size > 2:
        put_in_reg_directive = DeserLocalVar4Directive(lvar_idx, 0, register)
    elif type_size > 1:
        put_in_reg_directive = DeserLocalVar2Directive(lvar_idx, 0, register)
    elif type_size == 1:
        put_in_reg_directive = DeserLocalVar1Directive(lvar_idx, 0, register)
    else:
        assert False, type_size

    directives.append(put_in_reg_directive)

    return directives


def put_argument_in_register(
    node: AstArgument, register: int, state: CompileState
) -> list[Directive] | None:
    directives = []
    if isinstance(node, AstReference):
        dirs = put_reference_in_register(node, register, state)
        if dirs is None:
            return None
        directives.extend(dirs)
    elif isinstance(node, AstFuncCall):
        # node must already have a const value at this point
        dirs = put_const_in_register(node, state.runtime_consts[node], register, state)
        if dirs is None:
            return None
        directives.extend(dirs)
    elif isinstance(node, Literal):
        # node must have an interpreted value at this point
        dirs = put_const_in_register(node, state.runtime_consts[node], register, state)
        if dirs is None:
            return None
        directives.extend(dirs)

    return directives


def get_argument_type(node: AstArgument, state: CompileState) -> FppTypeClass:
    if isinstance(node, AstReference):
        resolved_refs = state.lookup_ref(node)
        if len(resolved_refs) != 1:
            state.errors.append(CompileException("Unknown reference", node))
            return None

        ref = resolved_refs[0]

        if not isinstance(ref, (ChTemplate, PrmTemplate, FppType)):
            state.errors.append(CompileException("Reference has no value", node))
            return None

        if isinstance(ref, ChTemplate):
            return ref.get_type_obj()

        elif isinstance(ref, PrmTemplate):
            return ref.get_type_obj()

        elif isinstance(ref, FppType):
            return type(ref)

    elif isinstance(node, (AstFuncCall | Literal)):
        return type(state.runtime_consts[node])


class ConditionalAnalysis:
    class Never:
        pass

    class Always:
        pass

    @dataclass
    class BranchFromRegister:
        result_reg: int


class CheckConditionals(CompilePass):
    def visit_AstComparison(self, parent, node: AstComparison, state: CompileState):
        lhs_type = get_argument_type(node.lhs, state)
        rhs_type = get_argument_type(node.rhs, state)

        result = ConditionalAnalysis.Never

        if node.op.value == "==":
            if lhs_type != rhs_type:
                # two diff types are never equal
                # probably a coding error, fail
                state.errors.append(
                    CompileException(f"Cannot compare {lhs_type} with {rhs_type}", node)
                )
                return
        elif node.op.value == "!=":
            if lhs_type != rhs_type:
                # two diff types are always unequal
                state.errors.append(
                    CompileException(f"Cannot compare {lhs_type} with {rhs_type}", node)
                )
                return

        lhs_reg = state.next_register
        state.next_register += 1
        rhs_reg = state.next_register
        state.next_register += 1
        res_reg = state.next_register
        state.next_register += 1

        lhs_dirs = put_argument_in_register(node.lhs, lhs_reg, state)
        if lhs_dirs is None:
            return
        rhs_dirs = put_argument_in_register(node.rhs, rhs_reg, state)
        if rhs_dirs is None:
            return

        comparison_dirs = []

        if node.op.value == "==":
            comparison_dirs.append(EqualDirective(lhs_reg, rhs_reg, res_reg))
        elif node.op.value == "!=":
            comparison_dirs.append(NotEqualDirective(lhs_reg, rhs_reg, res_reg))
        else:
            signed = False
            if lhs_type in SIGNED_INTEGER_TYPES or rhs_type in SIGNED_INTEGER_TYPES:
                # if either is signed, promote both to signed
                signed = True

            if signed:
                dir_type = SIGNED_INEQUALITY_DIRECTIVES[node.op.value]
            else:
                dir_type = UNSIGNED_INEQUALITY_DIRECTIVES[node.op.value]

            comparison_dirs.append(dir_type(lhs_reg, rhs_reg, res_reg))

        # require that all directives for lhs and rhs are included before these dirs
        state.prerequisite_nodes[node] = [node.lhs, node.rhs]
        state.generated_directives[node] = lhs_dirs + rhs_dirs + comparison_dirs
        state.conditionals[node] = ConditionalAnalysis.BranchFromRegister(res_reg)

    def visit_AstNot(self, parent, node: AstNot, state: CompileState):
        value_analysis = state.conditionals.get(node.value, None)
        if value_analysis is not None:
            if value_analysis == ConditionalAnalysis.Never:
                state.conditionals[node] = ConditionalAnalysis.Always
                return
            elif value_analysis == ConditionalAnalysis.Always:
                state.conditionals[node] = ConditionalAnalysis.Never
                return
            elif isinstance(value_analysis, ConditionalAnalysis.BranchFromRegister):
                value_reg = value_analysis.result_reg
                res_reg = state.next_register
                state.next_register += 1
                # make sure that all directives needed to create the value are included before these ones
                state.prerequisite_nodes[node] = [node.value]
                state.generated_directives[node] = [NotDirective(value_reg, res_reg)]
                state.conditionals[node] = ConditionalAnalysis.BranchFromRegister(
                    res_reg
                )
                return
            else:
                assert False, value_analysis
        # okay, value is not a conditional
        assert isinstance(node.value, AstArgument), node.value

        value_reg = state.next_register
        state.next_register += 1
        dirs = put_argument_in_register(node.value, value_reg, state)
        if dirs is None:
            # cannot put in register
            return
        res_reg = state.next_register
        state.next_register += 1
        dirs.append(NotDirective(value_reg, res_reg))
        # make sure that all directives needed to create the value are included before these ones
        state.prerequisite_nodes[node] = [node.value]
        state.generated_directives[node] = dirs
        state.conditionals[node] = ConditionalAnalysis.BranchFromRegister(res_reg)

    def visit_AstAnd(self, parent, node: AstAnd, state: CompileState):

        registers_to_compare = []
        dirs = []

        state.prerequisite_nodes[node] = []
        for value in node.values:
            conditional_analysis = state.conditionals.get(value, None)
            if conditional_analysis == ConditionalAnalysis.Never:
                # this "and" can never be true because some arg is never true
                state.conditionals[node] = ConditionalAnalysis.Never
                return
            if conditional_analysis == ConditionalAnalysis.Always:
                # this arg is always true, don't have to calculate anything with it
                continue
            # otherwise, we actually have to calculate something here
            # include the directives necessary for this conditional
            state.prerequisite_nodes[node].append(value)
            if isinstance(conditional_analysis, ConditionalAnalysis.BranchFromRegister):
                registers_to_compare.append(conditional_analysis.result_reg)
                continue
            assert isinstance(value, AstArgument)
            value_reg = state.next_register
            state.next_register += 1
            argument_in_register_dirs = put_argument_in_register(
                value, value_reg, state
            )
            if argument_in_register_dirs is None:
                # unable to put arg in register
                return
            dirs.extend(argument_in_register_dirs)
            registers_to_compare.append(value_reg)

        assert len(registers_to_compare) >= 2, len(registers_to_compare)

        # okay, now we have to "and" together all of the registers
        # "and" the first two together, put in res.
        # from then on, "and" the next with res

        res_reg = state.next_register
        state.next_register += 1

        dirs.append(
            AndDirective(registers_to_compare[0], registers_to_compare[1], res_reg)
        )

        for i in range(2, len(registers_to_compare)):
            dirs.append(AndDirective(res_reg, registers_to_compare[i], res_reg))

        state.generated_directives[node] = dirs
        state.conditionals[node] = ConditionalAnalysis.BranchFromRegister(res_reg)

    def visit_AstOr(self, parent, node: AstOr, state: CompileState):

        registers_to_compare = []
        dirs = []

        state.prerequisite_nodes[node] = []
        for value in node.values:
            conditional_analysis = state.conditionals.get(value, None)
            if conditional_analysis == ConditionalAnalysis.Always:
                # this "or" is always true because some arg is always true
                state.conditionals[node] = ConditionalAnalysis.Always
                return
            if conditional_analysis == ConditionalAnalysis.Never:
                # this arg is never true, don't have to calculate anything with it
                continue
            # otherwise, we actually have to calculate something here
            # include the directives necessary for this conditional
            state.prerequisite_nodes[node].append(value)
            if isinstance(conditional_analysis, ConditionalAnalysis.BranchFromRegister):
                registers_to_compare.append(conditional_analysis.result_reg)
                continue
            assert isinstance(value, AstArgument)
            value_reg = state.next_register
            state.next_register += 1
            argument_in_register_dirs = put_argument_in_register(
                value, value_reg, state
            )
            if argument_in_register_dirs is None:
                # unable to put arg in register
                return
            dirs.extend(argument_in_register_dirs)
            registers_to_compare.append(value_reg)

        assert len(registers_to_compare) >= 2, len(registers_to_compare)

        # okay, now we have to "or" together all of the registers
        # "or" the first two together, put in res.
        # from then on, "or" the next with res

        res_reg = state.next_register
        state.next_register += 1

        dirs.append(
            OrDirective(registers_to_compare[0], registers_to_compare[1], res_reg)
        )

        for i in range(2, len(registers_to_compare)):
            dirs.append(OrDirective(res_reg, registers_to_compare[i], res_reg))

        state.generated_directives[node] = dirs
        state.conditionals[node] = ConditionalAnalysis.BranchFromRegister(res_reg)

    def visit_AstElif(self, parent, node: AstElif, state: CompileState):
        # include all code necessary to calculate the condition
        state.prerequisite_nodes[node] = [node.condition]
        if isinstance(node.condition, AstArgument):
            res_reg = state.next_register
            state.next_register += 1
            dirs = put_argument_in_register(node.condition, res_reg, state)
            if dirs is None:
                # could not put arg in register
                return
            state.generated_directives[node] = dirs
            state.conditionals[node] = ConditionalAnalysis.BranchFromRegister(res_reg)
        else:
            # it should already be analyzed
            state.conditionals[node] = state.conditionals[node.condition]

    def visit_AstIf(self, parent, node: AstIf, state: CompileState):
        # elif and if are handled the same way
        self.visit_AstElif(parent, node, state)


@dataclass
class ConditionalBody:
    condition_node: AstCondition
    condition_analysis: ConditionalAnalysis
    body: AstUnscopedBody


@dataclass
class IfAnalysis:
    conditional_bodies: list[ConditionalBody]


class AnalyzeControlFlow(CompilePass):
    def visit_AstIf(self, parent, node: AstIf, state: CompileState):

        # the bodies, before filtering for always true/false conditions
        unfiltered_bodies: list[ConditionalBody] = []
        # all conditionals should already be analyzed
        unfiltered_bodies.append(
            ConditionalBody(
                node.condition, state.conditionals[node.condition], node.body
            )
        )
        for elif_case in node.elifs if node.elifs is not None else []:
            conditional_analysis = state.conditionals[elif_case.condition]
            unfiltered_bodies.append(
                ConditionalBody(
                    elif_case.condition, conditional_analysis, elif_case.body
                )
            )

        # the bodies, after optimizing away always false, and not including
        # anything after an always true cond
        bodies: list[ConditionalBody] = []
        for condition_node, conditional_analysis, body in unfiltered_bodies:
            # all conditionals should already be analyzed
            if conditional_analysis == ConditionalAnalysis.Never:
                # don't bother including this branch
                continue
            bodies.append(ConditionalBody(condition_node, conditional_analysis, body))
            if conditional_analysis == ConditionalAnalysis.Always:
                # this one always happens, don't include anything after
                break

        # okay, now we know which ones will/won't happen for sure
        # generate code
        state.prerequisite_nodes[node] = []
        state.generated_directives[node] = [IfAnalysis(bodies)]

    def visit_AstUnscopedBody(self, parent, node: AstUnscopedBody, state: CompileState):
        # descend the tree of prerequisites
        # add all generated nodes to list

        def get_dirs(n: Ast) -> list[Union[Directive | IfAnalysis]]:
            prereq_directives = []
            for prereq in state.prerequisite_nodes.get(n, []):
                prereq_directives.extend(get_dirs(prereq))

            return prereq_directives + state.generated_directives.get(n, [])

        state.prerequisite_nodes[node] = node.stmts
        state.body_directives[node] = get_dirs(node)

    def visit_AstScopedBody(self, parent, node: AstScopedBody, state: CompileState):
        # unscoped and scoped are handled the same way
        self.visit_AstUnscopedBody(parent, node, state)


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

    enum_consts: dict[str, FppType] = {}

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
        callable_name_dict[name].append(FpyCmd(None, args, cmd))

    infix_callable_name_dict = defaultdict(list)

    numeric_infix_ops = ["<", ">", "<=", ">=", "==", "!="]
    for op in numeric_infix_ops:
        infix_callable_name_dict[op].append(
            FpyOperator(
                BoolType, [("lhs", AnyNumericType), ("rhs", AnyNumericType)], op
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

        callable_name_dict[name].append(FpyTypeCtor(typ, args, typ))

    state = CompileState(
        tlms=ch_name_dict,
        prms=prm_name_dict,
        global_consts=enum_consts,
        callables=callable_name_dict,
        types=type_name_dict,
        infix_operators=infix_callable_name_dict,
    )
    return state


def compile(body: AstScopedBody, dictionary: str) -> list[StatementData]:
    state = get_base_compile_state(dictionary)
    passes: list[CompilePass] = [
        AssignIds(),
        CreateScopes(),
        # might want to error if you're overriding smth from the dict
        CreateVariables(),
        # now that variables have been defined, try resolving references
        # again and fail if anything isn't found
        ResolveReferencesByName(),
        CheckVariableTypesAndValues(),
        # okay, we know what all the different names could be pointing to,
        # at least according to the name of the symbol.
        # but in the case of polymorphic functions, multiple funcs can have
        # the same name. let's use arg types to figure out which one we're calling
        ResolvePolymorphicCallsByArgType(),
        # now we know what each call points to
        ConstructRuntimeConstants(),
        CheckConditionals(),
        AnalyzeControlFlow(),
    ]
    for compile_pass in passes:
        compile_pass.run(body, state)
        print(state)
        for error in state.errors:
            raise error

    print()
    print(state.body_directives[body])
