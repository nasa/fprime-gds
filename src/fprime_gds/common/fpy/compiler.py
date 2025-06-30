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
    FLOAT_INEQUALITY_DIRECTIVES,
    INT_EQUALITY_DIRECTIVES,
    MAX_SERIALIZABLE_REGISTER_SIZE,
    INT_SIGNED_INEQUALITY_DIRECTIVES,
    INT_UNSIGNED_INEQUALITY_DIRECTIVES,
    AndDirective,
    CmdDirective,
    DeserSerReg1Directive,
    DeserSerReg2Directive,
    DeserSerReg4Directive,
    DeserSerReg8Directive,
    Directive,
    EqualDirective,
    ExitDirective,
    FloatEqualDirective,
    FloatNotEqualDirective,
    GetPrmDirective,
    GetTlmDirective,
    GotoDirective,
    IfDirective,
    NotDirective,
    NotEqualDirective,
    OrDirective,
    SetSerRegDirective,
    SetRegDirective,
    WaitAbsDirective,
    WaitRelDirective,
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
    AstGetItem,
    AstNot,
    AstNumber,
    AstOr,
    AstReference,
    AstStmt,
    AstString,
    Ast,
    AstTest,
    AstBody,
    AstLiteral,
    AstIf,
    AstAssign,
    AstFuncCall,
    AstVar,
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

    def from_arg_values(self, arg_vals: list[FppType]) -> Directive:
        assert len(arg_vals) == len(fields(self.dir))
        arg_vals = [v.val for v in arg_vals]
        return self.dir(*arg_vals)


BUILTINS: dict[str, FpyBuiltin] = {
    "sleep": FpyBuiltin(
        NothingType, [("seconds", U32Type), ("useconds", U32Type)], WaitRelDirective
    ),
    "sleep_until": FpyBuiltin(
        NothingType, [("wakeup_time", TimeType)], WaitAbsDirective
    ),
    "exit": FpyBuiltin(NothingType, [("success", BoolType)], ExitDirective),
}


@dataclass
class FpyTypeCtor(FpyCallable):
    type: FppTypeClass


@dataclass
class FpyOperator(FpyCallable):
    op: str
    directive: type[Directive]


@dataclass
class FieldReference:
    parent: "FpyReference"
    type: FppTypeClass
    offset: int
    name: str = None
    idx: int = None

    def get_from(self, parent_val: FppType) -> FppType:
        assert isinstance(parent_val, self.type)
        assert self.name is not None or self.idx is not None
        value = None
        if self.name is not None:
            if isinstance(parent_val, SerializableType):
                value = parent_val.val[self.name]
            elif isinstance(parent_val, TimeType):
                if self.name == "seconds":
                    value = parent_val.__secs
                elif self.name == "useconds":
                    value = parent_val.__usecs
                elif self.name == "time_base":
                    value = parent_val.__timeBase
                elif self.name == "time_context":
                    value = parent_val.__timeContext
                else:
                    assert False, self.name
            else:
                assert False, parent_val

        else:

            assert isinstance(parent_val, ArrayType), parent_val

            value = parent_val._val[self.idx]

        assert isinstance(value, self.type), (value, self.type)
        return value


# named variables can be tlm chans, prms, callables, or directly referenced consts (usually enums)
@dataclass
class FpyVariable:
    type_ref: AstExpr
    type: FppTypeClass | None = None
    """type of the variable. None if type unsure at the moment"""
    sreg_idx: int | None = None
    """the index of the sreg it is stored in"""


FpyNamespace = dict[str, "FpyReference"]


