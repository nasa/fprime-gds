from abc import ABC
import argparse
import inspect
from pathlib import Path
from dataclasses import dataclass, field, fields
import traceback
from typing import Callable

from fprime_gds.common.fpy.bytecode.directives import (
    AllocateStackDirective,
    ConstCmdDirective,
    FloatAddDirective,
    FloatDivideDirective,
    FloatExponentDirective,
    FloatFloorDivideDirective,
    FloatMultiplyDirective,
    FloatSubtractDirective,
    FloatToSignedIntDirective,
    FloatToUnsignedIntDirective,
    FloatTruncateDirective,
    IntAddDirective,
    IntDivideDirective,
    IntModuloDirective,
    IntMultiplyDirective,
    IntSubtractDirective,
    IntegerTruncateDirective,
    LogDirective,
    SignedIntegerExtendDirective,
    StackCmdDirective,
    StorePrmDirective,
    IntegerZeroExtendDirective,
    serialize_directives,
    BINARY_COMPARISON_DIRECTIVES,
    FLOAT_INEQUALITY_DIRECTIVES,
    INT_EQUALITY_DIRECTIVES,
    INT_SIGNED_INEQUALITY_DIRECTIVES,
    INT_UNSIGNED_INEQUALITY_DIRECTIVES,
    AndDirective,
    Directive,
    FloatExtendDirective,
    IntEqualDirective,
    ExitDirective,
    FloatEqualDirective,
    FloatNotEqualDirective,
    LoadDirective,
    StoreTlmValDirective,
    GotoDirective,
    IfDirective,
    NotDirective,
    IntNotEqualDirective,
    OrDirective,
    PushValDirective,
    SignedIntToFloatDirective,
    StoreDirective,
    UnsignedIntToFloatDirective,
    WaitAbsDirective,
    WaitRelDirective,
)
from fprime_gds.common.fpy.model import WORD_SIZE
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
    AstAdd,
    AstAnd,
    AstBoolean,
    AstComparison,
    AstElif,
    AstElifs,
    AstExpr,
    AstDiv,
    AstGetAttr,
    AstGetItem,
    AstFloorDiv,
    AstMath,
    AstModulo,
    AstMul,
    AstNot,
    AstNumber,
    AstOr,
    AstPow,
    AstReference,
    AstScopedBody,
    AstString,
    Ast,
    AstSub,
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


