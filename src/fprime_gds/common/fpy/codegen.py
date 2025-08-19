from __future__ import annotations
from abc import ABC
import inspect
from dataclasses import dataclass, field, fields
import struct
import traceback
import typing

from fprime_gds.common.fpy.bytecode.directives import (
    BINARY_STACK_OPS,
    UNARY_STACK_OPS,
    AllocateDirective,
    ConstCmdDirective,
    FloatTruncateDirective,
    MemCompareDirective,
    StackOpDirective,
    IntegerTruncate64To16Directive,
    IntegerTruncate64To32Directive,
    IntegerTruncate64To8Directive,
    FloatLogDirective,
    PrintDirective,
    IntegerSignedExtend16To64Directive,
    IntegerSignedExtend32To64Directive,
    IntegerSignedExtend8To64Directive,
    StackCmdDirective,
    StorePrmDirective,
    IntegerZeroExtend16To64Directive,
    IntegerZeroExtend32To64Directive,
    IntegerZeroExtend8To64Directive,
    Directive,
    FloatExtendDirective,
    ExitDirective,
    LoadDirective,
    StoreTlmValDirective,
    GotoDirective,
    IfDirective,
    NotDirective,
    PushValDirective,
    SignedIntToFloatDirective,
    StoreDirective,
    UnsignedIntToFloatDirective,
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
    AstBinaryOp,
    AstBoolean,
    AstElif,
    AstElifs,
    AstExpr,
    AstGetAttr,
    AstGetItem,
    AstNumber,
    AstOp,
    AstReference,
    AstScopedBody,
    AstString,
    Ast,
    AstBody,
    AstLiteral,
    AstIf,
    AstAssign,
    AstFuncCall,
    AstUnaryOp,
    AstVar,
)
from fprime.common.models.serialize.type_base import BaseType as FppType

GENERIC_NUMERIC_TYPES = (NumericalType, FloatType, IntegerType)

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

NUMERIC_OPERATORS = ["+", "-", "*", "/", "%", "**", "//"]


# a value of type FppTypeClass is a Python `type` object representing
# the type of an Fprime value
FppTypeClass = type[FppType]


class NothingType(ABC):
    """a type which has no valid values in fprime. used to denote
    a function which doesn't return a value"""

    @classmethod
    def __subclasscheck__(cls, subclass):
        return False


# the `type` object representing the NothingType class
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
class FpyMacro(FpyCallable):
    dir: type[Directive]
    """a function which instantiates the macro given the argument exprs"""


class PrintStrType(StringType.construct_type("print_str_type", 128)):
    def serialize(self):
        if self.val is None:
            raise RuntimeError(type(self))
        if self.MAX_LENGTH is not None and len(self.val) > self.MAX_LENGTH:
            raise RuntimeError(len(self.val), self.MAX_LENGTH)
        return self.val.encode() + struct.pack(">H", len(self.val))

    def deserialize(self, data, offset):
        """
        Deserializes a string from the given data buffer.
        """
        try:
            val_size = struct.unpack_from(">H", data, len(data - 2))[0]
            # Deal with not enough data left in the buffer
            if len(data[offset + 2 :]) < val_size:
                msg = f"Not enough data to deserialize string data. Needed: {val_size} Left: {len(data[offset + 2:])}"
                raise RuntimeError(msg)
            # Deal with a string that is larger than max string
            if self.MAX_LENGTH is not None and val_size > self.MAX_LENGTH:
                raise RuntimeError(val_size, self.MAX_LENGTH)
            self.val = data[offset : offset + val_size].decode()
        except struct.error:
            raise RuntimeError("Not enough bytes to deserialize string length.")


MACROS: dict[str, FpyMacro] = {
    "sleep": FpyMacro(
        NothingType,
        [
            (
                "seconds",
                U32Type,
            ),
            ("microseconds", U32Type),
        ],
        WaitRelDirective,
    ),
    "sleep_until": FpyMacro(NothingType, [("wakeup_time", TimeType)], WaitAbsDirective),
    "exit": FpyMacro(NothingType, [("success", BoolType)], ExitDirective),
    "log": FpyMacro(F64Type, [("operand", F64Type)], FloatLogDirective),
    "print": FpyMacro(NothingType, [("msg", PrintStrType)], PrintDirective),
}


@dataclass
class FpyTypeCtor(FpyCallable):
    type: FppTypeClass


@dataclass
class FieldReference:
    """a reference to a field/index of an fprime type"""

    parent: "FpyReference"
    """the qualifier"""
    type: FppTypeClass
    """the fprime type of this reference"""
    offset: int
    """the constant offset in the parent type at which to find this field"""
    name: str = None
    """the name of the field, if applicable"""
    idx: int = None
    """the index of the field, if applicable"""

    def get_from(self, parent_val: FppType) -> FppType:
        """gets the field value from the parent value"""
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
    """a mutable, typed value referenced by an unqualified name"""

    type_ref: AstExpr
    """the expression denoting the var's type"""
    declaration: AstAssign
    """the node where this var is declared"""
    type: FppTypeClass | None = None
    """the resolved type of the variable. None if type unsure at the moment"""
    lvar_offset: int | None = None
    """the offset in the lvar array where this var is stored"""