def create_namespace(
    references: dict[str, "FpyReference"],
) -> FpyNamespace:

    base = {}

    for fqn, ref in references.items():
        names_strs = fqn.split(".")

        ns = base
        while len(names_strs) > 1:
            existing_child = ns.get(names_strs[0], None)
            if existing_child is None:
                # this namespace is not defined atm
                existing_child = {}
                ns[names_strs[0]] = existing_child

            if not isinstance(existing_child, dict):
                # something else already has this name
                print(
                    f"WARNING: {fqn} is already defined as {existing_child}, tried to redefine it as {ref}"
                )
                break

            ns = existing_child
            names_strs = names_strs[1:]

        if len(names_strs) != 1:
            # broke early. skip this loop
            continue

        # okay, now ns is the complete namespace of the attribute
        # i.e. everything up until the last '.'
        name = names_strs[0]

        existing_child = ns.get(name, None)

        if existing_child is not None:
            # uh oh, something already had this name with a diff value
            print(
                f"WARNING: {fqn} is already defined as {existing_child}, tried to redefine it as {ref}"
            )
            continue

        ns[name] = ref

    return base


def union_namespace(lhs: FpyNamespace, rhs: FpyNamespace) -> FpyNamespace:
    lhs_keys = set(lhs.keys())
    rhs_keys = set(rhs.keys())
    common_keys = lhs_keys.intersection(rhs_keys)

    only_lhs_keys = lhs_keys.difference(common_keys)
    only_rhs_keys = rhs_keys.difference(common_keys)

    new = FpyNamespace()

    for key in common_keys:
        if not isinstance(lhs[key], dict) or not isinstance(rhs[key], dict):
            # cannot be merged cleanly. one of the two is not a namespace
            print(f"WARNING: {key} is defined as {lhs[key]}, ignoring {rhs[key]}")
            new[key] = lhs[key]
            continue

        new[key] = union_namespace(lhs[key], rhs[key])

    for key in only_lhs_keys:
        new[key] = lhs[key]
    for key in only_rhs_keys:
        new[key] = rhs[key]

    return new


FpyReference = (
    ChTemplate
    | PrmTemplate
    | FppType
    | FpyCallable
    | FppTypeClass
    | FpyVariable
    | FieldReference
    | dict  # FpyReference
)


def get_ref_fpp_type_class(ref: FpyReference) -> FppTypeClass:
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
    elif isinstance(ref, FieldReference):
        result_type = ref.type
    elif isinstance(ref, dict):
        # reference to a namespace. namespaces don't have values
        result_type = NothingType
    else:
        assert False, ref

    return result_type


@dataclass
class CompileState:
    types: FpyNamespace
    callables: FpyNamespace
    tlms: FpyNamespace
    prms: FpyNamespace
    consts: FpyNamespace
    variables: FpyNamespace = field(default_factory=dict)
    runtime_values: FpyNamespace = None

    def __post_init__(self):
        self.runtime_values = union_namespace(
            self.tlms,
            union_namespace(self.prms, union_namespace(self.consts, self.variables)),
        )

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

    def err(self, msg, n):
        self.errors.append(CompileException(msg, n))


class Visitor:

    def _find_custom_visit_func(self, node: Ast):
        for name, func in inspect.getmembers(type(self), inspect.isfunction):
            if not name.startswith("visit") or name == "visit_default":
                # not a visitor, or the default visit func
                continue
            signature = inspect.signature(func)
            params = list(signature.parameters.values())
            assert len(params) == 3
            assert params[1].annotation is not None
            if isinstance(node, params[1].annotation):
                return func
        else:
            # call the default
            return type(self).visit_default

    def _visit(self, node: Ast, state: CompileState):
        visit_func = self._find_custom_visit_func(node)
        visit_func(self, node, state)

    def visit_default(self, node: Ast, state: CompileState):
        pass

    def run(self, start: Ast, state: CompileState):
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
                if len(state.errors) != 0:
                    break
                self._visit(child, state)
                if len(state.errors) != 0:
                    break

        _descend(start)
        self._visit(start, state)


class TopDownVisitor(Visitor):

    def run(self, start: Ast, state: CompileState):
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
                self._visit(child, state)
                if len(state.errors) != 0:
                    break
                _descend(child)
                if len(state.errors) != 0:
                    break

        self._visit(start, state)
        _descend(start)


