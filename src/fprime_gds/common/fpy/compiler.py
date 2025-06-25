from abc import ABC
import argparse
import inspect
from pathlib import Path
from pprint import pprint
from collections import defaultdict
from dataclasses import dataclass, field, fields
import traceback
from types import NoneType
from typing import TypeVar, Union

from fprime_gds.common.fpy.bytecode.serialize_bytecode import serialize_directives
from fprime_gds.common.fpy.bytecode.directives import (
    BINARY_COMPARISON_DIRECTIVES,
    EQUALITY_DIRECTIVES,
    MAX_SERIALIZABLE_REGISTER_SIZE,
    SIGNED_INEQUALITY_DIRECTIVES,
    UNSIGNED_INEQUALITY_DIRECTIVES,
    AndDirective,
    CmdDirective,
    DeserSerReg1Directive,
    DeserSerReg2Directive,
    DeserSerReg4Directive,
    DeserSerReg8Directive,
    Directive,
    EqualDirective,
    GetPrmDirective,
    GetTlmDirective,
    GotoDirective,
    IfDirective,
    NotDirective,
    NotEqualDirective,
    OrDirective,
    SetSerRegDirective,
    SetRegDirective,
)
from fprime_gds.common.loaders.ch_json_loader import ChJsonLoader
from fprime_gds.common.loaders.cmd_json_loader import CmdJsonLoader
from fprime_gds.common.loaders.prm_json_loader import PrmJsonLoader
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime_gds.common.templates.prm_template import PrmTemplate
from fprime.common.models.serialize.time_type import TimeType
from fprime.common.models.serialize.enum_type import EnumType
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
    FloatType,
    IntegerType,
    NumericalType,
)
from fprime.common.models.serialize.string_type import StringType
from fprime.common.models.serialize.bool_type import BoolType
from fprime_gds.common.fpy.parser import (
    AstAnd,
    AstBoolean,
    AstComparison,
    AstElif,
    AstElifs,
    AstExpr,
    AstGetAttr,
    AstNot,
    AstNumber,
    AstOr,
    AstReference,
    AstStmt,
    AstString,
    Ast,
    AstTest,
    AstUnscopedBody,
    AstLiteral,
    AstScopedBody,
    AstIf,
    AstAssign,
    AstFuncCall,
    parse,
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


class NothingType(ABC):
    @classmethod
    def __subclasscheck__(cls, subclass):
        return False


NothingTypeClass = type[NothingType]


class CompileException(BaseException):
    def __init__(self, msg, node: Ast):
        self.msg = msg
        self.node = node
        self.stack_trace = "\n".join(traceback.format_stack(limit=8)[:-1])

    def __str__(self):
        return f'{self.stack_trace}\nAt line {self.node.meta.line} "{self.node.node_text}": {self.msg}'


@dataclass
class FpyCallable:
    return_type: FppTypeClass | NothingTypeClass
    args: list[tuple[str, FppTypeClass]]


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
    directive: type[Directive]


@dataclass
class FieldReference:
    ref: "FpyReference"
    type: FppTypeClass
    offset: int


# named variables can be tlm chans, prms, callables, or directly referenced consts (usually enums)
@dataclass
class FpyVariable:
    type_ref: AstReference
    type: FppTypeClass | None = None
    """type of the variable. None if type unsure at the moment"""
    sreg_idx: int | None = None
    """the index of the sreg it is stored in"""


FpyNamespace = dict[str, list["FpyReference"]]


def create_namespaces(references: dict[str, "FpyReference"]) -> FpyNamespace:

    base: FpyNamespace = {}

    for fqn, ref in references.items():
        names_strs = fqn.split(".")

        ns = base
        while len(names_strs) > 1:
            existing_children = ns.get(names_strs[0], None)
            if existing_children is None:
                existing_children = []
                ns[names_strs[0]] = existing_children

            found_ns = False
            for child in existing_children:
                if isinstance(child, dict):
                    # found a namespace
                    ns = child
                    names_strs = names_strs[1:]
                    found_ns = True
                    break

            if found_ns:
                continue

            # did not find an existing namespace
            new_ns = {}
            existing_children.append(new_ns)
            ns = new_ns
            names_strs = names_strs[1:]

        # only one name left

        # is there a list entry in the ns for this name
        if names_strs[0] not in ns:
            ns[names_strs[0]] = []

        ns[names_strs[0]].append(ref)

    return ns


FpyReference = (
    ChTemplate
    | PrmTemplate
    | FppType
    | FpyCallable
    | FppTypeClass
    | FpyVariable
    | FieldReference
    | FpyNamespace
)


@dataclass
class CompileState:
    ns: FpyNamespace

    parent_scope: dict[Ast, AstScopedBody | None] = field(
        repr=False, default_factory=dict
    )
    """a dict tracking the parent scope of each ast node"""

    variable_tables: dict[AstScopedBody, dict[str, FpyVariable]] = field(
        repr=False, default_factory=dict
    )
    """a table containing all variables defined in a scope, for each scopedbody"""

    reference_resolution_hints: dict[AstReference, type[FpyReference]] = field(
        default_factory=dict, repr=False
    )

    overloaded_references: dict[AstReference, list[FpyReference]] = field(
        default_factory=dict, repr=False
    )
    """reference to its possible resolutions"""

    resolved_references: dict[AstReference, FpyReference] = field(
        default_factory=dict, repr=False
    )
    """reference to its singular resolution"""

    expr_types: dict[AstExpr, FppTypeClass | NothingTypeClass] = field(
        default_factory=dict
    )
    """expr to its fprime type, or nothing type if none"""

    expr_values: dict[AstExpr, FppType | NothingType | None] = field(
        default_factory=dict
    )
    """expr to its fprime value, or nothing if no value, or None if unsure at compile time"""

    expr_registers: dict[AstExpr, int] = field(default_factory=dict)
    """expr to the register it's stored in"""

    directives: dict[Ast, list[Directive] | None] = field(default_factory=dict)

    node_dir_counts: dict[Ast, int] = field(default_factory=dict)

    next_register: int = 0
    next_sreg: int = 0

    start_line_idx: dict[Ast, int] = field(default_factory=dict)

    linearized_directives: list[Directive] = field(default_factory=list)

    errors: list[CompileException] = field(default_factory=list)

    def lookup_variable(self, var: str, at_node: Ast) -> FpyVariable | None:
        # first check if there's a symbol defined in the sequence
        parent = self.parent_scope[at_node]
        while parent is not None:
            table = self.variable_tables[parent]
            if var in table:
                return table[var]

            parent = self.parent_scope[parent]

        return None


class CompilePass:

    def _find_custom_visit_func(self, node: Ast):
        for name, func in inspect.getmembers(type(self), inspect.isfunction):
            if not name.startswith("visit") or name == "visit_default":
                # not a visitor, or the default visit func
                continue
            signature = inspect.signature(func)
            params = list(signature.parameters.values())
            assert len(params) == 4
            assert params[2].annotation is not None
            if isinstance(node, params[2].annotation):
                return func
        else:
            # call the default
            return type(self).visit_default

    def _visit(self, parent: Ast | None, node: Ast, state: CompileState):
        visit_func = self._find_custom_visit_func(node)
        visit_func(self, parent, node, state)

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
        if existing and node.var_type is not None:
            # redeclaring an existing variable
            state.errors.append(
                CompileException(f"{node.variable.value} already declared", node)
            )
            return


class AssignReferenceResolutionHints(CompilePass):
    def visit_AstFuncCall(self, parent, node: AstFuncCall, state: CompileState):
        # interpret the function reference as an fpy callable
        state.reference_resolution_hints[node.func] = FpyCallable

    def visit_AstAssign(self, parent, node: AstAssign, state: CompileState):
        # interpret the type reference as an fprime type
        if node.var_type is not None:
            state.reference_resolution_hints[node.var_type] = type


class ResolveReferencesByName(CompilePass):

    def visit_AstAssign(self, parent, node: AstAssign, state: CompileState):
        # also lookup variable types

        var = state.lookup_variable(node.variable.value, node)

        assert var is not None

        if node.var_type is not None:
            var_type = state.resolved_references[node.var_type]
            assert var_type is not None
            var.type = var_type

    def visit_AstGetAttr(self, parent, node: AstGetAttr, state: CompileState):
        qualifier_node = node.parent
        resolved = None
        if qualifier_node is None:
            # looking up unqualified
            resolved = state.ns.get(node.attr.value, [])
        else:
            qualifier = state.resolved_references[node.parent]
            if isinstance(qualifier, dict):
                resolved = qualifier.get(node.attr.value, [])
            else:
                fields = self.get_fields(node.parent, qualifier)
                if isinstance(fields, CompileException):
                    state.errors.append(fields)
                    return
                field = fields.get(node.attr.value, None)
                if field is not None:
                    resolved = [field]
                else:
                    resolved = []


        type_hint = state.reference_resolution_hints.get(node, None)
        if type_hint is not None:
            # interpret as type_hint
            resolved = [r for r in resolved if isinstance(r, type_hint)]

        if len(resolved) == 0:
            state.errors.append(CompileException(f"Unknown reference", node))
            return
        if len(resolved) > 1:
            state.errors.append(CompileException(f"Ambiguous reference: {resolved}", node))
            return

        state.resolved_references[node] = resolved[0]

    def is_type_constant_size(self, type: FppTypeClass) -> bool:
        if isinstance(type, StringType):
            return False

        if isinstance(type, ArrayType):
            return self.is_type_constant_size(type.MEMBER_TYPE)

        if isinstance(type, SerializableType):
            for _, arg_type, _, _ in type.MEMBER_LIST:
                if not self.is_type_constant_size(arg_type):
                    return False
            return True

        return True

    def get_fields(self, node: Ast, ref: FpyReference) -> dict[str, list[FieldReference]]|CompileException:

        base_type = None
        if isinstance(ref, ChTemplate):
            base_type = ref.ch_type_obj
        elif isinstance(ref, PrmTemplate):
            base_type = ref.prm_type_obj
        elif isinstance(ref, FppType):
            base_type = type(ref)
        elif isinstance(ref, FppTypeClass):
            base_type = NothingType
        elif isinstance(ref, FpyVariable):
            base_type = ref.type
        elif isinstance(ref, FieldReference):
            base_type = ref.type
        else:
            assert False, ref

        if base_type is None or base_type == NothingType:
            return {}

        if not self.is_type_constant_size(base_type):
            return CompileException(f"{base_type} has non-constant sized members", node)

        fields = {}
        if isinstance(base_type, SerializableType):
            offset = 0
            for arg_name, arg_type, _, _ in base_type.MEMBER_LIST:
                fields[arg_name] = [FieldReference(ref, arg_type, offset)]
                offset += arg_type.getMaxSize()

        elif isinstance(base_type, ArrayType):
            offset = 0
            for i in range(0, base_type.LENGTH):
                fields[f"[{i}]"] = [FieldReference(ref, base_type.MEMBER_TYPE, offset)]
                offset += base_type.MEMBER_TYPE.getMaxSize()

        return fields



class CalculateExprTypes(CompilePass):

    def visit_AstNumber(self, parent, node: AstNumber, state: CompileState):
        if isinstance(node.value, float):
            result_type = FloatType
        elif isinstance(node.value, int):
            result_type = IntegerType
        else:
            assert False, node.value
        state.expr_types[node] = result_type

    def visit_AstString(self, parent, node: AstString, state: CompileState):
        state.expr_types[node] = StringType

    def visit_AstBoolean(self, parent, node: AstBoolean, state: CompileState):
        state.expr_types[node] = BoolType

    def visit_AstGetAttr(self, parent, node: AstGetAttr, state: CompileState):
        ref = state.resolved_references[node]

        if isinstance(ref, ChTemplate):
            result_type = ref.ch_type_obj
        elif isinstance(ref, PrmTemplate):
            result_type = ref.prm_type_obj
        elif isinstance(ref, FppType):
            # constant value
            result_type = type(ref)
        elif isinstance(ref, FpyCallable):
            # a reference to a callable isn't a type in and of itself
            # it has a return type but you have to call it (with an AstFuncCall)
            # consider making a separate "reference" type
            result_type = NothingType
        elif isinstance(ref, FpyVariable):
            result_type = ref.type
        elif isinstance(ref, type):
            # a reference to a type doesn't have a value, and so doesn't have a type,
            # in and of itself. if this were a function call to the type's ctor then
            # it would have a value and thus a type
            result_type = NothingType
        elif isinstance(ref, dict):
            # reference to a namespace. namespaces don't have values
            result_type = NothingType
        else:
            assert False, ref

        state.expr_types[node] = result_type

    def visit_AstFuncCall(self, parent, node: AstFuncCall, state: CompileState):
        ref = state.resolved_references[node.func]
        assert isinstance(ref, FpyCallable)
        state.expr_types[node] = ref.return_type

    def visit_AstOr_AstAnd_AstNot_AstComparison(
        self, parent, node: AstOr | AstAnd | AstNot | AstComparison, state: CompileState
    ):
        state.expr_types[node] = BoolType


class CheckAndResolveArgumentTypes(CompilePass):

    def visit_AstComparison(self, parent, node: AstComparison, state: CompileState):
        # op exists at syntax level, coding error if no exist
        func = state.infix_operators[node.op.value]
        node_args = [node.lhs, node.rhs]
        self.check_args([v for k, v in func.args], node, node_args, state)

    def visit_AstFuncCall(self, parent, node: AstFuncCall, state: CompileState):
        func = state.resolved_references[node.func]
        node_args = node.args if node.args else []
        self.check_args([v for k, v in func.args], node, node_args, state)

    def visit_AstOr_AstAnd(self, parent, node: AstOr | AstAnd, state: CompileState):
        # "or/and" can have as many args as you want. they all need to be bools tho
        self.check_args([BoolType] * len(node.values), node, node.values, state)

    def visit_AstNot(self, parent, node: AstNot, state: CompileState):
        self.check_args([BoolType], node, [node.value], state)

    def check_args(
        self,
        func_args: list[FppTypeClass],
        node: Ast,
        node_args: list[AstExpr],
        state: CompileState,
    ) -> tuple[bool, CompileException]:
        if len(node_args) < len(func_args):
            state.errors.append(
                CompileException(
                    f"Missing arguments (expected {len(func_args)} found {len(node_args)})",
                    node,
                )
            )
            return
        if len(node_args) > len(func_args):
            state.errors.append(
                CompileException(
                    f"Too many arguments (expected {len(func_args)} found {len(node_args)})",
                    node,
                )
            )
            return

        for value_expr, arg_type in zip(node_args, func_args):

            value_expr_type = state.expr_types[value_expr]

            if arg_type == value_expr_type:
                # arg type is good!
                continue

            # TODO rewrite this to use a "is_convertible_to" type to type
            # "convert_type_to_type"
            # store all values as a type and the bits

            if issubclass(arg_type, value_expr_type):
                # the arg template type is more specific
                # than the arg value type

                # convert the arg value type into the arg template type
                state.expr_types[value_expr] = arg_type
            elif issubclass(value_expr_type, arg_type):
                # the arg value type is more specific
                # than the arg template type

                # the underlying function is saying it is able to handle
                # this
                pass
            else:
                # it is not. these are not compatible
                state.errors.append(
                    CompileException(
                        f"Cannot interpret {value_expr} ({value_expr_type}) as {arg_type}",
                        value_expr,
                    )
                )
                return

        # got thru all args successfully


class PickNumericLiteralTypes(CompilePass):
    def visit_AstNumber(self, parent, node: AstNumber, state: CompileState):
        expr_type = state.expr_types[node]
        # we've got a numeric literal. if we don't have a decisive type for it,
        # pick one
        if expr_type in NUMERIC_TYPES:
            # type is already "decided"
            return

        # type is undecided
        # we get to pick, based on the number
        if isinstance(node.value, int):
            assert expr_type in (NumericalType, IntegerType)
            state.expr_types[node] = I64Type
        elif isinstance(node.value, float):
            assert expr_type in (NumericalType, FloatType)
            state.expr_types[node] = F64Type


class CalculateExprValues(CompilePass):

    def visit_AstLiteral(self, parent, node: AstLiteral, state: CompileState):
        state.expr_values[node] = state.expr_types[node](node.value)

    def visit_AstGetAttr(self, parent, node: AstGetAttr, state: CompileState):
        ref = state.resolved_references[node]

        if isinstance(ref, (ChTemplate, PrmTemplate, FpyVariable)):
            # we do not try to calculate or predict these values at compile time
            expr_value = None
        elif isinstance(ref, FppType):
            # constant value
            expr_value = ref
        elif isinstance(ref, FpyCallable):
            # a reference to a callable doesn't have a value, you have to actually
            # call the func
            expr_value = NothingType()
        elif isinstance(ref, type):
            # a reference to a type doesn't have a value, and so doesn't have a type,
            # in and of itself. if this were a function call to the type's ctor then
            # it would have a value
            expr_value = NothingType()
        elif isinstance(ref, dict):
            # a ref to a namespace doesn't have a value
            expr_value = NothingType()
        else:
            assert False, ref

        state.expr_values[node] = expr_value

    def visit_AstFuncCall(self, parent, node: AstFuncCall, state: CompileState):
        func = state.resolved_references[node.func]
        assert isinstance(func, FpyCallable)
        # gather arg values
        arg_values = [
            state.expr_values[e] for e in (node.args if node.args is not None else [])
        ]
        unknown_value = any(v for v in arg_values if v is None)
        if unknown_value:
            state.expr_values[node] = None
            return

        if isinstance(func, FpyTypeCtor):
            # actually construct the type
            if issubclass(func.type, SerializableType):
                instance = func.type()
                # pass in args as a dict
                # t[0] is the arg name
                arg_dict = {t[0]: v for t, v in zip(func.type.MEMBER_LIST, arg_values)}
                instance._val = arg_dict
                state.expr_values[node] = instance

            elif issubclass(func.return_type, ArrayType):
                state.expr_values[node] = func.return_type(arg_values)

            elif func.return_type == TimeType:
                state.expr_values[node] = TimeType(*arg_values)

            else:
                # no other FppTypeClasses have ctors
                assert False, func.return_type
        else:
            # don't try to calculate the value of this function call
            # it's something like a cmd or builtin
            state.expr_values[node] = None

    def visit_AstTest(self, parent, node: AstTest, state: CompileState):
        # we do not calculate compile time value of or/and/nots/cmps at the moment
        state.expr_values[node] = None


class CheckVariableValues(CompilePass):

    def visit_AstAssign(self, parent, node: AstAssign, state: CompileState):
        existing_var = state.lookup_variable(node.variable.value, node)
        # should already have been put in var table
        assert existing_var is not None

        # we should have type info about the variable
        assert existing_var.type is not None

        value_type = state.expr_types[node.value]
        value = state.expr_values[node.value]

        if value is None:
            # expr value is unknown at this point in compile
            state.errors.append(
                CompileException(
                    f"Cannot assign {node.variable.value}: {existing_var.type} to {node.value}, as its value was not known at compile time",
                    node.value,
                )
            )
            return

        assert isinstance(value, value_type), (value, value_type)

        if isinstance(value, NothingType):
            # expr is known to have no value
            state.errors.append(
                CompileException(
                    f"Cannot assign {node.variable.value}: {existing_var.type} to {node.value}, because the rhs has no value",
                    node.value,
                )
            )
            return

        if value.getMaxSize() > MAX_SERIALIZABLE_REGISTER_SIZE:
            state.errors.append(
                CompileException(
                    f"{existing_var.type} is too big to fit in a variable", node
                )
            )
            return

        sreg_idx = existing_var.sreg_idx
        if sreg_idx is None:
            # doesn't have an sreg idx, allocate one
            sreg_idx = state.next_sreg
            state.next_sreg += 1
            existing_var.sreg_idx = sreg_idx
        state.directives[node] = [SetSerRegDirective(sreg_idx, value.serialize())]


class CreateConstantCommands(CompilePass):
    def visit_AstFuncCall(self, parent, node: AstFuncCall, state: CompileState):
        func = state.resolved_references[node.func]
        if isinstance(func, FpyCmd):
            arg_bytes = bytes()
            for arg_node in node.args if node.args is not None else []:
                arg_value = state.expr_values[arg_node]
                if arg_value is None:
                    state.errors.append(
                        CompileException(
                            f"Only constant arguments to commands are allowed", arg_node
                        )
                    )
                    return
                arg_bytes += arg_value.serialize()
            state.directives[node] = [CmdDirective(func.cmd.get_op_code(), arg_bytes)]
        else:
            state.directives[node] = None


def put_sreg_in_nreg(sreg_idx: int, nreg_idx: int, size: int) -> list[Directive]:
    if size > 4:
        return [DeserSerReg8Directive(sreg_idx, 0, nreg_idx)]
    elif size > 2:
        return [DeserSerReg4Directive(sreg_idx, 0, nreg_idx)]
    elif size > 1:
        return [DeserSerReg2Directive(sreg_idx, 0, nreg_idx)]
    elif size == 1:
        return [DeserSerReg1Directive(sreg_idx, 0, nreg_idx)]
    else:
        assert False, size


class AssignExprRegisters(CompilePass):
    def visit_AstExpr(self, parent, node: AstExpr, state: CompileState):
        state.expr_registers[node] = state.next_register
        state.next_register += 1


class PutConstExprsInRegisters(CompilePass):
    def visit_AstExpr(self, parent, node: AstExpr, state: CompileState):
        expr_type = state.expr_types[node]

        if node in state.directives:
            # already have directives associated with this node
            return

        if expr_type == NothingType:
            # impossible. nothing type has no value
            state.directives[node] = None
            return

        if expr_type.getMaxSize() > 8:
            # bigger than 8 bytes
            # impossible. can't fit in a register
            state.directives[node] = None
            return

        # okay, it is not nothing and it is smaller than 8 bytes.
        # should be able to put it in a reg

        register = state.expr_registers[node]

        expr_value = state.expr_values[node]

        if expr_value is None:
            return

        # it has a constant value at compile time
        serialized_expr_value = expr_value.serialize()
        assert len(serialized_expr_value) <= 8, len(serialized_expr_value)
        val_as_i64_bytes = bytes(8 - len(serialized_expr_value))
        val_as_i64_bytes += serialized_expr_value

        # reinterpret as an I64
        val_as_i64 = I64Type()
        val_as_i64.deserialize(val_as_i64_bytes, 0)

        state.directives[node] = [SetRegDirective(register, val_as_i64.val)]


class PutNonConstExprsInRegisters(CompilePass):

    def visit_AstReference(self, parent, node: AstReference, state: CompileState):
        if node in state.directives:
            # already know how to put it in reg, or it is impossible
            return

        expr_type = state.expr_types[node]
        ref = state.resolved_references[node]

        directives = []

        # does not have a constant compile time value

        # all references that don't have a compile time value have to go into an sreg first
        # and then into an nreg

        sreg_idx = None

        if isinstance(ref, FpyVariable):
            # already in an sreg
            sreg_idx = ref.sreg_idx
        else:
            sreg_idx = state.next_sreg
            state.next_sreg += 1

            if isinstance(ref, ChTemplate):
                tlm_time_sreg_idx = state.next_sreg
                state.next_sreg += 1
                directives.append(
                    GetTlmDirective(sreg_idx, tlm_time_sreg_idx, ref.get_id())
                )

            elif isinstance(ref, PrmTemplate):
                directives.append(GetPrmDirective(sreg_idx, ref.get_id()))

            else:
                assert (
                    False
                ), ref  # ref should either be impossible to put in a reg or should have a compile time val

        # pull from sreg into nreg
        directives.extend(
            put_sreg_in_nreg(
                sreg_idx, state.expr_registers[node], expr_type.getMaxSize()
            )
        )

        state.directives[node] = directives

    def visit_AstAnd_AstOr(self, parent, node: AstAnd | AstOr, state: CompileState):
        if node in state.directives:
            # already know how to put it in reg, or know that it's impossible
            return

        expr_reg = state.expr_registers[node]
        directives = []

        registers_to_compare = []
        for arg_value_expr in node.values:
            arg_value_dirs = state.directives[arg_value_expr]
            assert arg_value_dirs is not None
            directives.extend(arg_value_dirs)
            registers_to_compare.append(state.expr_registers[arg_value_expr])

        assert len(registers_to_compare) >= 2, len(registers_to_compare)

        # okay, now we have to "or" or "and" together all of the registers
        # "or/and" the first two together, put in res.
        # from then on, "or/and" the next with res

        dir_type = OrDirective if isinstance(node, AstOr) else AndDirective

        directives.append(
            dir_type(registers_to_compare[0], registers_to_compare[1], expr_reg)
        )

        for i in range(2, len(registers_to_compare)):
            directives.append(dir_type(expr_reg, registers_to_compare[i], expr_reg))

        state.directives[node] = directives

    def visit_AstNot(self, parent, node: AstNot, state: CompileState):
        if node in state.directives:
            # already know how to put it in reg
            return

        expr_reg = state.expr_registers[node]
        directives = []
        arg_value_dirs = state.directives[node.value]
        assert arg_value_dirs is not None
        directives.extend(arg_value_dirs)
        directives.append(NotDirective(state.expr_registers[node.value], expr_reg))

        state.directives[node] = directives

    def visit_AstComparison(self, parent, node: AstComparison, state: CompileState):
        if node in state.directives:
            # already know how to put it in reg
            return

        directives = []

        lhs_type = state.expr_types[node.lhs]
        rhs_type = state.expr_types[node.rhs]

        lhs_reg = state.expr_registers[node.lhs]
        rhs_reg = state.expr_registers[node.rhs]
        res_reg = state.expr_registers[node]

        directives.extend(state.directives[node.lhs])
        directives.extend(state.directives[node.rhs])

        if node.op.value == "==":
            directives.append(EqualDirective(lhs_reg, rhs_reg, res_reg))
        elif node.op.value == "!=":
            directives.append(NotEqualDirective(lhs_reg, rhs_reg, res_reg))
        else:
            signed = False
            if lhs_type in SIGNED_INTEGER_TYPES or rhs_type in SIGNED_INTEGER_TYPES:
                # if either is signed, promote both to signed
                signed = True

            if signed:
                dir_type = SIGNED_INEQUALITY_DIRECTIVES[node.op.value]
            else:
                dir_type = UNSIGNED_INEQUALITY_DIRECTIVES[node.op.value]

            directives.append(dir_type(lhs_reg, rhs_reg, res_reg))

        state.directives[node] = directives


class CountDirectives(CompilePass):

    def visit_AstIf(self, parent, node: AstIf, state: CompileState):
        count = 0
        # include the condition
        count += state.node_dir_counts[node.condition]
        # include if stmt
        count += 1
        # include body
        count += state.node_dir_counts[node.body]
        # include a goto end of if
        count += 1

        if node.elifs is not None:
            count += state.node_dir_counts[node.elifs]
        if node.els is not None:
            count += state.node_dir_counts[node.els]

        state.node_dir_counts[node] = count

    def visit_AstElifs(self, parent, node: AstElifs, state: CompileState):
        count = 0
        for case in node.cases:
            count += state.node_dir_counts[case]

        state.node_dir_counts[node] = count

    def visit_AstElif(self, parent, node: AstElif, state: CompileState):
        count = 0
        # include the condition
        count += state.node_dir_counts[node.condition]
        # include if stmt
        count += 1
        # include body
        count += state.node_dir_counts[node.body]
        # include a goto end of if
        count += 1

        state.node_dir_counts[node] = count

    def visit_AstBody(
        self, parent, node: AstUnscopedBody | AstScopedBody, state: CompileState
    ):
        count = 0
        for stmt in node.stmts:
            count += state.node_dir_counts[stmt]

        state.node_dir_counts[node] = count

    def visit_default(self, parent, node, state):
        state.node_dir_counts[node] = (
            len(state.directives[node]) if state.directives.get(node) is not None else 0
        )


class CalculateStartLineIdx(TopDownCompilePass):
    def visit_AstBody(
        self, parent, node: AstUnscopedBody | AstScopedBody, state: CompileState
    ):
        if parent is None:
            state.start_line_idx[node] = 0

        start_idx = state.start_line_idx[node]

        line_idx = start_idx
        for stmt in node.stmts:
            state.start_line_idx[stmt] = line_idx
            line_idx += state.node_dir_counts[stmt]

    def visit_AstIf(self, parent, node: AstIf, state: CompileState):
        line_idx = state.start_line_idx[node]
        state.start_line_idx[node.condition] = line_idx
        line_idx += state.node_dir_counts[node.condition]
        # include if stmt
        line_idx += 1
        state.start_line_idx[node.body] = line_idx
        line_idx += state.node_dir_counts[node.body]
        # include goto stmt
        line_idx += 1
        if node.elifs is not None:
            state.start_line_idx[node.elifs] = line_idx
            line_idx += state.node_dir_counts[node.elifs]
        if node.els is not None:
            state.start_line_idx[node.els] = line_idx
            line_idx += state.node_dir_counts[node.els]

    def visit_AstElifs(self, parent, node: AstElifs, state: CompileState):
        line_idx = state.start_line_idx[node]
        for case in node.cases:
            state.start_line_idx[case] = line_idx
            line_idx += state.node_dir_counts[case]

    def visit_AstElif(self, parent, node: AstElif, state: CompileState):
        line_idx = state.start_line_idx[node]
        state.start_line_idx[node.condition] = line_idx
        line_idx += state.node_dir_counts[node.condition]
        # include if dir
        line_idx += 1
        state.start_line_idx[node.body] = line_idx
        line_idx += state.node_dir_counts[node.body]
        # include a goto end of if
        line_idx += 1


class CollectDirectives(CompilePass):

    def visit_AstIf(self, parent, node: AstIf, state: CompileState):
        start_line_idx = state.start_line_idx[node]

        all_dirs = []

        cases: list[tuple[AstExpr, AstUnscopedBody]] = []
        goto_ends: list[GotoDirective] = []

        cases.append((node.condition, node.body))

        if node.elifs is not None:
            for case in node.elifs.cases:
                cases.append((case.condition, case.body))

        for case in cases:
            case_dirs = []
            # include the condition
            case_dirs.extend(state.directives[case[0]])
            # include if stmt (update the end idx later)
            if_dir = IfDirective(state.expr_registers[case[0]], -1)

            case_dirs.append(if_dir)
            # include body
            case_dirs.extend(state.directives[case[1]])
            # include a temporary goto end of if, will be refined later
            goto_dir = GotoDirective(-1)
            case_dirs.append(goto_dir)
            goto_ends.append(goto_dir)

            # if false, skip the body and goto
            if_dir.false_goto_stmt_index = (
                start_line_idx + len(all_dirs) + len(case_dirs)
            )

            all_dirs.extend(case_dirs)

        if node.els is not None:
            all_dirs.extend(state.directives[node.els])

        for goto in goto_ends:
            goto.statement_index = start_line_idx + len(all_dirs)

        state.directives[node] = all_dirs

    def visit_AstBody(
        self, parent, node: AstUnscopedBody | AstScopedBody, state: CompileState
    ):
        dirs = []
        for stmt in node.stmts:
            stmt_dirs = state.directives.get(stmt, None)
            if stmt_dirs is not None:
                dirs.extend(stmt_dirs)

        state.directives[node] = dirs


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

    callable_name_dict = {}
    for name, cmd in cmd_name_dict.items():
        cmd: CmdTemplate
        args = []
        for arg_name, _, arg_type in cmd.arguments:
            args.append((arg_name, arg_type))
        callable_name_dict[name] = FpyCmd(NothingType, args, cmd)

    infix_callable_name_dict = defaultdict(list)

    for op, dir in BINARY_COMPARISON_DIRECTIVES.items():
        infix_callable_name_dict[op] = FpyOperator(
            BoolType, [("lhs", NumericalType), ("rhs", NumericalType)], op, dir
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

        callable_name_dict[name] = FpyTypeCtor(typ, args, typ)

    combined_dict = {}
    combined_dict.update(ch_name_dict)
    combined_dict.update(prm_name_dict)
    combined_dict.update(enum_consts)
    combined_dict.update(type_name_dict)
    combined_dict.update(callable_name_dict)
    combined_dict.update(infix_callable_name_dict)
    ns = create_namespaces(combined_dict)

    state = CompileState(
        ns
    )
    return state


def compile(body: AstScopedBody, dictionary: str) -> list[Directive]:
    state = get_base_compile_state(dictionary)
    passes: list[CompilePass] = [
        AssignIds(),
        # TODO delete this
        CreateScopes(),
        # might want to error if you're overriding smth from the dict
        CreateVariables(),
        # now that variables have been defined, try resolving references
        # again and fail if anything isn't found
        ResolveReferencesByName(),
        CalculateExprTypes(),
        # okay, we know what all the different names could be pointing to,
        # at least according to the name of the symbol.
        # but in the case of polymorphic functions, multiple funcs can have
        # the same name. let's use arg types to figure out which one we're calling
        CheckAndResolveArgumentTypes(),
        PickNumericLiteralTypes(),
        # now we know what each call points to
        CalculateExprValues(),
        CheckVariableValues(),
        AssignExprRegisters(),
        CreateConstantCommands(),
        PutConstExprsInRegisters(),
        PutNonConstExprsInRegisters(),
        CountDirectives(),
        CalculateStartLineIdx(),
        CollectDirectives(),
    ]

    for compile_pass in passes:
        compile_pass.run(body, state)
        for error in state.errors:
            raise error

    print(
        "\n".join(
            str(idx) + ": " + str(s) for idx, s in enumerate(state.directives[body])
        )
    )

    return state.directives[body]


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("input", type=Path, help="The input .fpy file")
    arg_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=False,
        default=None,
        help="The output .bin path",
    )
    arg_parser.add_argument(
        "-d",
        "--dictionary",
        type=Path,
        required=True,
        help="The FPrime dictionary .json file",
    )

    args = arg_parser.parse_args()

    if not args.input.exists():
        print(f"Input file {args.input} does not exist")
        exit(-1)

    print(args.input.read_text())

    body = parse(args.input.read_text())
    directives = compile(body, args.dictionary)
    output = args.output
    if output is None:
        output = args.input.with_suffix(".bin")
    serialize_directives(directives, output)