# a scope
FpyScope = dict[str, "FpyReference"]


def create_scope(
    references: dict[str, "FpyReference"],
) -> FpyScope:
    """from a flat dict of strs to references, creates a hierarchical, scoped
    dict. no two leaf nodes may have the same name"""

    base = {}

    for fqn, ref in references.items():
        names_strs = fqn.split(".")

        ns = base
        while len(names_strs) > 1:
            existing_child = ns.get(names_strs[0], None)
            if existing_child is None:
                # this scope is not defined atm
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

        # okay, now ns is the complete scope of the attribute
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


def union_scope(lhs: FpyScope, rhs: FpyScope) -> FpyScope:
    """returns the two scopes, joined into one. if there is a conflict, chooses lhs over rhs"""
    lhs_keys = set(lhs.keys())
    rhs_keys = set(rhs.keys())
    common_keys = lhs_keys.intersection(rhs_keys)

    only_lhs_keys = lhs_keys.difference(common_keys)
    only_rhs_keys = rhs_keys.difference(common_keys)

    new = FpyScope()

    for key in common_keys:
        if not isinstance(lhs[key], dict) or not isinstance(rhs[key], dict):
            # cannot be merged cleanly. one of the two is not a scope
            print(f"WARNING: {key} is defined as {lhs[key]}, ignoring {rhs[key]}")
            new[key] = lhs[key]
            continue

        new[key] = union_scope(lhs[key], rhs[key])

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
    | dict  # dict of FpyReference
)
"""some named concept in fpy"""


def get_ref_fpp_type_class(ref: FpyReference) -> FppTypeClass:
    """returns the fprime type of the ref, if it were to be evaluated as an expression"""
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
        # reference to a scope. scopes don't have values
        result_type = NothingType
    else:
        assert False, ref

    return result_type


@dataclass
class CompileState:
    """a collection of input, internal and output state variables and maps"""

    types: FpyScope
    """a scope whose leaf nodes are subclasses of BaseType"""
    callables: FpyScope
    """a scope whose leaf nodes are FpyCallable instances"""
    tlms: FpyScope
    """a scope whose leaf nodes are ChTemplates"""
    prms: FpyScope
    """a scope whose leaf nodes are PrmTemplates"""
    consts: FpyScope
    """a scope whose leaf nodes are instances of subclasses of BaseType"""
    variables: FpyScope = field(default_factory=dict)
    """a scope whose leaf nodes are FpyVariables"""
    runtime_values: FpyScope = None
    """a scope whose leaf nodes are tlms/prms/consts/variables, all of which
    have some value at runtime."""

    def __post_init__(self):
        self.runtime_values = union_scope(
            self.tlms,
            union_scope(self.prms, union_scope(self.consts, self.variables)),
        )

    resolved_references: dict[AstReference, FpyReference] = field(
        default_factory=dict, repr=False
    )
    """reference to its singular resolution"""

    expr_types: dict[AstExpr, FppTypeClass | NothingTypeClass] = field(
        default_factory=dict
    )
    """expr to its fprime type, or nothing type if none"""

    stack_op_directives: dict[AstOp, type[StackOpDirective]] = field(
        default_factory=dict
    )
    """some stack operation to which directive will be emitted for it"""

    type_conversions: dict[AstExpr, FppTypeClass] = field(default_factory=dict)
    """expr to fprime type it must be converted into at runtime"""

    expr_values: dict[AstExpr, FppType | NothingType | None] = field(
        default_factory=dict
    )
    """expr to its fprime value, or nothing if no value, or None if unsure at compile time"""

    directives: dict[Ast, list[Directive] | None] = field(default_factory=dict)
    """a list of code generated by each node, or None/empty list if no directives"""

    node_dir_counts: dict[Ast, int] = field(default_factory=dict)
    """node to the number of directives generated by it"""

    lvar_array_size_bytes: int = 0
    """the size in bytes of the lvar array"""

    start_line_idx: dict[Ast, int] = field(default_factory=dict)
    """the line index at which each node's directives will be included in the output"""

    errors: list[CompileException] = field(default_factory=list)
    """a list of all compile exceptions generated by passes"""

    def err(self, msg, n):
        """adds a compile exception to internal state"""
        self.errors.append(CompileException(msg, n))


class Visitor:
    """visits each class, calling a custom visit function, if one is defined, for each
    node type"""

    def _find_custom_visit_func(self, node: Ast):
        for name, func in inspect.getmembers(type(self), inspect.isfunction):
            if not name.startswith("visit") or name == "visit_default":
                # not a visitor, or the default visit func
                continue
            signature = inspect.signature(func)
            params = list(signature.parameters.values())
            assert len(params) == 3
            assert params[1].annotation is not None
            annotations = typing.get_type_hints(func)
            param_type = annotations[params[1].name]
            if isinstance(node, param_type):
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
        """runs the visitor, starting at the given node, descending depth-first"""

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
        """runs the visitor, starting at the given node, descending breadth-first"""

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
    """assigns a unique id to each node to allow it to be indexed in a dict"""

    def __init__(self):
        self.next_id = 0

    def visit_default(self, node, state):
        node.id = self.next_id
        self.next_id += 1