class AssignIds(TopDownVisitor):

    def __init__(self):
        self.next_id = 0

    def visit_default(self, node, state):
        node.id = self.next_id
        self.next_id += 1


class CreateVariables(Visitor):

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        existing = state.variables.get(node.variable.var, None)
        if not existing:
            # idk what this var is. make sure it's a valid declaration
            if node.var_type is None:
                # error because this isn't an annotated assignment. right now all declarations must be annotated
                state.err(
                    "Must provide a type annotation for new variables", node.variable
                )
                return

            var = FpyVariable(node.var_type, None)
            # new var. put it in the table under this scope
            state.variables[node.variable.var] = var
            state.runtime_values[node.variable.var] = var

        if existing and node.var_type is not None:
            # redeclaring an existing variable
            state.err(f"{node.variable.var} already declared", node)
            return


class ResolveReferences(Visitor):

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

    def get_attr_of_ref(
        self, parent: FpyReference, node: AstGetAttr, state: CompileState
    ) -> FpyReference | None:

        if isinstance(parent, (FpyCallable, type)):
            # right now we don't support resolving something after a callable/type/var
            state.err("Invalid syntax", node)
            return None

        if isinstance(parent, dict):
            # parent is a namespace
            attr = parent.get(node.attr, None)
            if attr is None:
                state.err("Unknown attribute", node)
                return None
            return attr

        # parent is a ch, prm, const or field

        value_type = get_ref_fpp_type_class(parent)

        assert value_type != NothingType

        if not issubclass(value_type, (SerializableType, TimeType)):
            # trying to do arr.x, but arr is not a struct
            state.err(
                "Invalid syntax (tried to access named member of a non-struct type)",
                node,
            )
            return None

        if not self.is_type_constant_size(value_type):
            state.err(
                f"{value_type} has non-constant sized members, cannot access members",
                node,
            )
            return None

        member_list: list[tuple[str, FppTypeClass]] = None
        if issubclass(value_type, SerializableType):
            member_list = [t[0:2] for t in value_type.MEMBER_LIST]
        else:
            # if it is a time type, there are some "implied" members
            member_list = []
            member_list.append(("time_base", U16Type))
            member_list.append(("time_context", U8Type))
            member_list.append(("seconds", U32Type))
            member_list.append(("useconds", U32Type))

        offset = 0
        for arg_name, arg_type in member_list:
            if arg_name == node.attr:
                return FieldReference(parent, arg_type, offset)
            offset += arg_type.getMaxSize()

        state.err(f"Unknown member {node.attr}", node)
        return None

    def get_item_of_ref(
        self, parent: FpyReference, node: AstGetItem, state: CompileState
    ) -> FpyReference | None:

        if isinstance(parent, (FpyCallable, type, dict)):
            # right now we don't support resolving index after a callable/type/var
            state.err("Invalid syntax", node)
            return None

        # parent is a ch, prm, const or field

        value_type = get_ref_fpp_type_class(parent)

        assert value_type != NothingType

        if not issubclass(value_type, ArrayType):
            # trying to do struct[0], but struct is not an array
            state.err(
                "Invalid syntax (tried to access indexed member of a non-array type)",
                node.item,
            )
            return None

        if not self.is_type_constant_size(value_type):
            state.err(
                f"{value_type} has non-constant sized members, cannot access members",
                node,
            )
            return None

        offset = 0
        for i in range(0, value_type.LENGTH):
            if i == node.item.value:
                return FieldReference(parent, value_type.MEMBER_TYPE, offset)
            offset += value_type.MEMBER_TYPE.getMaxSize()

        state.err(
            f"Array access out-of-bounds (access: {node.item}, array size: {value_type.LENGTH})",
            node.item,
        )
        return None

    def try_resolve_expr_in_ns(
        self, node: AstExpr, ns: FpyNamespace, state: CompileState
    ) -> bool:
        if not isinstance(node, AstReference):
            return True

        return self.resolve_in_ns(node, ns, state) is not None

    def resolve_in_ns(
        self, node: AstExpr, ns: FpyNamespace, state: CompileState
    ) -> FpyReference | None:
        if isinstance(node, AstVar):
            if not isinstance(ns, dict):
                state.err("Invalid syntax", node)
                return None
            ref = ns.get(node.var, None)
            if ref is None:
                state.err("Unknown variable", node)
                return None
            state.resolved_references[node] = ref
            return ref

        parent = self.resolve_in_ns(node.parent, ns, state)
        if parent is None:
            # couldn't resolve parent
            return None

        if isinstance(node, AstGetItem):
            ref = self.get_item_of_ref(parent, node, state)
            state.resolved_references[node] = ref
            return ref

        assert isinstance(node, AstGetAttr)
        ref = self.get_attr_of_ref(parent, node, state)
        state.resolved_references[node] = ref
        return ref

    def visit_AstFuncCall(self, node: AstFuncCall, state: CompileState):
        # function refs must be callables
        if not self.resolve_in_ns(node.func, state.callables, state):
            return

        for arg in node.args if node.args is not None else []:
            # arg value refs must be consts
            if not self.try_resolve_expr_in_ns(arg, state.consts, state):
                return

    def visit_AstIf(self, node: AstIf, state: CompileState):
        # if condition expr refs must be "runtime values" (tlm/prm/const/etc)
        if not self.try_resolve_expr_in_ns(node.condition, state.runtime_values, state):
            return

    def visit_AstElif(self, node: AstElif, state: CompileState):
        # elif condition expr refs must be "runtime values" (tlm/prm/const/etc)
        if not self.try_resolve_expr_in_ns(node.condition, state.runtime_values, state):
            return

    def visit_AstComparison(self, node: AstComparison, state: CompileState):
        # lhs/rhs side of comparison, if they are refs, must be refs to "runtime vals"
        if not self.try_resolve_expr_in_ns(node.lhs, state.runtime_values, state):
            return
        if not self.try_resolve_expr_in_ns(node.rhs, state.runtime_values, state):
            return

    def visit_AstAnd_AstOr(self, node: AstAnd | AstOr, state: CompileState):
        for val in node.values:
            if not self.try_resolve_expr_in_ns(val, state.runtime_values, state):
                return

    def visit_AstNot(self, node: AstNot, state: CompileState):
        if not self.try_resolve_expr_in_ns(node.value, state.runtime_values, state):
            return

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        var = self.resolve_in_ns(node.variable, state.variables, state)
        if not var:
            return

        if node.var_type is not None:
            type = self.resolve_in_ns(node.var_type, state.types, state)
            if not type:
                return
            var.type = type

        if not self.try_resolve_expr_in_ns(node.value, state.consts, state):
            return


