from __future__ import annotations
from abc import ABC
from decimal import Decimal
import inspect
from dataclasses import astuple, dataclass, field, fields
import math
import struct
import typing
from typing import Callable, Iterable, Union, get_args, get_origin
import zlib

from fprime_gds.common.fpy.error import CompileError

# In Python 3.10+, the `|` operator creates a `types.UnionType`.
# We need to handle this for forward compatibility, but it won't exist in 3.9.
try:
    from types import UnionType

    UNION_TYPES = (Union, UnionType)
except ImportError:
    UNION_TYPES = (Union,)

from fprime_gds.common.fpy.bytecode.directives import (
    Directive,
)
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime_gds.common.templates.prm_template import PrmTemplate
from fprime_gds.common.models.serialize.numerical_types import (
    U8Type as U8Value,
    U16Type as U16Value,
    U32Type as U32Value,
    U64Type as U64Value,
    I8Type as I8Value,
    I16Type as I16Value,
    I32Type as I32Value,
    I64Type as I64Value,
    F32Type as F32Value,
    F64Type as F64Value,
    IntegerType as IntegerValue,
    FloatType as FloatValue,
    NumericalType as NumericalValue,
)
from fprime_gds.common.models.serialize.string_type import StringType as StringValue
from fprime_gds.common.fpy.syntax import (
    AstBreak,
    AstContinue,
    AstExpr,
    AstFor,
    AstFuncCall,
    AstOp,
    AstReference,
    Ast,
    AstAssign,
    AstScopedBody,
    AstWhile,
)
from fprime_gds.common.models.serialize.type_base import BaseType as FppValue

MAX_DIRECTIVES_COUNT = 1024
MAX_DIRECTIVE_SIZE = 2048
MAX_STACK_SIZE = 1024

COMPILER_MAX_STRING_SIZE = 128


def typename(typ: FppType) -> str:
    if typ == FpyIntegerValue:
        return "Integer"
    if typ == FpyFloatValue:
        return "Float"
    if issubclass(typ, NumericalValue):
        return typ.get_canonical_name()
    if typ == FpyStringValue:
        return "String"
    if typ == RangeValue:
        return "Range"
    return str(typ)


LoopVarValue = I64Value


# this is the "internal" integer type that integer literals have by
# default. it is arbitrary precision. it is also only used in places where
# we know the value is constant
class FpyIntegerValue(IntegerValue):
    @classmethod
    def range(cls):
        raise NotImplementedError()

    @staticmethod
    def get_serialize_format():
        raise NotImplementedError()

    @classmethod
    def get_bits(cls):
        return math.inf

    @classmethod
    def validate(cls, val):
        if not isinstance(val, int):
            raise RuntimeError()


# this is the "internal" float type that float literals have by
# default. it is arbitrary precision. it is also only used in places where
# we know the value is constant
class FpyFloatValue(FloatValue):
    @staticmethod
    def get_serialize_format():
        raise NotImplementedError()

    @classmethod
    def get_bits(cls):
        return math.inf

    @classmethod
    def validate(cls, val):
        if not isinstance(val, Decimal):
            raise RuntimeError()


# the type produced by range expressions `X .. Y`
class RangeValue(FppValue):
    def serialize(self):
        raise NotImplementedError()

    def deserialize(self, data, offset):
        raise NotImplementedError()

    def getSize(self):
        raise NotImplementedError()

    @classmethod
    def getMaxSize(cls):
        raise NotImplementedError()

    def __repr__(self):
        return self.__class__.__name__

    def to_jsonable(self):
        raise NotImplementedError()


# this is the "internal" string type that string literals have by
# default. it is arbitrary length. it is also only used in places where
# we know the value is constant
FpyStringValue = StringValue.construct_type("FpyStringValue", None)


SPECIFIC_NUMERIC_TYPES = (
    U32Value,
    U16Value,
    U64Value,
    U8Value,
    I16Value,
    I32Value,
    I64Value,
    I8Value,
    F32Value,
    F64Value,
)
SPECIFIC_INTEGER_TYPES = (
    U32Value,
    U16Value,
    U64Value,
    U8Value,
    I16Value,
    I32Value,
    I64Value,
    I8Value,
)
SIGNED_INTEGER_TYPES = (
    I16Value,
    I32Value,
    I64Value,
    I8Value,
)
UNSIGNED_INTEGER_TYPES = (
    U32Value,
    U16Value,
    U64Value,
    U8Value,
)
SPECIFIC_FLOAT_TYPES = (
    F32Value,
    F64Value,
)
ARBITRARY_PRECISION_TYPES = (FpyFloatValue, FpyIntegerValue)