class CreateVariables(Visitor):
    """finds all variable declarations and adds them to the variable scope"""

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

            var = FpyVariable(node.var_type, node)
            # new var. put it in the table under this scope
            state.variables[node.variable.var] = var
            state.runtime_values[node.variable.var] = var

        if existing and node.var_type is not None:
            # redeclaring an existing variable
            state.err(f"{node.variable.var} already declared", node)
            return


class ResolveReferences(Visitor):
    """for each reference, resolve it in a specific scope based on its
    syntactic position, or fail if could not resolve"""

    def is_type_constant_size(self, type: FppTypeClass) -> bool:
        """return true if the type is statically sized"""
        if issubclass(type, StringType):
            return False

        if issubclass(type, ArrayType):
            return self.is_type_constant_size(type.MEMBER_TYPE)

        if issubclass(type, SerializableType):
            for _, arg_type, _, _ in type.MEMBER_LIST:
                if not self.is_type_constant_size(arg_type):
                    return False
            return True

        return True

    def get_attr_of_ref(
        self, parent: FpyReference, node: AstGetAttr, state: CompileState
    ) -> FpyReference | None:
        """resolve a GetAttr node relative to a given FpyReference. return the
        resolved ref, or None if none could be found. Will raise errors if not found"""

        if isinstance(parent, (FpyCallable, type)):
            # right now we don't support resolving something after a callable/type
            state.err("Invalid syntax", node)
            return None

        if isinstance(parent, dict):
            # parent is a scope
            attr = parent.get(node.attr, None)
            if attr is None:
                state.err("Unknown attribute", node)
                return None
            return attr

        # parent is a ch, prm, const, or field

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
                return FieldReference(parent, arg_type, offset, name=arg_name)
            offset += arg_type.getMaxSize()

        state.err(f"Unknown member {node.attr}", node)
        return None

    def get_item_of_ref(
        self, parent: FpyReference, node: AstGetItem, state: CompileState
    ) -> FpyReference | None:
        """resolve a GetItem node relative to a given FpyReference. return the
        resolved ref, or None if none could be found. Will raise errors if not found"""

        if isinstance(parent, (FpyCallable, type, dict)):
            # right now we don't support resolving index after a callable/type/scope
            state.err("Invalid syntax", node)
            return None

        # parent is a ch, prm, const, or field

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
                f"{value_type.__name__} has non-constant sized members, cannot access members",
                node,
            )
            return None

        offset = 0
        for i in range(0, value_type.LENGTH):
            if i == node.item.value:
                return FieldReference(parent, value_type.MEMBER_TYPE, offset, idx=i)
            offset += value_type.MEMBER_TYPE.getMaxSize()

        state.err(
            f"Array access out-of-bounds (access: {node.item}, array size: {value_type.LENGTH})",
            node.item,
        )
        return None

    def resolve_if_ref(self, node: AstExpr, ns: FpyScope, state: CompileState) -> bool:
        """if the node is a reference, try to resolve it in the given scope, and return true if success.
        otherwise, if it is not a reference, return true as it doesn't need to be resolved
        """
        if not isinstance(node, AstReference):
            return True

        return self.resolve_ref_in_ns(node, ns, state) is not None

    def resolve_ref_in_ns(
        self, node: AstReference, ns: FpyScope, state: CompileState
    ) -> FpyReference | None:
        """recursively resolves a reference in a scope, returning the resolved ref
        or none if none could be found."""
        if isinstance(node, AstVar):
            if not isinstance(ns, dict):
                return None
            ref = ns.get(node.var, None)
            if ref is None:
                return None
            state.resolved_references[node] = ref
            return ref

        parent = self.resolve_ref_in_ns(node.parent, ns, state)
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
        if not self.resolve_ref_in_ns(node.func, state.callables, state):
            state.err("Unknown callable", node.func)
            return

        for arg in node.args if node.args is not None else []:
            # arg value refs must have values at runtime
            if not self.resolve_if_ref(arg, state.runtime_values, state):
                state.err("Unknown runtime value", arg)
                return

    def visit_AstIf_AstElif(self, node: AstIf | AstElif, state: CompileState):
        # if condition expr refs must be "runtime values" (tlm/prm/const/etc)
        if not self.resolve_if_ref(node.condition, state.runtime_values, state):
            state.err("Unknown runtime value", node.condition)
            return

    def visit_AstBinaryOp(self, node: AstBinaryOp, state: CompileState):
        # lhs/rhs side of stack op, if they are refs, must be refs to "runtime vals"
        if not self.resolve_if_ref(node.lhs, state.runtime_values, state):
            state.err("Unknown runtime value", node.lhs)
            return
        if not self.resolve_if_ref(node.rhs, state.runtime_values, state):
            state.err("Unknown runtime value", node.rhs)
            return

    def visit_AstUnaryOp(self, node: AstUnaryOp, state: CompileState):
        if not self.resolve_if_ref(node.val, state.runtime_values, state):
            state.err("Unknown runtime value", node.val)
            return

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        var = self.resolve_ref_in_ns(node.variable, state.variables, state)
        if not var:
            state.err("Unknown variable", node.variable)
            return

        if node.var_type is not None:
            type = self.resolve_ref_in_ns(node.var_type, state.types, state)
            if not type:
                state.err("Unknown type", node.var_type)
                return
            var.type = type

        if not self.resolve_if_ref(node.value, state.runtime_values, state):
            state.err("Unknown runtime value", node.value)
            return