class CalculateExprTypes(Visitor):

    def visit_AstNumber(self, node: AstNumber, state: CompileState):
        if isinstance(node.value, float):
            result_type = FloatType
        elif isinstance(node.value, int):
            result_type = IntegerType
        else:
            assert False, node.value
        state.expr_types[node] = result_type

    def visit_AstString(self, node: AstString, state: CompileState):
        state.expr_types[node] = StringType

    def visit_AstBoolean(self, node: AstBoolean, state: CompileState):
        state.expr_types[node] = BoolType

    def visit_AstReference(self, node: AstReference, state: CompileState):
        ref = state.resolved_references[node]
        state.expr_types[node] = get_ref_fpp_type_class(ref)

    def visit_AstFuncCall(self, node: AstFuncCall, state: CompileState):
        ref = state.resolved_references[node.func]
        assert isinstance(ref, FpyCallable)
        state.expr_types[node] = ref.return_type

    def visit_AstOr_AstAnd_AstNot_AstComparison(
        self, node: AstOr | AstAnd | AstNot | AstComparison, state: CompileState
    ):
        state.expr_types[node] = BoolType

    def visit_default(self, node, state):
        # coding error, missed an expr
        assert not isinstance(node, AstExpr), node


class CheckAndResolveArgumentTypes(Visitor):

    def is_convertible_to(self, from_type: FppTypeClass, to_type: FppTypeClass) -> bool:
        if from_type == to_type:
            return True

        if issubclass(from_type, StringType) and issubclass(to_type, StringType):
            if from_type == StringType or to_type == StringType:
                # from a "generic" string to either a generic string or specific one

                # or from a "specific" string to a generic one
                return True
            return False

        if issubclass(from_type, NumericalType) and issubclass(to_type, NumericalType):

            if issubclass(from_type, IntegerType):
                # ints can be converted to larger ints or floats
                if from_type == IntegerType:
                    # it is a "generic" int. can turn into any type we want
                    return True

                if issubclass(to_type, FloatType):
                    return True

                if from_type.getMaxSize() < to_type.getMaxSize():
                    # going to a larger type
                    return True

                return False

            assert issubclass(from_type, FloatType), from_type

            # float type cannot be converted to int
            if issubclass(to_type, IntegerType):
                return False

            if from_type == FloatType:
                # generic float can be converted to any float
                return True

            # f64 cannot be converted to f32
            if from_type.getMaxSize() > to_type.getMaxSize():
                return False

            return True

        return False

    def visit_AstComparison(self, node: AstComparison, state: CompileState):

        lhs_type = state.expr_types[node.lhs]
        rhs_type = state.expr_types[node.rhs]

        if not issubclass(lhs_type, NumericalType):
            state.err(f"Cannot compare non-numeric type {lhs_type}", node.lhs)
            return
        if not issubclass(rhs_type, NumericalType):
            state.err(f"Cannot compare non-numeric type {rhs_type}", node.rhs)
            return

        # args are both numeric
        # if one is a float, both must be fp values because we only have fp-fp comparisons rn

        fp_cmp = issubclass(lhs_type, FloatType) or issubclass(rhs_type, FloatType)

        if fp_cmp:
            if not issubclass(lhs_type, FloatType) or not issubclass(
                rhs_type, FloatType
            ):
                state.err(
                    f"Cannot compare non-floats with floats ({lhs_type} with {rhs_type})",
                    node,
                )
                return

            # if both are generic float types, pick F64
            if lhs_type == FloatType and rhs_type == FloatType:
                state.expr_types[node.lhs] = F64Type
                state.expr_types[node.rhs] = F64Type
                # good2go
                return
            if lhs_type == FloatType:
                # use rhs type
                state.expr_types[node.lhs] = state.expr_types[node.rhs]
                return
            if rhs_type == FloatType:
                # use lhs type
                state.expr_types[node.rhs] = state.expr_types[node.lhs]
                return
            if lhs_type == rhs_type:
                return
            # don't support this at the moment... need to convert f32 to f64
            state.err("Cannot compare F32 to F64", node)
            return

        # in integer comparisons, we can compare any type to any other type

        # are they both generic?
        if lhs_type == IntegerType and rhs_type == IntegerType:
            # use i64
            state.expr_types[node.lhs] = I64Type
            state.expr_types[node.rhs] = I64Type
            return
        if lhs_type == IntegerType:
            # use rhs type
            state.expr_types[node.lhs] = state.expr_types[node.rhs]
        if rhs_type == IntegerType:
            # use lhs type
            state.expr_types[node.rhs] = state.expr_types[node.lhs]
        # otherwise, they are both "specific" integer types. user beware
        # if you're doing some weird cmp between signed vs unsigned
        return

    def visit_AstFuncCall(self, node: AstFuncCall, state: CompileState):
        func = state.resolved_references[node.func]
        func_args = func.args
        node_args = node.args if node.args else []

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

        for value_expr, arg in zip(node_args, func_args):
            arg_name, arg_type = arg

            value_expr_type = state.expr_types[value_expr]

            if self.is_convertible_to(value_expr_type, arg_type):
                # arg type is good!
                state.expr_types[value_expr] = arg_type
                continue

            # it is not. these are not compatible
            state.errors.append(
                CompileException(
                    f"Cannot convert {value_expr} ({value_expr_type}) to {arg_type}",
                    value_expr,
                )
            )
            return

        # got thru all args successfully

    def visit_AstOr_AstAnd(self, node: AstOr | AstAnd, state: CompileState):
        # "or/and" can have as many args as you want. they all need to be bools tho
        for val in node.values:
            val_type = state.expr_types[val]
            if not self.is_convertible_to(val_type, BoolType):
                state.err(f"Arguments to 'and'/'or' must be booleans", val)
                return

    def visit_AstNot(self, node: AstNot, state: CompileState):
        val_type = state.expr_types[node.value]
        if not self.is_convertible_to(val_type, BoolType):
            state.err(f"Argument to 'not' must be boolean", node.value)
            return