def is_instance_compat(obj, cls):
    """
    A wrapper for isinstance() that correctly handles Union types in Python 3.9+.

    Args:
        obj: The object to check.
        cls: The class, tuple of classes, or Union type to check against.

    Returns:
        True if the object is an instance of the class or any type in the Union.
    """
    origin = get_origin(cls)
    if origin in UNION_TYPES:
        # It's a Union type, so get its arguments.
        # e.g., get_args(Union[int, str]) returns (int, str)
        return isinstance(obj, get_args(cls))

    # It's not a Union, so it's a regular type (like int) or a
    # tuple of types ((int, str)), which isinstance handles natively.
    return isinstance(obj, cls)


# a value of type FppType is a Python `type` object representing
# the type of an Fprime value
FppType = type[FppValue]


class NothingValue(ABC):
    """a type which has no valid values in fprime. used to denote
    a function which doesn't return a value"""

    @classmethod
    def __subclasscheck__(cls, subclass):
        return False


# the `type` object representing the NothingType class
NothingType = type[NothingValue]


@dataclass
class FpyCallable:
    name: str
    return_type: FppType | NothingType
    args: list[tuple[str, FppType]]


@dataclass
class FpyCmd(FpyCallable):
    cmd: CmdTemplate


@dataclass
class FpyMacro(FpyCallable):
    generate: Callable[[AstFuncCall], list[Directive]]
    """a function which instantiates the macro given the calling node"""


@dataclass
class FpyTypeCtor(FpyCallable):
    type: FppType


@dataclass
class FpyCast(FpyCallable):
    to_type: FppType


@dataclass
class FieldReference:
    """a reference to a member/element of an fprime struct/array type"""

    parent_expr: AstExpr
    """the complete qualifier"""
    base_ref: FpyReference
    """the base ref, up through all the layers of field refs"""
    type: FppType
    """the fprime type of this reference"""
    is_struct_member: bool = False
    """True if this is a struct member reference"""
    is_array_element: bool = False
    """True if this is an array element reference"""
    base_offset: int = None
    """the constant offset in the base ref type, or None if unknown at compile time"""
    local_offset: int = None
    """the constant offset in the parent type at which to find this field
    or None if unknown at compile time"""
    name: str = None
    """the name of the field, if applicable"""
    idx_expr: AstExpr = None
    """the expression that evaluates to the index in the parent array of the field, if applicable"""


# named variables can be tlm chans, prms, callables, or directly referenced consts (usually enums)
@dataclass
class FpyVariable:
    """a mutable, typed value referenced by an unqualified name"""

    name: str
    type_ref: AstExpr
    """the expression denoting the var's type"""
    declaration: AstAssign
    """the node where this var is declared"""
    type: FppType | None = None
    """the resolved type of the variable. None if type unsure at the moment"""
    lvar_offset: int | None = None
    """the offset in the lvar array where this var is stored"""


@dataclass
class ForLoopAnalysis:
    loop_var: FpyVariable
    upper_bound_var: FpyVariable
    reuse_existing_loop_var: bool


# a scope
next_scope_id = 0


class FpyScope(dict):
    def __init__(self):
        global next_scope_id
        self.id = next_scope_id
        next_scope_id += 1

    def __getitem__(self, key: str) -> FpyReference:
        return super().__getitem__(key)

    def get(self, key) -> FpyReference | None:
        return super().get(key, None)

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, value):
        return isinstance(value, FpyScope) and value.id == self.id


def create_scope(
    references: dict[str, "FpyReference"],
) -> FpyScope:
    """from a flat dict of strs to references, creates a hierarchical, scoped
    dict. no two leaf nodes may have the same name"""

    base = FpyScope()

    for fqn, ref in references.items():
        names_strs = fqn.split(".")

        ns = base
        while len(names_strs) > 1:
            existing_child = ns.get(names_strs[0])
            if existing_child is None:
                # this scope is not defined atm
                existing_child = {}
                ns[names_strs[0]] = existing_child

            if not isinstance(existing_child, dict):
                # something else already has this name
                break

            ns = existing_child
            names_strs = names_strs[1:]

        if len(names_strs) != 1:
            # broke early. skip this loop
            continue

        # okay, now ns is the complete scope of the attribute
        # i.e. everything up until the last '.'
        name = names_strs[0]

        existing_child = ns.get(name)

        if existing_child is not None:
            # uh oh, something already had this name with a diff value
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
            new[key] = lhs[key]
            continue

        new[key] = union_scope(lhs[key], rhs[key])

    for key in only_lhs_keys:
        new[key] = lhs[key]
    for key in only_rhs_keys:
        new[key] = rhs[key]

    return new