class CheckUseBeforeDeclare(Visitor):

    def __init__(self):
        self.currently_declared_vars: list[FpyVariable] = []

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        var = state.resolved_references[node.variable]

        if var.declaration != node:
            # this is not the node that declares this variable
            return

        # this node declares this variable

        self.currently_declared_vars.append(var)

    def visit_AstReference(self, node: AstReference, state: CompileState):
        ref = state.resolved_references[node]
        if not isinstance(ref, FpyVariable):
            return

        if ref.declaration.variable == node:
            # this is the initial name of the variable. don't crash
            return

        if ref not in self.currently_declared_vars:
            state.err("Variable used before declared", node)
            return


class CalculateExprTypes(Visitor):
    """stores in state the fprime type of each expression, or NothingType if the expr had no type"""

    def coerce_expr_type(
        self, node: AstExpr, type: FppTypeClass, state: CompileState
    ) -> bool:
        node_type = state.expr_types[node]
        if self.can_interpret_type(node_type, type):
            state.expr_types[node] = type
            return True
        if self.can_convert_type(node_type, type):
            state.type_conversions[node] = type
            return True
        state.err(f"Expected {type.__name__}, found {node_type.__name__}", node)
        return False

    def can_interpret_type(self, type: FppTypeClass, as_type: FppTypeClass) -> bool:
        if type == as_type:
            return True
        if type in GENERIC_NUMERIC_TYPES and issubclass(as_type, type):
            # if type is a generic number type, and it's a superclass of the dest type, we
            # can interpret it as the dest type
            return True

        if type == IntegerType and issubclass(as_type, FloatType):
            # also allow interpreting int literals as floats
            return True

        if type == StringType and issubclass(as_type, type):
            # if type is a generic string type, we can convert it to any string type
            return True

        # otherwise, cannot interpret
        return False

    def can_convert_type(self, type: FppTypeClass, to_type: FppTypeClass) -> bool:
        if type == to_type:
            return True

        if not issubclass(type, NumericalType) or not issubclass(
            to_type, NumericalType
        ):
            # only allow conversions between numerical types
            return False

        if issubclass(type, FloatType) and issubclass(to_type, IntegerType):
            # cannot convert float to int (i.e. don't allow it)
            return False

        # otherwise we're good
        return True

    def pick_intermediate_type(
        self, arg_types: list[FppTypeClass], op: str
    ) -> FppTypeClass:

        if op == "and" or op == "or" or op == "not":
            return BoolType

        non_numeric = any(not issubclass(t, NumericalType) for t in arg_types)

        if op == "==" or op == "!=":
            if non_numeric:
                if len(set(arg_types)) != 1:
                    # can only compare equality between the same types
                    return None
                return arg_types[0]

        # all arguments should be numeric
        if non_numeric:
            # cannot find intermediate type
            return None

        if op == "/" or op == "**":
            # always do true division over floats, python style
            return F64Type

        float = any(issubclass(t, FloatType) for t in arg_types)
        unsigned = any(t in UNSIGNED_INTEGER_TYPES for t in arg_types)

        if float:
            # at least one arg is a float
            return F64Type

        if unsigned:
            # at least one arg is unsigned
            return U64Type

        return I64Type

    def visit_AstNumber(self, node: AstNumber, state: CompileState):
        # give a best guess as to the final type of this node. we don't actually know
        # its bitwidth or signedness yet
        if isinstance(node.value, float):
            result_type = FloatType
        else:
            result_type = IntegerType
        state.expr_types[node] = result_type

    def visit_AstBinaryOp(self, node: AstBinaryOp, state: CompileState):
        lhs_type = state.expr_types[node.lhs]
        rhs_type = state.expr_types[node.rhs]

        intermediate_type = self.pick_intermediate_type([lhs_type, rhs_type], node.op)
        if intermediate_type is None:
            state.err(
                f"Op {node.op} undefined for {lhs_type.__name__}, {rhs_type.__name__}",
                node,
            )
            return

        if not self.coerce_expr_type(node.lhs, intermediate_type, state):
            return
        if not self.coerce_expr_type(node.rhs, intermediate_type, state):
            return

        # okay now find which actual directive we're going to use based on this intermediate
        # type, and save it

        dir = None
        if (
            node.op == "==" or node.op == "!="
        ) and intermediate_type not in NUMERIC_TYPES:
            dir = MemCompareDirective
        else:
            dir = BINARY_STACK_OPS[node.op][intermediate_type]

        state.stack_op_directives[node] = dir

        result_type = None
        if node.op in NUMERIC_OPERATORS:
            result_type = intermediate_type
        else:
            result_type = BoolType
        state.expr_types[node] = result_type

    def visit_AstUnaryOp(self, node: AstUnaryOp, state: CompileState):
        val_type = state.expr_types[node.val]

        intermediate_type = self.pick_intermediate_type([val_type], node.op)
        if intermediate_type is None:
            state.err(f"Op {node.op} undefined for {val_type.__name__}", node)
            return

        if not self.coerce_expr_type(node.val, intermediate_type, state):
            return

        # okay now find which actual directive we're going to use based on this intermediate
        # type, and save it

        chosen_dir = UNARY_STACK_OPS[node.op][intermediate_type]

        result_type = None
        if node.op in NUMERIC_OPERATORS:
            result_type = intermediate_type
        else:
            result_type = BoolType

        state.stack_op_directives[node] = chosen_dir
        state.expr_types[node] = result_type

    def visit_AstString(self, node: AstString, state: CompileState):
        state.expr_types[node] = StringType

    def visit_AstBoolean(self, node: AstBoolean, state: CompileState):
        state.expr_types[node] = BoolType

    def visit_AstReference(self, node: AstReference, state: CompileState):
        ref = state.resolved_references[node]
        state.expr_types[node] = get_ref_fpp_type_class(ref)
        if isinstance(node, AstGetItem):
            # the node of the index number has no expression value, it's an arg
            # but only at syntax level
            state.expr_types[node.item] = NothingType

    def visit_AstFuncCall(self, node: AstFuncCall, state: CompileState):
        func = state.resolved_references[node.func]
        assert isinstance(func, FpyCallable)
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

            if not self.coerce_expr_type(value_expr, arg_type, state):
                return

        # got thru all args successfully
        state.expr_types[node] = func.return_type

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        var_type = state.resolved_references[node.variable].type

        if not self.coerce_expr_type(node.value, var_type, state):
            return

    def visit_default(self, node, state):
        # coding error, missed an expr
        assert not isinstance(node, AstExpr), node