class PickNumericLiteralTypes(Visitor):

    def try_interpret_literal_as(
        self, node: AstExpr, type: FppTypeClass, state: CompileState
    ) -> bool:
        if not isinstance(node, AstLiteral):
            return True

        # it is a literal. can it be assigned
        expr_type = state.expr_types[node]

        if expr_type == type:
            return True

        # we've got a numeric literal. if we don't have a decisive type for it,
        # pick one
        if expr_type in NUMERIC_TYPES:
            # type is already "decided" as something else
            return False

        # type is undecided
        # we get to pick, based on the number
        if isinstance(node.value, int):
            assert expr_type in (NumericalType, IntegerType)
            if type in INTEGER_TYPES:
                state.expr_types[node] = type
                return True
            else:
                return False

        elif isinstance(node.value, float):
            assert expr_type in (NumericalType, FloatType)
            if type in FLOAT_TYPES:
                state.expr_types[node] = type
                return True
            else:
                return False

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        var_type = state.resolved_references[node.variable].type
        if not self.try_interpret_literal_as(node.value, var_type, state):
            state.err(f"Cannot interpret {node.value} as {var_type}", node.value)
            return

    def visit_AstGetItem(self, node: AstGetItem, state: CompileState):
        self.try_interpret_literal_as(node.item, I64Type, state)