FpyReference = typing.Union[
    ChTemplate,
    PrmTemplate,
    FppValue,
    FpyCallable,
    FppType,
    FpyVariable,
    FieldReference,
    dict,  # dict of FpyReference
]
"""some named concept in fpy"""


def resolve_var(node: Ast, name: str, state: CompileState) -> FpyVariable:
    # check this scope and all parent scopes
    local_scope = state.local_scopes[node]
    resolved = None
    while local_scope is not None and resolved is None:
        resolved = local_scope.get(name)
        local_scope = state.scope_parents[local_scope]

    return resolved


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
    """a scope whose leaf nodes are FpyVariables"""
    runtime_values: FpyScope = None
    """a scope whose leaf nodes are tlms/prms/consts, all of which
    have some value at runtime."""

    compile_args: dict = field(default_factory=dict)

    def __post_init__(self):
        self.runtime_values = union_scope(
            self.tlms,
            union_scope(self.prms, self.consts),
        )

    next_node_id: int = 0
    root: AstScopedBody = None
    variables: list[FpyVariable] = field(default_factory=list)
    """a list of all variables, including ones that are anonymous, unlike the scope dict"""
    scope_parents: dict[AstScopedBody, AstScopedBody | None] = field(
        default_factory=dict, repr=False
    )
    body_scopes: dict[AstScopedBody, FpyScope] = field(default_factory=dict, repr=False)
    local_scopes: dict[Ast, FpyScope] = field(default_factory=dict, repr=False)
    for_loops: dict[AstFor, ForLoopAnalysis] = field(default_factory=dict)
    enclosing_loops: dict[Union[AstBreak, AstContinue], Union[AstFor, AstWhile]] = (
        field(default_factory=dict)
    )
    desugared_for_loops: dict[AstWhile, AstFor] = field(default_factory=dict)

    resolved_references: dict[AstReference, FpyReference] = field(
        default_factory=dict, repr=False
    )
    """reference to its singular resolution"""

    expr_unconverted_types: dict[AstExpr, FppType | NothingType] = field(
        default_factory=dict
    )
    """expr to its fprime type, before type conversions are applied"""

    op_intermediate_types: dict[AstOp, FppType] = field(default_factory=dict)

    expr_explicit_casts: list[AstExpr] = field(default_factory=list)
    expr_converted_types: dict[AstExpr, FppType] = field(default_factory=dict)
    """expr to fprime type it will end up being on the stack after type conversions"""

    expr_converted_values: dict[AstExpr, FppValue | NothingValue | None] = field(
        default_factory=dict
    )
    """expr to the fprime value it will end up being on the stack after type conversions.
    None if unsure at compile time"""

    while_loop_end_labels: dict[AstWhile, int] = field(default_factory=dict)
    while_loop_start_labels: dict[AstWhile, int] = field(default_factory=dict)
    # store keys as while because for loops are desugared to while
    for_loop_inc_labels: dict[AstWhile, int] = field(default_factory=dict)

    lvar_array_size_bytes: int = 0
    """the size in bytes of the lvar array"""

    errors: list[CompileError] = field(default_factory=list)
    """a list of all compile exceptions generated by passes"""

    warnings: list[CompileError] = field(default_factory=list)
    """a list of all compiler warnings generated by passes"""

    next_anon_var_id: int = 0

    def new_anonymous_variable_name(self) -> str:
        id = self.next_anon_var_id
        return f"$value{id}"

    def err(self, msg, n):
        """adds a compile exception to internal state"""
        self.errors.append(CompileError(msg, n))

    def warn(self, msg, n):
        self.warnings.append(CompileError("Warning: " + msg, n))


class Visitor:
    """visits each class, calling a custom visit function, if one is defined, for each
    node type"""

    def __init__(self):
        self.visitors: dict[type[Ast], Callable] = {}
        """dict of node type to handler function"""
        self.build_visitor_dict()

    def build_visitor_dict(self):
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

            origin = get_origin(param_type)
            if origin in UNION_TYPES:
                # It's a Union type, so get its arguments.
                for t in get_args(param_type):
                    self.visitors[t] = getattr(self, name)
            else:
                # It's not a Union, so it's a regular type
                self.visitors[param_type] = getattr(self, name)

    def _visit(self, node: Ast, state: CompileState):
        visit_func = self.visitors.get(type(node), self.visit_default)
        return visit_func(node, state)

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