class AllocateVariables(Visitor):
    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        existing_var = state.resolved_references[node.variable]

        assert existing_var is not None
        assert existing_var.type is not None

        value_size = existing_var.type.getMaxSize()

        if existing_var.lvar_offset is None:
            # doesn't have an lvar idx, allocate one
            lvar_offset = state.lvar_array_size_bytes
            state.lvar_array_size_bytes += value_size
            existing_var.lvar_offset = lvar_offset


class CalculateConstExprValues(Visitor):
    """for each expr, try to calculate its constant value and store it in a map. stores None if no value could be
    calculated at compile time, and NothingType if the expr had no value"""

    def visit_AstLiteral(self, node: AstLiteral, state: CompileState):
        literal_type = state.expr_types[node]
        if literal_type != NothingType:
            assert (
                literal_type in NUMERIC_TYPES
                or issubclass(literal_type, StringType)
                or literal_type == BoolType
            ), literal_type
            state.expr_values[node] = literal_type(node.value)
        else:
            state.expr_values[node] = literal_type()

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
            # a ref to a scope doesn't have a value
            expr_value = NothingType()
        else:
            assert False, ref

        assert expr_value is None or isinstance(expr_value, state.expr_types[node]), (
            expr_value,
            state.expr_types[node],
        )
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
            # we will have to calculate this at runtime
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

            elif issubclass(func.type, ArrayType):
                instance = func.type()
                instance._val = arg_values
                state.expr_values[node] = instance

            elif func.type == TimeType:
                state.expr_values[node] = TimeType(*arg_values)

            else:
                # no other FppTypeClasses have ctors
                assert False, func.return_type
        else:
            # don't try to calculate the value of this function call
            # it's something like a cmd or macro
            state.expr_values[node] = None

    def visit_AstOp(self, node: AstOp, state: CompileState):
        # we do not calculate compile time value of operators at the moment
        state.expr_values[node] = None

    def visit_default(self, node, state):
        # coding error, missed an expr
        assert not isinstance(node, AstExpr), node


class GenerateConstExprDirectives(Visitor):
    """for each expr with a constant compile time value, generate
    directives for how to put it in its register"""

    def visit_AstExpr(self, node: AstExpr, state: CompileState):
        if node in state.directives:
            # already have directives associated with this node
            return

        expr_value = state.expr_values[node]

        if expr_value is None:
            # no const value
            return

        assert node not in state.type_conversions, node

        expr_type = state.expr_types[node]

        if expr_type == NothingType:
            # nothing type has no value
            state.directives[node] = []
            return

        # it has a constant value at compile time
        serialized_expr_value = expr_value.serialize()

        # push it to the stack
        state.directives[node] = [PushValDirective(serialized_expr_value)]


