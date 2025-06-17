from ast import Pass
from collections import defaultdict
from dataclasses import dataclass, field, fields
from enum import Enum
import traceback
from types import NoneType
from typing import TypeVar, overload

from fprime_gds.common.data_types.cmd_data import CmdData
from fprime_gds.common.fpy.bytecode.types import (
    FPY_DIRECTIVES,
    DirectiveOpcode,
    StatementData,
    StatementTemplate,
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
    Argument,
    AstBoolean,
    AstComparison,
    AstInfixOp,
    AstNumber,
    AstReference,
    AstString,
    Ast,
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
    opcode: int


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

    generated_directives: dict[Ast, list[ConstDirective]] = field(
        default_factory=dict
    )

    linearized_directives: list[ConstDirective] = field(default_factory=list)

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
    node_args: list[Argument],
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
    func: FpyCallable, node: Ast, node_args: list[Argument], state: CompileState
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
        state.generated_directives[node] = ConstDirective(DirectiveOpcode.)


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


class ConstructRuntimeConstants(CompilePass):

    def visit_AstFuncCall(self, parent, node: AstFuncCall, state: CompileState):
        func = state.lookup_single_ref_with_type(node.func, FpyCallable)
        if func is None:
            # error generated in lookup
            return

        # try gathering arg values. if we fail to gather an arg value, assume it is not a
        # runtime constant and skip it

        # gather arg values
        arg_values = []
        for arg_node, arg_template in zip(node.args if node.args is not None else [], func.args):
            arg_name, arg_type = arg_template
            # we can already be assured that the node converts to our desired type because of
            # the previous compiler pass
            # but it might not have a constant value. if it doesn't, skip it and skip this type
            arg_value = None
            if isinstance(arg_node, Literal):
                # should not error, if it does, coding error
                arg_value = unsafe_coerce_literal_to_value(arg_node, arg_type)
            elif isinstance(arg_node, AstFuncCall):
                # if it's a func call with a constant result we should already
                # have calculated its value at this point in the traverse. try to get it
                arg_value = state.runtime_consts.get(arg_node, None)
            elif isinstance(arg_node, AstReference):
                # TODO next thing to do is error if this isn't a const, or pull this out into a diff step
                arg_value = state.lookup_single_ref_with_type(
                    arg_node, FppType, dont_create_errors=True
                )
            else:
                assert False, arg_node

            if not isinstance(arg_value, arg_type):
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
            arg_values.insert(0, ("opcode", func.cmd.get_op_code()))
            state.generated_directives[node] = [
                ConstDirective(DirectiveOpcode.CMD, arg_values)
            ]
        elif isinstance(func, FpyBuiltin):
            state.generated_directives[node] = [
                ConstDirective(func.opcode, arg_values)
            ]


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


class LinearizeGeneratedDirectives(CompilePass):
    def visit_default(self, parent, node, state):
        directives = state.generated_directives.get(node, [])
        state.linearized_directives.extend(directives)


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
        CheckComparisons(),
        CheckIfStatements(),
        LinearizeGeneratedDirectives(),
    ]
    for compile_pass in passes:
        compile_pass.run(body, state)
        print(state)
        for error in state.errors:
            raise error

    print()
    print(state.linearized_directives)