class CalculateExprValues(Visitor):

    def visit_AstLiteral(self, node: AstLiteral, state: CompileState):
        state.expr_values[node] = state.expr_types[node](node.value)

    def visit_AstReference(self, node: AstReference, state: CompileState):
        ref = state.resolved_references[node]

        if isinstance(ref, (ChTemplate, PrmTemplate, FpyVariable)):
            # we do not try to calculate or predict these values at compile time
            expr_value = None
        elif isinstance(ref, FieldReference):
            if isinstance(ref.parent, FppType):
                # ref to a field of a constant
                # get the field
                expr_value = ref.get_from(ref.parent)
            else:
                # ref to a field of smth else. no runtime val
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

    def visit_AstFuncCall(self, node: AstFuncCall, state: CompileState):
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

    def visit_AstTest(self, node: AstTest, state: CompileState):
        # we do not calculate compile time value of or/and/nots/cmps at the moment
        state.expr_values[node] = None

    def visit_default(self, node, state):
        # coding error, missed an expr
        assert not isinstance(node, AstExpr), node


class CheckVariableValues(Visitor):

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        existing_var = state.resolved_references[node.variable]
        # should already have been put in var table
        assert existing_var is not None

        # we should have type info about the variable
        assert existing_var.type is not None

        value_type = state.expr_types[node.value]
        value = state.expr_values[node.value]

        if existing_var.type != value_type:
            state.err(
                f"Cannot assign variable of type {existing_var.type} to {value_type}",
                node.value,
            )
            return

        if value is None:
            # expr value is unknown at this point in compile
            state.errors.append(
                CompileException(
                    f"Cannot assign {node.variable.var}: {existing_var.type} to {node.value}, as its value was not known at compile time",
                    node.value,
                )
            )
            return

        assert isinstance(value, value_type), (value, value_type)
        print(value, value_type)

        if isinstance(value, NothingType):
            # expr is known to have no value
            state.errors.append(
                CompileException(
                    f"Cannot assign {node.variable.var}: {existing_var.type} to {node.value}, because the rhs has no value",
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
        val_bytes = value.serialize()
        assert len(val_bytes) == value.getMaxSize()
        state.directives[node] = [SetSerRegDirective(sreg_idx, val_bytes)]


class CreateConstantCommands(Visitor):
    def visit_AstFuncCall(self, node: AstFuncCall, state: CompileState):
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
        elif isinstance(func, FpyBuiltin):
            arg_values = []
            for arg_node in node.args if node.args is not None else []:
                arg_value = state.expr_values[arg_node]
                if arg_value is None:
                    state.errors.append(
                        CompileException(
                            f"Only constant arguments to builtins are allowed", arg_node
                        )
                    )
                    return
                arg_values.append(arg_value)

            state.directives[node] = [func.from_arg_values(arg_values)]
        else:
            state.directives[node] = None


def put_sreg_in_nreg(
    sreg_idx: int, sreg_offset: int, nreg_idx: int, size: int
) -> list[Directive]:
    if size > 4:
        return [DeserSerReg8Directive(sreg_idx, sreg_offset, nreg_idx)]
    elif size > 2:
        return [DeserSerReg4Directive(sreg_idx, sreg_offset, nreg_idx)]
    elif size > 1:
        return [DeserSerReg2Directive(sreg_idx, sreg_offset, nreg_idx)]
    elif size == 1:
        return [DeserSerReg1Directive(sreg_idx, sreg_offset, nreg_idx)]
    else:
        assert False, size


class AssignExprRegisters(Visitor):
    def visit_AstExpr(self, node: AstExpr, state: CompileState):
        state.expr_registers[node] = state.next_register
        state.next_register += 1


class PutConstExprsInRegisters(Visitor):
    def visit_AstExpr(self, node: AstExpr, state: CompileState):
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
            # no const value
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


class PutNonConstExprsInRegisters(Visitor):

    def visit_AstReference(self, node: AstReference, state: CompileState):
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

        offset = 0

        if isinstance(ref, FpyVariable):
            # already in an sreg
            sreg_idx = ref.sreg_idx
        else:
            sreg_idx = state.next_sreg
            state.next_sreg += 1
            base_ref = ref

            while isinstance(base_ref, FieldReference):
                offset += base_ref.offset
                base_ref = base_ref.parent

            if isinstance(base_ref, ChTemplate):
                tlm_time_sreg_idx = state.next_sreg
                state.next_sreg += 1
                directives.append(
                    GetTlmDirective(sreg_idx, tlm_time_sreg_idx, base_ref.get_id())
                )

            elif isinstance(base_ref, PrmTemplate):
                directives.append(GetPrmDirective(sreg_idx, base_ref.get_id()))

            elif isinstance(base_ref, FpyVariable):
                # already in sreg
                sreg_idx = base_ref.sreg_idx

            else:
                assert (
                    False
                ), ref  # ref should either be impossible to put in a reg or should have a compile time val

        # pull from sreg into nreg
        directives.extend(
            put_sreg_in_nreg(
                sreg_idx, offset, state.expr_registers[node], expr_type.getMaxSize()
            )
        )

        state.directives[node] = directives

    def visit_AstAnd_AstOr(self, node: AstAnd | AstOr, state: CompileState):
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

    def visit_AstNot(self, node: AstNot, state: CompileState):
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

    def visit_AstComparison(self, node: AstComparison, state: CompileState):
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

        fp = False
        if issubclass(lhs_type, FloatType):
            assert issubclass(rhs_type, FloatType), rhs_type
            fp = True

        if node.op.value == "==":
            if fp:
                directives.append(FloatEqualDirective(lhs_reg, rhs_reg, res_reg))
            else:
                directives.append(EqualDirective(lhs_reg, rhs_reg, res_reg))
        elif node.op.value == "!=":
            if fp:
                directives.append(FloatNotEqualDirective(lhs_reg, rhs_reg, res_reg))
            else:
                directives.append(NotEqualDirective(lhs_reg, rhs_reg, res_reg))
        else:

            if fp:
                dir_type = FLOAT_INEQUALITY_DIRECTIVES[node.op.value]
            else:
                # if either is signed, consider both as signed
                signed = (
                    lhs_type in SIGNED_INTEGER_TYPES or rhs_type in SIGNED_INTEGER_TYPES
                )

                if signed:
                    dir_type = INT_SIGNED_INEQUALITY_DIRECTIVES[node.op.value]
                else:
                    dir_type = INT_UNSIGNED_INEQUALITY_DIRECTIVES[node.op.value]

            directives.append(dir_type(lhs_reg, rhs_reg, res_reg))

        state.directives[node] = directives


class CountDirectives(Visitor):

    def visit_AstIf(self, node: AstIf, state: CompileState):
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

    def visit_AstElifs(self, node: AstElifs, state: CompileState):
        count = 0
        for case in node.cases:
            count += state.node_dir_counts[case]

        state.node_dir_counts[node] = count

    def visit_AstElif(self, node: AstElif, state: CompileState):
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

    def visit_AstBody(self, node: AstBody, state: CompileState):
        count = 0
        for stmt in node.stmts:
            count += state.node_dir_counts[stmt]

        state.node_dir_counts[node] = count

    def visit_default(self, node, state):
        state.node_dir_counts[node] = (
            len(state.directives[node]) if state.directives.get(node) is not None else 0
        )


class CalculateStartLineIdx(TopDownVisitor):
    def visit_AstBody(self, node: AstBody, state: CompileState):
        if node not in state.start_line_idx:
            state.start_line_idx[node] = 0

        start_idx = state.start_line_idx[node]

        line_idx = start_idx
        for stmt in node.stmts:
            state.start_line_idx[stmt] = line_idx
            line_idx += state.node_dir_counts[stmt]

    def visit_AstIf(self, node: AstIf, state: CompileState):
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

    def visit_AstElifs(self, node: AstElifs, state: CompileState):
        line_idx = state.start_line_idx[node]
        for case in node.cases:
            state.start_line_idx[case] = line_idx
            line_idx += state.node_dir_counts[case]

    def visit_AstElif(self, node: AstElif, state: CompileState):
        line_idx = state.start_line_idx[node]
        state.start_line_idx[node.condition] = line_idx
        line_idx += state.node_dir_counts[node.condition]
        # include if dir
        line_idx += 1
        state.start_line_idx[node.body] = line_idx
        line_idx += state.node_dir_counts[node.body]
        # include a goto end of if
        line_idx += 1


class CollectDirectives(Visitor):

    def visit_AstIf(self, node: AstIf, state: CompileState):
        start_line_idx = state.start_line_idx[node]

        all_dirs = []

        cases: list[tuple[AstExpr, AstBody]] = []
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

    def visit_AstBody(self, node: AstBody, state: CompileState):
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

    enum_const_name_dict: dict[str, FppType] = {}

    for name, typ in type_name_dict.items():
        if issubclass(typ, EnumType):
            for enum_const_name, val in typ.ENUM_DICT.items():
                enum_const_name_dict[name + "." + enum_const_name] = typ(
                    enum_const_name
                )

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

    for builtin_name, builtin in BUILTINS.items():
        callable_name_dict[builtin_name] = builtin

    state = CompileState(
        tlms=create_namespace(ch_name_dict),
        prms=create_namespace(prm_name_dict),
        types=create_namespace(type_name_dict),
        callables=create_namespace(callable_name_dict),
        consts=create_namespace(enum_const_name_dict),
    )
    return state


def compile(body: AstBody, dictionary: str) -> list[Directive]:
    print(body)
    state = get_base_compile_state(dictionary)
    passes: list[Visitor] = [
        AssignIds(),
        # might want to error if you're overriding smth from the dict
        CreateVariables(),
        # now that variables have been defined, try resolving references
        # again and fail if anything isn't found
        ResolveReferences(),
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