class GenerateExprMacrosAndCmds(Visitor):
    """for each expr whose value is not known at compile time, but can be calculated at run time,
    generate directives to calculate the value and put it in its register. for each command
    or macro, generate directives for calling them with appropriate arg values"""

    def get_64_bit_type(self, type: FppTypeClass) -> FppTypeClass:
        assert type in NUMERIC_TYPES, type
        return (
            I64Type
            if type in SIGNED_INTEGER_TYPES
            else U64Type if type in UNSIGNED_INTEGER_TYPES else F64Type
        )

    def truncate_from_64_bits(
        self, from_type: FppTypeClass, new_size: int
    ) -> list[Directive]:

        assert new_size in (1, 2, 4, 8), new_size
        assert from_type.getMaxSize() == 8, from_type.getMaxSize()

        if new_size == 8:
            # already correct size
            return []

        if from_type == F64Type:
            # only one option for float trunc
            assert new_size == 4, new_size
            return [FloatTruncateDirective()]

        # must be an int
        assert issubclass(from_type, IntegerType), from_type

        if new_size == 1:
            return [IntegerTruncate64To8Directive()]
        elif new_size == 2:
            return [IntegerTruncate64To16Directive()]

        return [IntegerTruncate64To32Directive()]

    def extend_to_64_bits(self, type: FppTypeClass) -> list[Directive]:
        if type.getMaxSize() == 8:
            # already 8 bytes
            return []
        if type == F32Type:
            return [FloatExtendDirective()]

        # must be an int
        assert issubclass(type, IntegerType), type

        from_size = type.getMaxSize()
        assert from_size in (1, 2, 4, 8), from_size

        if type in SIGNED_INTEGER_TYPES:
            if from_size == 1:
                return [IntegerSignedExtend8To64Directive()]
            elif from_size == 2:
                return [IntegerSignedExtend16To64Directive()]
            else:
                return [IntegerSignedExtend32To64Directive()]
        else:
            if from_size == 1:
                return [IntegerZeroExtend8To64Directive()]
            elif from_size == 2:
                return [IntegerZeroExtend16To64Directive()]
            else:
                return [IntegerZeroExtend32To64Directive()]

    def convert_type(
        self, from_type: FppTypeClass, to_type: FppTypeClass
    ) -> list[Directive]:
        if from_type == to_type:
            return []

        # only valid runtime type conversion is between two numeric types
        assert from_type in NUMERIC_TYPES and to_type in NUMERIC_TYPES, (
            from_type,
            to_type,
        )
        # also invalid to convert from a float to an integer at runtime due to loss of precision
        assert not (from_type in FLOAT_TYPES and to_type in INTEGER_TYPES), (
            from_type,
            to_type,
        )

        dirs = []
        # first go to 64 bit width
        dirs.extend(self.extend_to_64_bits(from_type))
        from_64_bit = self.get_64_bit_type(from_type)
        to_64_bit = self.get_64_bit_type(to_type)

        # now convert from int to float if necessary
        if from_64_bit == U64Type and to_64_bit == F64Type:
            dirs.append(UnsignedIntToFloatDirective())
            from_64_bit = F64Type
        elif from_64_bit == I64Type and to_64_bit == F64Type:
            dirs.append(SignedIntToFloatDirective())
            from_64_bit = F64Type
        elif from_64_bit == U64Type or from_64_bit == I64Type:
            assert to_64_bit == U64Type or to_64_bit == I64Type
            # conversion from signed to unsigned int is implicit, doesn't need code gen
            from_64_bit = to_64_bit

        assert from_64_bit == to_64_bit, (from_64_bit, to_64_bit)

        # now truncate back down to desired size
        dirs.extend(self.truncate_from_64_bits(to_64_bit, to_type.getMaxSize()))
        return dirs

    def visit_AstReference(self, node: AstReference, state: CompileState):
        if node in state.directives:
            # already know how to put it on stack, or it is impossible
            return

        expr_type = state.expr_types[node]
        ref = state.resolved_references[node]

        directives = []

        # does not have a constant compile time value

        # first, put it in an lvar. then load it from the lvar onto stack

        # the offset of the field in the parent type
        offset_in_parent_val = 0
        # the offset of the lvar the parent type is stored in
        offset_in_lvar_array = 0

        base_ref = ref

        # if it's a field ref, find the parent and the offset in the parent
        while isinstance(base_ref, FieldReference):
            offset_in_parent_val += base_ref.offset
            base_ref = base_ref.parent

        if isinstance(base_ref, ChTemplate):
            # put it in an lvar
            offset_in_lvar_array = state.lvar_array_size_bytes
            state.lvar_array_size_bytes += base_ref.get_type_obj().getMaxSize()
            directives.append(
                StoreTlmValDirective(base_ref.get_id(), offset_in_lvar_array)
            )
        elif isinstance(base_ref, PrmTemplate):
            # put it in an lvar
            offset_in_lvar_array = state.lvar_array_size_bytes
            state.lvar_array_size_bytes += base_ref.get_type_obj().getMaxSize()
            directives.append(
                StorePrmDirective(base_ref.get_id(), offset_in_lvar_array)
            )
        elif isinstance(base_ref, FpyVariable):
            # already should be in an lvar
            offset_in_lvar_array = base_ref.lvar_offset
        else:
            assert (
                False
            ), base_ref  # ref should either be impossible to put on stack or should have a compile time val

        # load from the lvar
        directives.append(
            LoadDirective(
                offset_in_lvar_array + offset_in_parent_val, expr_type.getMaxSize()
            )
        )
        converted_type = state.type_conversions.get(node, None)
        if converted_type is not None:
            directives.extend(self.convert_type(expr_type, converted_type))

        state.directives[node] = directives

    def visit_AstBinaryOp(self, node: AstBinaryOp, state: CompileState):
        if node in state.directives:
            # already know how to put it on stack
            return

        directives = []

        expr_type = state.expr_types[node]

        lhs_dirs = state.directives[node.lhs]
        rhs_dirs = state.directives[node.rhs]

        # which variant of the op did we pick?
        dir = state.stack_op_directives[node]

        # generate the actual op itself
        directives: list[Directive] = lhs_dirs + rhs_dirs
        if dir == MemCompareDirective:
            lhs_type = state.expr_types[node.lhs]
            rhs_type = state.expr_types[node.rhs]
            assert lhs_type == rhs_type, (lhs_type, rhs_type)
            directives.append(dir(lhs_type.getMaxSize()))
            if node.op == "!=":
                directives.append(NotDirective())
        else:
            directives.append(dir())

        # and convert the result of the op into the desired result of this expr
        converted_type = state.type_conversions.get(node, None)
        if converted_type is not None:
            directives.extend(self.convert_type(expr_type, converted_type))

        state.directives[node] = directives

    def visit_AstUnaryOp(self, node: AstUnaryOp, state: CompileState):
        if node in state.directives:
            # already know how to put it on stack
            return

        directives = []

        expr_type = state.expr_types[node]

        val_dirs = state.directives[node.val]

        # which variant of the op did we pick?
        dir = state.stack_op_directives[node]
        # generate the actual op itself
        directives: list[Directive] = val_dirs
        directives.append(dir())
        # and convert the result of the op into the desired result of this expr
        converted_type = state.type_conversions.get(node, None)
        if converted_type is not None:
            directives.extend(self.convert_type(expr_type, converted_type))

        state.directives[node] = directives

    def visit_AstFuncCall(self, node: AstFuncCall, state: CompileState):
        node_args = node.args if node.args is not None else []
        func = state.resolved_references[node.func]
        dirs = state.directives.get(node, [])
        if len(dirs) > 0:
            # already know how to put this on the stack
            return
        if isinstance(func, FpyCmd):
            const_args = not any(
                state.expr_values[arg_node] is None for arg_node in node_args
            )
            if const_args:
                # can just hardcode this cmd
                arg_bytes = bytes()
                for arg_node in node_args:
                    arg_value = state.expr_values[arg_node]
                    arg_bytes += arg_value.serialize()
                dirs = [ConstCmdDirective(func.cmd.get_op_code(), arg_bytes)]
            else:
                arg_byte_count = 0
                # push all args to the stack
                # keep track of how many bytes total we have pushed
                for arg_node in node_args:
                    node_dirs = state.directives[arg_node]
                    assert len(node_dirs) >= 1
                    dirs.extend(node_dirs)
                    arg_byte_count = state.expr_types[arg_node].getMaxSize()
                # then push cmd opcode to stack as u32
                dirs.append(
                    PushValDirective(U32Type(func.cmd.get_op_code()).serialize())
                )
                # now that all args are pushed to the stack, pop them and opcode off the stack
                # as a command
                dirs.append(StackCmdDirective(arg_byte_count))
        elif isinstance(func, FpyMacro):
            # put all arg values on stack
            for arg_node in node_args:
                node_dirs = state.directives[arg_node]
                assert len(node_dirs) >= 1
                dirs.extend(node_dirs)
                arg_byte_count = state.expr_types[arg_node].getMaxSize()

            dirs.append(func.dir())
        else:
            dirs = None

        # perform type conversion if called for
        converted_type = state.type_conversions.get(node, None)
        if converted_type is not None:
            dirs.extend(self.convert_type(func.return_type, converted_type))
        state.directives[node] = dirs

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        var = state.resolved_references[node.variable]
        state.directives[node] = state.directives[node.value] + [
            StoreDirective(var.lvar_offset, var.type.getMaxSize())
        ]