MACROS: dict[str, FpyMacro] = {
    "sleep": FpyMacro(NothingType, [("seconds", F64Type)], WaitRelDirective),
    "sleep_until": FpyMacro(NothingType, [("wakeup_time", TimeType)], WaitAbsDirective),
    "exit": FpyMacro(NothingType, [("success", BoolType)], ExitDirective),
    "log": FpyMacro(F64Type, [("operand", F64Type)], LogDirective),
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
    type: FppTypeClass | None = None
    """the resolved type of the variable. None if type unsure at the moment"""
    lvar_offset: int | None = None
    """the index of the lvar it is stored in"""


# a namespace is just a mapping of strings to FpyReferences
# essentially, it is a name which only exists as a qualifier, and doesn't have a value
# on its own
FpyNamespace = dict[str, "FpyReference"]


def create_namespace(
    references: dict[str, "FpyReference"],
) -> FpyNamespace:
    """from a flat dict of strs to references, creates a hierarchical, namespaced
    dict. no two leaf nodes may have the same name"""

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
    """returns the two namespaces, joined into one. if there is a conflict, chooses lhs over rhs"""
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
        # reference to a namespace. namespaces don't have values
        result_type = NothingType
    else:
        assert False, ref

    return result_type


@dataclass
class CompileState:
    """a collection of input, internal and output state variables and maps"""

    types: FpyNamespace
    """a namespace whose leaf nodes are subclasses of BaseType"""
    callables: FpyNamespace
    """a namespace whose leaf nodes are FpyCallable instances"""
    tlms: FpyNamespace
    """a namespace whose leaf nodes are ChTemplates"""
    prms: FpyNamespace
    """a namespace whose leaf nodes are PrmTemplates"""
    consts: FpyNamespace
    """a namespace whose leaf nodes are instances of subclasses of BaseType"""
    variables: FpyNamespace = field(default_factory=dict)
    """a namespace whose leaf nodes are FpyVariables"""
    runtime_values: FpyNamespace = None
    """a namespace whose leaf nodes are tlms/prms/consts/variables, all of which
    have some value at runtime."""

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
    """finds all variable declarations and adds them to the variable namespace"""

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
    """for each reference, resolve it in a specific namespace based on its
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
            # parent is a namespace
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
            # right now we don't support resolving index after a callable/type/namespace
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
                f"{value_type} has non-constant sized members, cannot access members",
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

    def resolve_if_ref(
        self, node: AstExpr, ns: FpyNamespace, state: CompileState
    ) -> bool:
        """if the node is a reference, try to resolve it in the given namespace, and return true if success.
        otherwise, if it is not a reference, return true as it doesn't need to be resolved
        """
        if not isinstance(node, AstReference):
            return True

        return self.resolve_ref_in_ns(node, ns, state) is not None

    def resolve_ref_in_ns(
        self, node: AstExpr, ns: FpyNamespace, state: CompileState
    ) -> FpyReference | None:
        """recursively resolves a reference in a namespace, returning the resolved ref
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

    def visit_AstComparison(self, node: AstComparison, state: CompileState):
        # lhs/rhs side of comparison, if they are refs, must be refs to "runtime vals"
        if not self.resolve_if_ref(node.lhs, state.runtime_values, state):
            state.err("Unknown runtime value", node.lhs)
            return
        if not self.resolve_if_ref(node.rhs, state.runtime_values, state):
            state.err("Unknown runtime value", node.rhs)
            return

    def visit_AstAnd_AstOr(self, node: AstAnd | AstOr, state: CompileState):
        for val in node.values:
            if not self.resolve_if_ref(val, state.runtime_values, state):
                state.err("Unknown runtime value", val)
                return

    def visit_AstNot(self, node: AstNot, state: CompileState):
        if not self.resolve_if_ref(node.value, state.runtime_values, state):
            state.err("Unknown runtime value", node.value)
            return

    def visit_AstMath(self, node: AstMath, state: CompileState):
        if not self.resolve_if_ref(node.lhs, state.runtime_values, state):
            state.err("Unknown runtime value", node.lhs)
            return
        if not self.resolve_if_ref(node.rhs, state.runtime_values, state):
            state.err("Unknown runtime value", node.rhs)
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

        if not self.resolve_if_ref(node.value, state.consts, state):
            state.err("Unknown const", node.value)
            return


class CalculateExprTypes(Visitor):
    """stores in state the fprime type of each expression, or NothingType if the expr had no type"""

    def visit_AstNumber(self, node: AstNumber, state: CompileState):
        if isinstance(node.value, float):
            result_type = FloatType
        else:
            # ints can be converted to either float or int
            result_type = NumericalType
        state.expr_types[node] = result_type

    def visit_AstMath(self, node: AstMath, state: CompileState):
        lhs_type = state.expr_types[node.lhs]
        rhs_type = state.expr_types[node.rhs]

        if isinstance(node, AstPow):
            # pow always returns float
            state.expr_types[node] = FloatType
            return

        if isinstance(node, AstModulo):
            # modulo always returns int
            state.expr_types[node] = IntegerType
            return

        if issubclass(lhs_type, FloatType) or issubclass(rhs_type, FloatType):
            # if either arg is a float, result must be a float (cannot be used as
            # an int)
            state.expr_types[node] = FloatType
            return

        # otherwise, result can be any number as int can be converted to float, or remain int
        state.expr_types[node] = NumericalType

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
    """for each syntactic node with arguments (ands/ors/nots/cmps/funcs), check that the argument
    types are right"""

    def is_type_interpretable_as(
        self, from_type: FppTypeClass, to_type: FppTypeClass
    ) -> bool:
        return issubclass(to_type, from_type)

    def visit_AstMath(self, node: AstMath, state: CompileState):

        lhs_type = state.expr_types[node.lhs]
        rhs_type = state.expr_types[node.rhs]

        if not issubclass(lhs_type, NumericalType):
            state.err(f"Cannot do math on non-numeric type {lhs_type}", node.lhs)
            return
        if not issubclass(rhs_type, NumericalType):
            state.err(f"Cannot do math on non-numeric type {rhs_type}", node.rhs)
            return

        # args are both numeric

        # TODO account for pow and modulo

        if lhs_type == NumericalType:
            # it can be converted into any number. pick int
            state.expr_types[node.lhs] = I64Type
        if rhs_type == NumericalType:
            # it can be converted into any number. pick int
            state.expr_types[node.rhs] = I64Type

        # if either is generic float, pick F64. we want F64 cuz otherwise we need
        # an FPEXT to convert to F64
        if lhs_type == FloatType:
            state.expr_types[node.lhs] = F64Type
        if rhs_type == FloatType:
            state.expr_types[node.rhs] = F64Type

        unsigned = (
            lhs_type in UNSIGNED_INTEGER_TYPES or rhs_type in UNSIGNED_INTEGER_TYPES
        )

        # if either is generic int, pick 64 bit wide. signedness depending on the other type
        # or if other type is unspecified signedness, pick I64
        if lhs_type == IntegerType:
            if unsigned:
                state.expr_types[node.lhs] = U64Type
            else:
                state.expr_types[node.lhs] = I64Type

        if rhs_type == IntegerType:
            if unsigned:
                state.expr_types[node.rhs] = U64Type
            else:
                state.expr_types[node.rhs] = I64Type

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

        if lhs_type == NumericalType:
            # it can be converted into any number. pick int
            state.expr_types[node.lhs] = I64Type
        if rhs_type == NumericalType:
            # it can be converted into any number. pick int
            state.expr_types[node.rhs] = I64Type

        # if either is generic float, pick F64. we want F64 cuz otherwise we need
        # an FPEXT to convert to F64
        if lhs_type == FloatType:
            state.expr_types[node.lhs] = F64Type
        if rhs_type == FloatType:
            state.expr_types[node.rhs] = F64Type

        if lhs_type == IntegerType and rhs_type == IntegerType:
            # if both are generic ints use i64
            state.expr_types[node.lhs] = I64Type
            state.expr_types[node.rhs] = I64Type
            return

        if lhs_type == IntegerType:
            # try to interpret it as the rhs_type if rhs_type is integer
            if issubclass(rhs_type, IntegerType):
                state.expr_types[node.lhs] = state.expr_types[node.rhs]
            else:
                # otherwise rhs is a float. just use i64
                state.expr_types[node.lhs] = I64Type

        if rhs_type == IntegerType:
            # try to interpret it as the rhs_type if rhs_type is integer
            if issubclass(lhs_type, IntegerType):
                state.expr_types[node.rhs] = state.expr_types[node.lhs]
            else:
                # otherwise lhs is a float. just use i64
                state.expr_types[node.rhs] = I64Type

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

            # the type of the arg is a subclass of the value
            #
            if self.is_type_interpretable_as(value_expr_type, arg_type):
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
            if val_type != BoolType:
                state.err(f"Arguments to 'and'/'or' must be booleans", val)
                return
            state.expr_types[val] = BoolType

    def visit_AstNot(self, node: AstNot, state: CompileState):
        val_type = state.expr_types[node.value]
        if val_type != BoolType:
            state.err(f"Argument to 'not' must be boolean", node.value)
            return
        state.expr_types[node.value] = BoolType

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        var_type = state.resolved_references[node.variable].type
        value_type = state.expr_types[node.value]

        if not self.is_type_interpretable_as(value_type, var_type):
            state.err(f"Cannot interpret {node.value} as {var_type}", node.value)
            return

        state.expr_types[node.value] = var_type

    def visit_AstGetItem(self, node: AstGetItem, state: CompileState):
        # the node of the index number has no expression value, it's an arg
        # but only at syntax level
        state.expr_types[node.item] = NothingType


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
            # a ref to a namespace doesn't have a value
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

    def visit_AstTest(self, node: AstTest, state: CompileState):
        # we do not calculate compile time value of or/and/nots/cmps at the moment
        state.expr_values[node] = None

    def visit_AstMath(self, node: AstMath, state: CompileState):
        # we do not calculate compile time value of arithmetic ops at the moment
        state.expr_values[node] = None

    def visit_default(self, node, state):
        # coding error, missed an expr
        assert not isinstance(node, AstExpr), node


class GenerateVariableDirectives(Visitor):
    """for each variable assignment or declaration, check the rhs was known
    at compile time, and generate a directive"""

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        existing_var = state.resolved_references[node.variable]
        # should already have been put in var table
        assert existing_var is not None

        # we should have type info about the variable
        assert existing_var.type is not None

        value_type = state.expr_types[node.value]
        value = state.expr_values[node.value]

        # already type checked
        assert value_type == type(value), (value_type, type(value))

        if value is None:
            # expr value is unknown at this point in compile
            state.err(
                f"Cannot assign {node.variable.var}: {existing_var.type} to {node.value}, as its value was not known at compile time",
                node.value,
            )
            return

        val_bytes = value.serialize()
        assert len(val_bytes) == value.getMaxSize(), (
            len(val_bytes),
            value.getMaxSize(),
            value,
        )

        lvar_offset = existing_var.lvar_offset
        if lvar_offset is None:
            # doesn't have an lvar idx, allocate one
            lvar_offset = state.lvar_array_size_bytes
            state.lvar_array_size_bytes += len(val_bytes)
            existing_var.lvar_offset = lvar_offset

        # then push the number to the stack, and then store that in an lvar
        state.directives[node] = [
            PushValDirective(val_bytes),
            StoreDirective(lvar_offset, len(val_bytes)),
        ]


class GenerateConstExprDirectives(Visitor):
    """for each expr with a constant compile time value, generate
    directives for how to put it in its register"""

    def visit_AstExpr(self, node: AstExpr, state: CompileState):
        expr_type = state.expr_types[node]

        if node in state.directives:
            # already have directives associated with this node
            return

        if expr_type == NothingType:
            # impossible. nothing type has no value
            state.directives[node] = None
            return

        if expr_type.getMaxSize() > WORD_SIZE:
            # bigger than 8 bytes
            # impossible. can't fit in a operand stack word
            state.directives[node] = None
            return

        # okay, it is not nothing and it is smaller than 8 bytes.
        # should be able to put it on stack

        expr_value = state.expr_values[node]

        if expr_value is None:
            # no const value
            return

        # it has a constant value at compile time
        serialized_expr_value = expr_value.serialize()
        assert len(serialized_expr_value) <= WORD_SIZE, len(serialized_expr_value)

        # push it to the stack
        state.directives[node] = [PushValDirective(serialized_expr_value)]


class GenerateExprMacrosAndCmds(Visitor):
    """for each expr whose value is not known at compile time, but can be calculated at run time,
    generate directives to calculate the value and put it in its register. for each command 
    or macro, generate directives for calling them with appropriate arg values"""

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

        return [IntegerTruncateDirective(8, new_size)]

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
        to_size = 8

        dir_type = (
            SignedIntegerExtendDirective
            if type in SIGNED_INTEGER_TYPES
            else IntegerZeroExtendDirective
        )

        return [dir_type(from_size, to_size)]

    def convert_to_type(
        self, from_type: FppTypeClass, to_type: FppTypeClass
    ) -> list[Directive]:
        assert from_type.getMaxSize() == 8, from_type
        assert to_type.getMaxSize() == 8, to_type

        if from_type == to_type:
            return []

        if from_type == F64Type:
            if to_type == I64Type:
                return [FloatToSignedIntDirective()]
            else:
                return [FloatToUnsignedIntDirective()]
        elif from_type == U64Type:
            if to_type == I64Type:
                # conversion between signed/unsigned doesn't do anything
                return []
            else:
                return [UnsignedIntToFloatDirective()]
        elif from_type == I64Type:
            if to_type == U64Type:
                return []
            else:
                return [SignedIntToFloatDirective()]

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
            state.lvar_array_size_bytes += expr_type.getMaxSize()
            directives.append(
                StoreTlmValDirective(base_ref.get_id(), offset_in_lvar_array)
            )
        elif isinstance(base_ref, PrmTemplate):
            # put it in an lvar
            offset_in_lvar_array = state.lvar_array_size_bytes
            state.lvar_array_size_bytes += expr_type.getMaxSize()
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

        state.directives[node] = directives

    def visit_AstAnd_AstOr(self, node: AstAnd | AstOr, state: CompileState):
        if node in state.directives:
            # already know how to put it on stack, or know that it's impossible
            return

        directives = []

        for arg_value_expr in node.values:
            arg_value_dirs = state.directives[arg_value_expr]
            assert arg_value_dirs is not None
            directives.extend(arg_value_dirs)

        # okay, now we have to "or" or "and" together all of the stack
        # "or/and" the first two together, then result goes on stack
        # continue doing this, once for each arg

        dir_type = OrDirective if isinstance(node, AstOr) else AndDirective

        for i in range(0, len(node.values) - 1):
            directives.append(dir_type())

        state.directives[node] = directives

    def visit_AstNot(self, node: AstNot, state: CompileState):
        if node in state.directives:
            # already know how to put it on stack
            return

        directives = []
        arg_value_dirs = state.directives[node.value]
        assert arg_value_dirs is not None
        directives.extend(arg_value_dirs)
        directives.append(NotDirective())

        state.directives[node] = directives

    def visit_AstMath(self, node: AstMath, state: CompileState):
        if node in state.directives:
            # already know how to put it on stack
            return

        directives = []

        result_type = state.expr_types[node]

        assert result_type in NUMERIC_TYPES, result_type

        lhs_type = state.expr_types[node.lhs]
        rhs_type = state.expr_types[node.rhs]

        lhs_dirs = state.directives[node.lhs]
        rhs_dirs = state.directives[node.rhs]

        # get both sides to 64 bit
        lhs_dirs.extend(self.extend_to_64_bits(lhs_type))
        rhs_dirs.extend(self.extend_to_64_bits(rhs_type))

        fp = False
        if issubclass(lhs_type, FloatType) or issubclass(rhs_type, FloatType):
            fp = True
            # convert both sides to float
            if issubclass(lhs_type, IntegerType):
                if lhs_type in UNSIGNED_INTEGER_TYPES:
                    lhs_dirs.append(UnsignedIntToFloatDirective())
                else:
                    lhs_dirs.append(SignedIntToFloatDirective())
            # convert int to float if necessary
            if issubclass(rhs_type, IntegerType):
                if rhs_type in UNSIGNED_INTEGER_TYPES:
                    rhs_dirs.append(UnsignedIntToFloatDirective())
                else:
                    rhs_dirs.append(SignedIntToFloatDirective())

        # what type do we operate on in the middle?
        intermediate_type = None
        if fp:
            intermediate_type = F64Type
        else:
            # if either side is signed, consider both sides as signed
            if lhs_type in SIGNED_INTEGER_TYPES or rhs_type in SIGNED_INTEGER_TYPES:
                intermediate_type = I64Type
            else:
                intermediate_type = U64Type

        directives.extend(lhs_dirs)
        directives.extend(rhs_dirs)

        dir_type = None

        if isinstance(node, AstFloorDiv):
            if fp:
                dir_type = FloatFloorDivideDirective
            else:
                # integer division is always floor div
                dir_type = IntDivideDirective
        elif isinstance(node, AstDiv):
            if fp:
                dir_type = FloatDivideDirective
            else:
                dir_type = IntDivideDirective
        elif isinstance(node, AstMul):
            if fp:
                dir_type = FloatMultiplyDirective
            else:
                dir_type = IntMultiplyDirective
        elif isinstance(node, AstAdd):
            if fp:
                dir_type = FloatAddDirective
            else:
                dir_type = IntAddDirective
        elif isinstance(node, AstSub):
            if fp:
                dir_type = FloatSubtractDirective
            else:
                dir_type = IntSubtractDirective
        elif isinstance(node, AstPow):
            dir_type = FloatExponentDirective
        elif isinstance(node, AstModulo):
            dir_type = IntModuloDirective
        else:
            assert False, node

        directives.append(dir_type())

        # okay now convert the intermediate type to the result type, but with 64 bits
        result_type_64_bits = (
            I64Type
            if result_type in SIGNED_INTEGER_TYPES
            else U64Type if result_type in UNSIGNED_INTEGER_TYPES else F64Type
        )
        directives.extend(self.convert_to_type(intermediate_type, result_type_64_bits))

        # okay now turn it back into the desired bitwidth
        directives.extend(
            self.truncate_from_64_bits(intermediate_type, result_type.getMaxSize())
        )

        state.directives[node] = directives

    def visit_AstComparison(self, node: AstComparison, state: CompileState):
        if node in state.directives:
            # already know how to put it on stack
            return

        directives = []

        lhs_type = state.expr_types[node.lhs]
        rhs_type = state.expr_types[node.rhs]

        lhs_dirs = state.directives[node.lhs]
        rhs_dirs = state.directives[node.rhs]

        # get both sides to 64 bit
        lhs_dirs.extend(self.extend_to_64_bits(lhs_type))
        rhs_dirs.extend(self.extend_to_64_bits(rhs_type))

        fp = False
        if issubclass(lhs_type, FloatType) or issubclass(rhs_type, FloatType):
            fp = True
            # convert both sides to float
            if issubclass(lhs_type, IntegerType):
                if lhs_type in UNSIGNED_INTEGER_TYPES:
                    lhs_dirs.append(UnsignedIntToFloatDirective())
                else:
                    lhs_dirs.append(SignedIntToFloatDirective())
            # convert int to float if necessary
            if issubclass(rhs_type, IntegerType):
                if rhs_type in UNSIGNED_INTEGER_TYPES:
                    rhs_dirs.append(UnsignedIntToFloatDirective())
                else:
                    rhs_dirs.append(SignedIntToFloatDirective())

        directives.extend(lhs_dirs)
        directives.extend(rhs_dirs)

        dir_type = None

        if node.op.value == "==":
            if fp:
                dir_type = FloatEqualDirective
            else:
                dir_type = IntEqualDirective
        elif node.op.value == "!=":
            if fp:
                dir_type = FloatNotEqualDirective
            else:
                dir_type = IntNotEqualDirective
        else:

            if fp:
                dir_type = FLOAT_INEQUALITY_DIRECTIVES[node.op.value]
            else:
                # if either is unsigned, consider both as unsigned
                unsigned = (
                    lhs_type in UNSIGNED_INTEGER_TYPES
                    or rhs_type in UNSIGNED_INTEGER_TYPES
                )

                if unsigned:
                    dir_type = INT_UNSIGNED_INEQUALITY_DIRECTIVES[node.op.value]
                else:
                    dir_type = INT_SIGNED_INEQUALITY_DIRECTIVES[node.op.value]

        assert dir_type is not None

        directives.append(dir_type())

        state.directives[node] = directives

    def visit_AstFuncCall(self, node: AstFuncCall, state: CompileState):
        node_args = node.args if node.args is not None else []
        func = state.resolved_references[node.func]
        dirs = []
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
                # first push cmd opcode to stack as u32
                dirs.append(
                    PushValDirective(U32Type(func.cmd.get_op_code()).serialize())
                )
                # push all args to the stack
                # keep track of how many bytes total we have pushed
                for arg_node in node_args:
                    node_dirs = state.directives[arg_node]
                    assert len(node_dirs) >= 1
                    dirs.extend(node_dirs)
                    arg_byte_count = state.expr_types[arg_node].getMaxSize()

                # now that all args are pushed to the stack, pop them and opcode off the stack
                # as a command
                dirs.append(StackCmdDirective(arg_byte_count + 4))
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

        state.directives[node] = dirs


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
            dirs.append(AllocateStackDirective(state.lvar_array_size_bytes))
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

    callable_name_dict: dict[str, FpyCallable] = {}
    # add all cmds to the callable dict
    for name, cmd in cmd_name_dict.items():
        cmd: CmdTemplate
        args = []
        for arg_name, _, arg_type in cmd.arguments:
            args.append((arg_name, arg_type))
        # cmds are thought of as callables with a "NothingType" return value
        callable_name_dict[name] = FpyCmd(NothingType, args, cmd)

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
        tlms=create_namespace(ch_name_dict),
        prms=create_namespace(prm_name_dict),
        types=create_namespace(type_name_dict),
        callables=create_namespace(callable_name_dict),
        consts=create_namespace(enum_const_name_dict),
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
        # now that we know what all refs point to, we should be able to figure out the type
        # of every expression
        CalculateExprTypes(),
        # now that we know the type of each expr, we can type check all function calls
        # and also narrow down ambiguous argument types
        CheckAndResolveArgumentTypes(),
        # okay, now that we're sure we're passing in all the right args to each func,
        # we can calculate values of type ctors etc etc
        CalculateConstExprValues(),
        # now that we know variable values, we can generate directives for vars
        GenerateVariableDirectives(),
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