class Transformer(Visitor):

    class Delete:
        pass

    def run(self, start: Ast, state: CompileState):

        def _descend(node):
            if not isinstance(node, Ast):
                return
            for field in fields(node):
                field_val = getattr(node, field.name)
                if isinstance(field_val, list):
                    # child is a list, iterate over each member of the list
                    # use a copy so we can remove as we traverse, also so
                    # we don't visit things that we added

                    #
                    idx = -1
                    for child in field_val[:]:
                        idx += 1
                        if not isinstance(child, Ast):
                            continue
                        _descend(child)
                        if len(state.errors) != 0:
                            break
                        transformed = self._visit(child, state)
                        if len(state.errors) != 0:
                            break
                        if isinstance(transformed, Iterable):
                            assert all(
                                isinstance(n, Ast) for n in transformed
                            ), transformed
                            # func split one node into many
                            # remove the original child and add the new ones
                            # insert them in the place where the child used to be, in the right order
                            field_val.remove(child)
                            for new_child_idx, new_child in enumerate(transformed):
                                field_val.insert(idx + new_child_idx, new_child)
                            # make sure that we maintain insertion order by updating the idx
                            # accounting for our removal of an original node
                            # if we don't do this, then if we were to insert into list after this based on idx,
                            # the positions could be swapped around
                            idx += len(transformed) - 1
                        elif isinstance(transformed, Ast):
                            field_val.remove(child)
                            field_val.insert(idx, transformed)
                        elif transformed is Transformer.Delete:
                            # just delete it
                            field_val.remove(child)
                        else:
                            assert transformed is None, transformed
                            # don't do anything, didn't return anything
                    if len(state.errors) != 0:
                        # need a second check here to get out of the enclosing loop
                        break
                    # don't need to update the field, it was a ptr to a list so should
                    # already be updated
                else:
                    _descend(field_val)
                    if len(state.errors) != 0:
                        break
                    transformed = self._visit(field_val, state)
                    if len(state.errors) != 0:
                        break
                    if isinstance(transformed, Ast):
                        setattr(node, field.name, transformed)
                    elif transformed is Transformer.Delete:
                        # just delete it
                        setattr(node, field.name, None)
                    else:
                        # cannot return a list if the original attr wasn't a list
                        assert transformed is None, transformed
                        # don't do anything, didn't return anything

        _descend(start)
        self._visit(start, state)


MAJOR_VERSION = 0
MINOR_VERSION = 3
PATCH_VERSION = 0
SCHEMA_VERSION = 3

HEADER_FORMAT = "!BBBBBHI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


@dataclass
class Header:
    majorVersion: int
    minorVersion: int
    patchVersion: int
    schemaVersion: int
    argumentCount: int
    statementCount: int
    bodySize: int


FOOTER_FORMAT = "!I"
FOOTER_SIZE = struct.calcsize(FOOTER_FORMAT)


@dataclass
class Footer:
    crc: int


def deserialize_directives(bytes: bytes) -> list[Directive]:
    header = Header(*struct.unpack_from(HEADER_FORMAT, bytes))

    if header.schemaVersion != SCHEMA_VERSION:
        raise RuntimeError(
            f"Schema version wrong (expected {SCHEMA_VERSION} found {header.schemaVersion})"
        )

    dirs = []
    idx = 0
    offset = HEADER_SIZE
    while idx < header.statementCount:
        offset_and_dir = Directive.deserialize(bytes, offset)
        if offset_and_dir is None:
            raise RuntimeError("Unable to deserialize sequence")
        offset, dir = offset_and_dir
        dirs.append(dir)
        idx += 1

    if offset != len(bytes) - FOOTER_SIZE:
        raise RuntimeError(
            f"{len(bytes) - FOOTER_SIZE - offset} extra bytes at end of sequence"
        )

    return dirs


def serialize_directives(dirs: list[Directive]) -> tuple[bytes, int]:
    output_bytes = bytes()

    for dir in dirs:
        dir_bytes = dir.serialize()
        if len(dir_bytes) > MAX_DIRECTIVE_SIZE:
            print(
                CompileError(
                    f"Directive {dir} in sequence too large (expected less than {MAX_DIRECTIVE_SIZE}, was {len(dir_bytes)})"
                )
            )
            exit(1)
        output_bytes += dir_bytes

    header = Header(
        MAJOR_VERSION,
        MINOR_VERSION,
        PATCH_VERSION,
        SCHEMA_VERSION,
        0,
        len(dirs),
        len(output_bytes),
    )
    output_bytes = struct.pack(HEADER_FORMAT, *astuple(header)) + output_bytes

    crc = zlib.crc32(output_bytes) % (1 << 32)
    footer = Footer(crc)
    output_bytes += struct.pack(FOOTER_FORMAT, *astuple(footer))

    return output_bytes, crc