class CountNodeDirectives(Visitor):
    """count the number of directives that will be generated by each node"""

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

    def visit_AstBody(self, node: AstBody | AstScopedBody, state: CompileState):
        count = 0
        if isinstance(node, AstScopedBody):
            # add one for lvar array alloc
            count += 1
        for stmt in node.stmts:
            count += state.node_dir_counts[stmt]

        state.node_dir_counts[node] = count

    def visit_default(self, node, state):
        state.node_dir_counts[node] = (
            len(state.directives[node]) if state.directives.get(node) is not None else 0
        )


class CalculateStartLineIdx(TopDownVisitor):
    """based on the number of directives generated by each node, calculate the start line idx
    of each node's directives"""

    def visit_AstBody(self, node: AstBody | AstScopedBody, state: CompileState):
        if node not in state.start_line_idx:
            state.start_line_idx[node] = 0

        start_idx = state.start_line_idx[node]

        line_idx = start_idx
        if isinstance(node, AstScopedBody):
            # include lvar alloc
            line_idx += 1

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


class GenerateBodyDirectives(Visitor):
    """concatenate all directives together for each AstBody"""

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
            # put the conditional on top of stack
            case_dirs.extend(state.directives[case[0]])
            # include if stmt (update the end idx later)
            if_dir = IfDirective(-1)

            case_dirs.append(if_dir)
            # include body
            case_dirs.extend(state.directives[case[1]])
            # include a temporary goto end of if, will be refined later
            goto_dir = GotoDirective(-1)
            case_dirs.append(goto_dir)
            goto_ends.append(goto_dir)

            # if false, skip the body and goto
            if_dir.false_goto_dir_index = (
                start_line_idx + len(all_dirs) + len(case_dirs)
            )

            all_dirs.extend(case_dirs)

        if node.els is not None:
            all_dirs.extend(state.directives[node.els])

        for goto in goto_ends:
            goto.dir_idx = start_line_idx + len(all_dirs)

        state.directives[node] = all_dirs

    def visit_AstBody(self, node: AstBody | AstScopedBody, state: CompileState):
        dirs = []
        if isinstance(node, AstScopedBody):
            dirs.append(AllocateDirective(state.lvar_array_size_bytes))
        for stmt in node.stmts:
            stmt_dirs = state.directives.get(stmt, None)
            if stmt_dirs is not None:
                dirs.extend(stmt_dirs)

        state.directives[node] = dirs


def get_base_compile_state(dictionary: str) -> CompileState:
    """return the initial state of the compiler, based on the given dict path"""
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
    # the type name dict is a mapping of a fully qualified name to an fprime type
    # here we put into it all types found while parsing all cmds, params and tlm channels
    type_name_dict: dict[str, FppTypeClass] = cmd_json_dict_loader.parsed_types
    type_name_dict.update(ch_json_dict_loader.parsed_types)
    type_name_dict.update(prm_json_dict_loader.parsed_types)

    # enum const dict is a dict of fully qualified enum const name (like Ref.Choice.ONE) to its fprime value
    enum_const_name_dict: dict[str, FppType] = {}

    # find each enum type, and put each of its values in the enum const dict
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
    # note no string type at the moment

    cmd_response_type = type_name_dict["Fw.CmdResponse"]
    callable_name_dict: dict[str, FpyCallable] = {}
    # add all cmds to the callable dict
    for name, cmd in cmd_name_dict.items():
        cmd: CmdTemplate
        args = []
        for arg_name, _, arg_type in cmd.arguments:
            args.append((arg_name, arg_type))
        # cmds are thought of as callables with a Fw.CmdResponse return value
        callable_name_dict[name] = FpyCmd(cmd_response_type, args, cmd)

    # for each type in the dict, if it has a constructor, create an FpyTypeCtor
    # object to track the constructor and put it in the callable name dict
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

    # for each macro function, add it to the callable dict
    for macro_name, macro in MACROS.items():
        callable_name_dict[macro_name] = macro

    state = CompileState(
        tlms=create_scope(ch_name_dict),
        prms=create_scope(prm_name_dict),
        types=create_scope(type_name_dict),
        callables=create_scope(callable_name_dict),
        consts=create_scope(enum_const_name_dict),
    )
    return state


def compile(body: AstScopedBody, dictionary: str) -> list[Directive]:
    state = get_base_compile_state(dictionary)
    passes: list[Visitor] = [
        AssignIds(),
        # based on assignment syntax nodes, we know which variables exist where
        CreateVariables(),
        # now that variables have been defined, all names/attributes/indices (references)
        # should be defined
        ResolveReferences(),
        CheckUseBeforeDeclare(),
        # now that we know what all refs point to, we should be able to figure out the type
        # of every expression
        CalculateExprTypes(),
        # now that expr types have been narrowed down, we can allocate lvar space for variables
        AllocateVariables(),
        # okay, now that we're sure we're passing in all the right args to each func,
        # we can calculate values of type ctors etc etc
        CalculateConstExprValues(),
        # for expressions which have constant values, generate corresponding directives
        # to put the expr on the stack
        GenerateConstExprDirectives(),
        # generate directives to calculate exprs, macros and cmds at runtime and put them
        # on the stack
        GenerateExprMacrosAndCmds(),
        # count the number of directives generated by each node
        CountNodeDirectives(),
        # calculate the index that the node will correspond to in the output file
        CalculateStartLineIdx(),
        # generate directives for each body node, including the root
        GenerateBodyDirectives(),
    ]

    for compile_pass in passes:
        compile_pass.run(body, state)
        for error in state.errors:
            raise error

    return state.directives[body]
