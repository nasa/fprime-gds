from __future__ import annotations
from abc import ABC
import inspect
from dataclasses import astuple, dataclass, field, fields
from pathlib import Path
import struct
import traceback
import typing
from typing import Union, get_origin, get_args
import zlib

from fprime_gds.common.fpy.model import DirectiveErrorCode
from fprime_gds.common.fpy.types import (
    SPECIFIC_FLOAT_TYPES,
    SPECIFIC_INTEGER_TYPES,
    MACROS,
    MAX_DIRECTIVE_SIZE,
    MAX_DIRECTIVES_COUNT,
    SPECIFIC_NUMERIC_TYPES,
    SIGNED_INTEGER_TYPES,
    UNSIGNED_INTEGER_TYPES,
    ArrayIndexType,
    CompileState,
    FieldReference,
    FppTypeClass,
    FpyCallable,
    FpyCmd,
    FpyMacro,
    FpyReference,
    FpyScope,
    FpyTypeCtor,
    FpyVariable,
    InternalIntType,
    InternalStringType,
    NothingType,
    TopDownVisitor,
    Visitor,
    convert_numeric_type,
    create_scope,
    get_ref_fpp_type_class,
    is_instance_compat,
)

from fprime_gds.common.fpy.error import CompileError

# In Python 3.10+, the `|` operator creates a `types.UnionType`.
# We need to handle this for forward compatibility, but it won't exist in 3.9.
try:
    from types import UnionType

    UNION_TYPES = (Union, UnionType)
except ImportError:
    UNION_TYPES = (Union,)

from fprime_gds.common.fpy.bytecode.directives import (
    BINARY_STACK_OPS,
    BOOLEAN_OPERATORS,
    NUMERIC_OPERATORS,
    UNARY_STACK_OPS,
    AllocateDirective,
    AssertDirective,
    BinaryStackOp,
    ConstCmdDirective,
    DuplicateDirective,
    FloatMultiplyDirective,
    FloatTruncateDirective,
    GetMemberDirective,
    IntAddDirective,
    IntMultiplyDirective,
    LoadDirective,
    MemCompareDirective,
    NoOpDirective,
    IntegerTruncate64To16Directive,
    IntegerTruncate64To32Directive,
    IntegerTruncate64To8Directive,
    IntegerSignedExtend16To64Directive,
    IntegerSignedExtend32To64Directive,
    IntegerSignedExtend8To64Directive,
    StackCmdDirective,
    IntegerZeroExtend16To64Directive,
    IntegerZeroExtend32To64Directive,
    IntegerZeroExtend8To64Directive,
    Directive,
    FloatExtendDirective,
    GotoDirective,
    IfDirective,
    NotDirective,
    PushValDirective,
    SignedIntToFloatDirective,
    StoreConstOffsetDirective,
    StoreDirective,
    PushPrmDirective,
    PushTlmValDirective,
    UnaryStackOp,
    UnsignedGreaterThanOrEqualDirective,
    UnsignedIntToFloatDirective,
    UnsignedLessThanDirective,
)
from fprime_gds.common.loaders.ch_json_loader import ChJsonLoader
from fprime_gds.common.loaders.cmd_json_loader import CmdJsonLoader
from fprime_gds.common.loaders.event_json_loader import EventJsonLoader
from fprime_gds.common.loaders.prm_json_loader import PrmJsonLoader
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime_gds.common.templates.prm_template import PrmTemplate
from fprime.common.models.serialize.time_type import TimeType
from fprime.common.models.serialize.enum_type import EnumType
from fprime.common.models.serialize.serializable_type import (
    SerializableType as StructType,
)
from fprime.common.models.serialize.array_type import ArrayType
from fprime.common.models.serialize.type_exceptions import TypeException
from fprime.common.models.serialize.numerical_types import (
    U32Type,
    U16Type,
    U64Type,
    U8Type,
    I64Type,
    F32Type,
    F64Type,
    FloatType,
    IntegerType,
    NumericalType,
)
from fprime.common.models.serialize.string_type import StringType
from fprime.common.models.serialize.bool_type import BoolType
from fprime_gds.common.fpy.parser import (
    AstAssert,
    AstBinaryOp,
    AstBoolean,
    AstElif,
    AstElifs,
    AstExpr,
    AstFor,
    AstGetAttr,
    AstGetItem,
    AstNumber,
    AstOp,
    AstReference,
    AstScopedBody,
    AstStmtWithExpr,
    AstString,
    Ast,
    AstBody,
    AstLiteral,
    AstIf,
    AstAssign,
    AstFuncCall,
    AstUnaryOp,
    AstVar,
    AstWhile,
)
from fprime.common.models.serialize.type_base import BaseType as FppType


class AssignIds(TopDownVisitor):
    """assigns a unique id to each node to allow it to be indexed in a dict"""

    def __init__(self):
        self.next_id = 0

    def visit_default(self, node, state):
        node.id = self.next_id
        self.next_id += 1


class SetLocalScope(Visitor):
    def __init__(self, scope: FpyScope):
        self.scope = scope

    def visit_default(self, node: Ast, state: CompileState):
        state.local_scopes[node] = self.scope


class AssignLocalScopes(TopDownVisitor):

    def visit_AstScopedBody(self, node: AstScopedBody, state: CompileState):
        parent_scope = state.local_scopes.get(node)
        # make a new scope
        scope = FpyScope()
        state.scope_parents[scope] = parent_scope
        # TODO ask rob there must be a better way to do this, that isn't as slow
        SetLocalScope(scope).run(node, state)


class CreateVariables(TopDownVisitor):
    """finds all variable declarations and adds them to the variable scope"""

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        if not isinstance(node.lhs, AstReference):
            state.err("Invalid assignment", node.lhs)
            return
        # okay, what are we assigning to?
        if isinstance(node.lhs, AstVar):
            # assigning to an FpyVariable
            existing = state.local_scopes[node].get(node.lhs.var)
            if not existing:
                # idk what this var is. make sure it's a valid declaration
                if node.type_ann is None:
                    # error because this isn't an annotated assignment. right now all declarations must be annotated
                    state.err(
                        "Must provide a type annotation for new variables",
                        node.lhs,
                    )
                    return

                var = FpyVariable(node.type_ann, node)
                # new var. put it in the table under this scope
                state.local_scopes[node][node.lhs.var] = var

            if existing and node.type_ann is not None:
                # redeclaring an existing variable
                state.err(f"{node.lhs.var} already declared", node)
                return
        else:
            # assigning to a member or array element. don't need to make a new variable,
            # space already exists
            if node.type_ann is not None:
                # type annotation on a field assignment... it already has a type!
                state.err("Cannot specify a type annotation for a field", node.type_ann)
                return

    def visit_AstFor(self, node: AstFor, state: CompileState):
        # for loops have an implicit loop variable that they declare inside of their scoped body
        existing = state.local_scopes[node.body].get(node.loop_var.var)

        if existing:
            # redeclaring an existing variable
            # i don't think this should be possible. this var should be "declared" before
            # anything else inside of its scope gets visited
            assert False, (node, state.local_scopes[node.body])

        var = FpyVariable(node.loop_var_type, node)
        state.local_scopes[node.body][node.loop_var.var] = var
        # the loop var should get resolved in the body
        state.local_scopes[node.loop_var] = state.local_scopes[node.body]


class CheckUseBeforeDeclare(TopDownVisitor):

    def __init__(self):
        self.currently_declared_vars: list[FpyVariable] = []

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        if not isinstance(node.lhs, AstVar):
            # definitely not a declaration, it's a field assignment
            return

        var = state.local_scopes[node][node.lhs.var]

        if var.declaration != node:
            # this is not the node that declares this variable
            return

        # this node declares this variable

        self.currently_declared_vars.append(var)

    def visit_AstFor(self, node: AstFor, state: CompileState):
        var = state.local_scopes[node.body][node.loop_var.var]

        self.currently_declared_vars.append(var)

    def visit_AstVar(self, node: AstVar, state: CompileState):
        ref = state.local_scopes[node].get(node.var)
        if ref is None:
            # not a variable, otherwise it would be in scope. might be a type name or smth
            return

        if (isinstance(ref.declaration, AstAssign) and ref.declaration.lhs == node) or (
            isinstance(ref.declaration, AstFor) and ref.declaration.loop_var == node
        ):
            # this is the initial name of the variable. don't crash
            return

        if ref not in self.currently_declared_vars:
            state.err(f"'{node.var}' used before declared", node)
            return


class ResolveVars(TopDownVisitor):
    def resolve_var_in_global_scope(
        self,
        node: Ast,
        global_scope: FpyScope,
        global_scope_name: str,
        state: CompileState,
    ) -> bool:
        if not isinstance(node, AstReference):
            return True

        if not isinstance(node, AstVar):
            return self.resolve_var_in_global_scope(
                node.parent, global_scope, global_scope_name, state
            )

        local_scope = state.local_scopes[node]
        resolved = None
        while local_scope is not None and resolved is None:
            resolved = local_scope.get(node.var)
            local_scope = state.scope_parents[local_scope]

        if resolved is None:
            # unable to find this symbol in the hierarchy of local scopes
            # look it up in the global scope
            resolved = global_scope.get(node.var)

        if resolved is None:
            state.err(f"Unknown {global_scope_name}", node)
            return False

        state.resolved_references[node] = resolved
        return True

    def visit_AstFuncCall(self, node: AstFuncCall, state: CompileState):
        if not self.resolve_var_in_global_scope(
            node.func, state.callables, "callable", state
        ):
            return

        for arg in node.args if node.args is not None else []:
            # arg value refs must have values at runtime
            if not self.resolve_var_in_global_scope(
                arg, state.runtime_values, "value", state
            ):
                return

    def visit_AstIf_AstElif(self, node: Union[AstIf, AstElif], state: CompileState):
        # if condition expr refs must be "runtime values" (tlm/prm/const/etc)
        if not self.resolve_var_in_global_scope(
            node.condition, state.runtime_values, "value", state
        ):
            return

    def visit_AstBinaryOp(self, node: AstBinaryOp, state: CompileState):
        # lhs/rhs side of stack op, if they are refs, must be refs to "runtime vals"
        if not self.resolve_var_in_global_scope(
            node.lhs, state.runtime_values, "value", state
        ):
            return
        if not self.resolve_var_in_global_scope(
            node.rhs, state.runtime_values, "value", state
        ):
            return

    def visit_AstUnaryOp(self, node: AstUnaryOp, state: CompileState):
        if not self.resolve_var_in_global_scope(
            node.val, state.runtime_values, "value", state
        ):
            return

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        if not self.resolve_var_in_global_scope(
            node.lhs, state.runtime_values, "value", state
        ):
            return

        if node.type_ann is not None:
            if not self.resolve_var_in_global_scope(
                node.type_ann, state.types, "value", state
            ):
                return
            # okay, we know the var, we know the type, let's update the var type
            # in the struct
            var = state.resolved_references[node.lhs]
            var_type = state.resolved_references[node.type_ann]
            assert isinstance(var, FpyVariable), var
            assert isinstance(var_type, type), var_type
            var.type = var_type

        if not self.resolve_var_in_global_scope(
            node.rhs, state.runtime_values, "value", state
        ):
            return

    def visit_AstFor(self, node: AstFor, state: CompileState):
        if not self.resolve_var_in_global_scope(
            node.loop_var, state.runtime_values, "value", state
        ):
            return
        if not self.resolve_var_in_global_scope(
            node.loop_var_type, state.types, "type", state
        ):
            return
        # okay, we know the var, we know the type, let's update the var type
        # in the struct
        loop_var = state.resolved_references[node.loop_var]
        loop_var_type = state.resolved_references[node.loop_var_type]
        assert isinstance(loop_var, FpyVariable), loop_var
        assert isinstance(loop_var_type, type), loop_var_type
        loop_var.type = loop_var_type
        if not self.resolve_var_in_global_scope(
            node.lower_bound, state.runtime_values, "value", state
        ):
            return
        if not self.resolve_var_in_global_scope(
            node.upper_bound, state.runtime_values, "value", state
        ):
            return

    def visit_AstWhile(self, node: AstWhile, state: CompileState):
        if not self.resolve_var_in_global_scope(
            node.condition, state.runtime_values, "value", state
        ):
            return

    def visit_AstAssert(self, node: AstAssert, state: CompileState):
        if not self.resolve_var_in_global_scope(
            node.condition, state.runtime_values, "value", state
        ):
            return
        if node.exit_code is not None:
            if not self.resolve_var_in_global_scope(
                node.exit_code, state.runtime_values, "value", state
            ):
                return

    def visit_AstVar(self, node: AstVar, state: CompileState):
        # make sure that all vars are resolved when we get to them
        # if not resolved, then the var is "outside" of a context which could resolve it
        if node not in state.resolved_references:
            state.err("Expression is invalid when used here", node)
            return

    def visit_AstGetItem(self, node: AstGetItem, state: CompileState):
        if not self.resolve_var_in_global_scope(
            node.item, state.runtime_values, "value", state
        ):
            return

    def visit_AstLiteral_AstGetAttr(
        self, node: Union[AstLiteral, AstGetAttr], state: CompileState
    ):
        # don't need to do anything for literals or getattr, but just have this here for completion's sake
        pass

    def visit_default(self, node, state):
        # coding error, missed an expr
        assert not is_instance_compat(node, AstStmtWithExpr), node


class PickTypesAndResolveAttrsAndItems(Visitor):

    def coerce_expr_type(
        self, node: AstExpr, type: FppTypeClass, state: CompileState
    ) -> bool:
        unconverted_type = state.expr_unconverted_types[node]
        if self.can_coerce_type(unconverted_type, type):
            state.expr_converted_types[node] = type
            return True
        state.err(f"Expected {type.__name__}, found {unconverted_type.__name__}", node)
        return False

    def can_coerce_type(self, type: FppTypeClass, to_type: FppTypeClass) -> bool:
        if type == to_type:
            return True
        if issubclass(type, IntegerType) and issubclass(to_type, NumericalType):
            # we can coerce any integer into any other number
            return True
        if issubclass(type, FloatType) and issubclass(to_type, FloatType):
            # we can convert any float into any float
            return True
        if type == InternalStringType and issubclass(to_type, StringType):
            # we can convert the internal String type to any string type
            return True

        return False

    def pick_intermediate_type(
        self, arg_types: list[FppTypeClass], op: BinaryStackOp | UnaryStackOp
    ) -> FppTypeClass:

        if op in BOOLEAN_OPERATORS:
            return BoolType

        non_numeric = any(not issubclass(t, NumericalType) for t in arg_types)

        if op == BinaryStackOp.EQUAL or op == BinaryStackOp.NOT_EQUAL:
            if non_numeric:
                if len(set(arg_types)) != 1:
                    # can only compare equality between the same types
                    return None
                return arg_types[0]

        # all arguments should be numeric
        if non_numeric:
            # cannot find intermediate type
            return None

        if op == BinaryStackOp.DIVIDE or op == BinaryStackOp.EXPONENT:
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

    def is_type_constant_size(self, type: FppTypeClass) -> bool:
        """return true if the type is statically sized"""
        if issubclass(type, StringType):
            return False

        if issubclass(type, ArrayType):
            return self.is_type_constant_size(type.MEMBER_TYPE)

        if issubclass(type, StructType):
            for _, arg_type, _, _ in type.MEMBER_LIST:
                if not self.is_type_constant_size(arg_type):
                    return False
            return True

        return True

    def get_members(
        self, node: Ast, parent_type: FppTypeClass, state: CompileState
    ) -> list[tuple[str, FppTypeClass]] | None:
        if not issubclass(parent_type, (StructType, TimeType)):
            return {}

        if not self.is_type_constant_size(parent_type):
            state.err(
                f"{parent_type} has dynamically-sized members, cannot access members",
                node,
            )
            return None

        member_list: list[tuple[str, FppTypeClass]] = None
        if issubclass(parent_type, StructType):
            member_list = [t[0:2] for t in parent_type.MEMBER_LIST]
        else:
            # if it is a time type, there are some "implied" members
            member_list = []
            member_list.append(("time_base", U16Type))
            member_list.append(("time_context", U8Type))
            member_list.append(("seconds", U32Type))
            member_list.append(("useconds", U32Type))
        return member_list

    def visit_AstGetAttr(self, node: AstGetAttr, state: CompileState):
        parent_ref = state.resolved_references.get(node.parent)

        if isinstance(parent_ref, (type, FpyCallable)):
            state.err("Unknown attribute", node)
            return

        ref = None
        if isinstance(parent_ref, dict):
            # getattr of a namespace
            # parent won't actually have a type
            ref = parent_ref.get(node.attr)
            if ref is None:
                state.err("Unknown attribute", node)
                return
        else:
            # in all other cases, parent has at least some sort of type
            # ref may be None (if parent is some complex expr), or it may be
            # a tlm chan or var or etc...
            # it may or may not have a compile time value, but it definitely has a type
            parent_type = state.expr_unconverted_types[node.parent]

            # field references store their "base reference", which is the first non-field-ref parent of
            # the field ref. this lets you easily check what actual underlying thing (tlm chan, variable, prm)
            # you're talking about a field of
            base_ref = (
                parent_ref
                if not isinstance(parent_ref, FieldReference)
                else parent_ref.base_ref
            )
            # we also calculate a "base offset" wrt. the start of the base_ref type, so you
            # can easily pick out this field from a value of the base ref type
            base_offset = (
                0
                if not isinstance(parent_ref, FieldReference)
                else parent_ref.base_offset
            )

            member_list = self.get_members(node, parent_type, state)
            if member_list is None:
                return

            offset = 0
            for arg_name, arg_type in member_list:
                if arg_name == node.attr:
                    ref = FieldReference(
                        is_struct_member=True,
                        parent_expr=node.parent,
                        type=arg_type,
                        base_ref=base_ref,
                        local_offset=offset,
                        base_offset=base_offset,
                        name=arg_name,
                    )
                    break
                offset += arg_type.getMaxSize()
                base_offset += arg_type.getMaxSize()

        if ref is None:
            state.err(
                f"{parent_type.__name__} has no member named {node.attr}",
                node,
            )
            return

        ref_type = get_ref_fpp_type_class(ref)

        state.resolved_references[node] = ref
        state.expr_unconverted_types[node] = ref_type
        state.expr_converted_types[node] = ref_type

    def visit_AstGetItem(self, node: AstGetItem, state: CompileState):
        parent_ref = state.resolved_references.get(node.parent)

        if isinstance(parent_ref, (type, FpyCallable, dict)):
            state.err("Unknown item", node)
            return

        # otherwise, we should definitely have a well-defined type for our parent expr

        parent_type = state.expr_unconverted_types[node.parent]

        if not self.is_type_constant_size(parent_type):
            state.err(
                f"{parent_type.__name__} has non-constant sized members, cannot access items",
                node,
            )
            return

        if not issubclass(parent_type, ArrayType):
            state.err(f"{parent_type.__name__} is not an array", node)
            return

        # coerce the index expression to array index type
        if not self.coerce_expr_type(node.item, ArrayIndexType, state):
            return

        base_ref = (
            parent_ref
            if not isinstance(parent_ref, FieldReference)
            else parent_ref.base_ref
        )

        ref = FieldReference(
            is_array_element=True,
            parent_expr=node.parent,
            type=parent_type.MEMBER_TYPE,
            base_ref=base_ref,
            idx_expr=node.item,
        )

        state.resolved_references[node] = ref
        state.expr_unconverted_types[node] = parent_type.MEMBER_TYPE
        state.expr_converted_types[node] = parent_type.MEMBER_TYPE

    def visit_AstVar(self, node: AstVar, state: CompileState):
        # already been resolved by SetScopes pass
        ref = state.resolved_references[node]
        if ref is None:
            return
        ref_type = get_ref_fpp_type_class(ref)

        state.expr_unconverted_types[node] = ref_type
        state.expr_converted_types[node] = ref_type

    def visit_AstNumber(self, node: AstNumber, state: CompileState):
        # give a best guess as to the final type of this node. we don't actually know
        # its bitwidth or signedness yet
        if isinstance(node.value, float):
            result_type = F64Type
        else:
            result_type = InternalIntType

        state.expr_unconverted_types[node] = result_type
        state.expr_converted_types[node] = result_type

    def visit_AstBinaryOp(self, node: AstBinaryOp, state: CompileState):
        lhs_type = state.expr_unconverted_types[node.lhs]
        rhs_type = state.expr_unconverted_types[node.rhs]

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
            node.op == BinaryStackOp.EQUAL or node.op == BinaryStackOp.NOT_EQUAL
        ) and intermediate_type not in SPECIFIC_NUMERIC_TYPES:
            dir = MemCompareDirective
        else:
            dir = BINARY_STACK_OPS[node.op][intermediate_type]

        result_type = None
        if node.op in NUMERIC_OPERATORS:
            result_type = intermediate_type
        else:
            result_type = BoolType

        state.stack_op_directives[node] = dir
        state.expr_unconverted_types[node] = result_type
        state.expr_converted_types[node] = result_type

    def visit_AstUnaryOp(self, node: AstUnaryOp, state: CompileState):
        val_type = state.expr_unconverted_types[node.val]

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
        state.expr_unconverted_types[node] = result_type
        state.expr_converted_types[node] = result_type

    def visit_AstString(self, node: AstString, state: CompileState):
        state.expr_unconverted_types[node] = InternalStringType
        state.expr_converted_types[node] = InternalStringType

    def visit_AstBoolean(self, node: AstBoolean, state: CompileState):
        state.expr_unconverted_types[node] = BoolType
        state.expr_converted_types[node] = BoolType

    def visit_AstFuncCall(self, node: AstFuncCall, state: CompileState):
        func = state.resolved_references.get(node.func)
        if not isinstance(func, FpyCallable):
            state.err("Unknown function", node.func)
            return
        func_args = func.args
        node_args = node.args if node.args else []

        if len(node_args) < len(func_args):
            state.errors.append(
                CompileError(
                    f"Missing arguments (expected {len(func_args)} found {len(node_args)})",
                    node,
                )
            )
            return
        if len(node_args) > len(func_args):
            state.errors.append(
                CompileError(
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
        state.expr_unconverted_types[node] = func.return_type
        state.expr_converted_types[node] = func.return_type

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        # should be present in resolved refs because we only let it through if
        # variable is attr, item or var
        lhs_ref = state.resolved_references[node.lhs]
        if not isinstance(lhs_ref, (FpyVariable, FieldReference)):
            state.err("Invalid assignment", node.lhs)
            return

        lhs_type = None
        if isinstance(lhs_ref, FpyVariable):
            lhs_type = lhs_ref.type
            if not self.coerce_expr_type(node.rhs, lhs_type, state):
                return
        else:
            # briefly check that we're only trying
            # to modify an fpy var
            if not isinstance(lhs_ref.base_ref, FpyVariable):
                state.err("Can only assign variables", node.lhs)
                return
            assert (
                state.expr_converted_types[node.lhs]
                == state.expr_unconverted_types[node.lhs]
            )
            lhs_type = state.expr_converted_types[node.lhs]

        # coerce the rhs into the lhs type
        if not self.coerce_expr_type(node.rhs, lhs_type, state):
            return

    def visit_AstAssert(self, node: AstAssert, state: CompileState):
        if not self.coerce_expr_type(node.condition, BoolType, state):
            return
        if node.exit_code is not None:
            if not self.coerce_expr_type(node.exit_code, U8Type, state):
                return

    def visit_AstFor(self, node: AstFor, state: CompileState):
        loop_var = state.resolved_references[node.loop_var]
        assert isinstance(loop_var, FpyVariable)
        if not self.coerce_expr_type(node.lower_bound, loop_var.type, state):
            return
        if not self.coerce_expr_type(node.upper_bound, loop_var.type, state):
            return

    def visit_AstWhile(self, node: AstWhile, state: CompileState):
        if not self.coerce_expr_type(node.condition, BoolType, state):
            return

    def visit_AstIf_AstElif(self, node: Union[AstIf, AstElif], state: CompileState):
        if not self.coerce_expr_type(node.condition, BoolType, state):
            return

    def visit_default(self, node, state):
        # coding error, missed an expr
        assert not is_instance_compat(node, AstStmtWithExpr), node


class AllocateVariables(Visitor):
    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        lhs_ref = state.resolved_references[node.lhs]
        if not isinstance(lhs_ref, FpyVariable):
            # it's a field ref, ignore it. don't need any more space for it
            return

        assert lhs_ref is not None
        assert lhs_ref.type is not None

        value_size = lhs_ref.type.getMaxSize()

        if lhs_ref.lvar_offset is None:
            # doesn't have an lvar idx, allocate one
            lvar_offset = state.lvar_array_size_bytes
            state.lvar_array_size_bytes += value_size
            lhs_ref.lvar_offset = lvar_offset

    def visit_AstFor(self, node: AstFor, state: CompileState):
        loop_var_ref = state.resolved_references[node.loop_var]
        assert isinstance(loop_var_ref, FpyVariable)
        lvar_offset = state.lvar_array_size_bytes
        state.lvar_array_size_bytes += loop_var_ref.type.getMaxSize()
        loop_var_ref.lvar_offset = lvar_offset


class CalculateConstExprValues(Visitor):
    """for each expr, try to calculate its constant value and store it in a map. stores None if no value could be
    calculated at compile time, and NothingType if the expr had no value"""

    def const_coerce_type(
        self, from_val: FppType, to_type: FppTypeClass, node: Ast, state: CompileState
    ) -> FppType | None:
        try:
            if type(from_val) == to_type:
                return from_val
            if issubclass(to_type, StringType):
                assert type(from_val) == InternalStringType, type(from_val)
                return to_type(from_val.val)
            if issubclass(to_type, FloatType):
                assert issubclass(type(from_val), NumericalType), type(from_val)
                return to_type(float(from_val.val))
            if issubclass(to_type, IntegerType):
                assert issubclass(type(from_val), IntegerType), type(from_val)
                return to_type(int(from_val.val))
            assert False, (from_val, type(from_val), to_type)
        except TypeException as e:
            state.err(f"For type {type(from_val).__name__}: {e}", node)
            return None

    def visit_AstLiteral(self, node: AstLiteral, state: CompileState):
        uncoerced_type = state.expr_unconverted_types[node]

        try:
            expr_value = uncoerced_type(node.value)
        except TypeException as e:
            state.err(f"For type {uncoerced_type.__name__}: {e}", node)
            return

        coerced_type = state.expr_converted_types[node]
        if coerced_type != uncoerced_type:
            expr_value = self.const_coerce_type(expr_value, coerced_type, node, state)
            if expr_value is None:
                return

        state.expr_converted_values[node] = expr_value

    def visit_AstGetAttr(self, node: AstGetAttr, state: CompileState):

        unconverted_type = state.expr_unconverted_types[node]
        converted_type = state.expr_converted_types[node]
        ref = state.resolved_references[node]
        expr_value = None
        if isinstance(ref, (type, dict, FpyCallable)):
            # these types have no value
            state.expr_converted_values[node] = NothingType()
            assert unconverted_type == converted_type, (
                unconverted_type,
                converted_type,
            )
            return
        elif isinstance(ref, (ChTemplate, PrmTemplate, FpyVariable)):
            # has a value but won't try to calc at compile time
            state.expr_converted_values[node] = None
            return
        elif isinstance(ref, FppType):
            expr_value = ref
        elif isinstance(ref, FieldReference):
            parent_value = state.expr_converted_values[node.parent]
            if parent_value is None:
                # no compile time constant value for our parent here
                state.expr_converted_values[node] = None
                return

            # we are accessing an attribute of something with an fprime value at compile time
            # we must be getting a member
            if isinstance(parent_value, StructType):
                expr_value = parent_value._val[node.attr]
            elif isinstance(parent_value, TimeType):
                if node.attr == "seconds":
                    expr_value = U32Type(parent_value.seconds)
                elif node.attr == "useconds":
                    expr_value = U32Type(parent_value.useconds)
                elif node.attr == "time_base":
                    expr_value = U16Type(parent_value.timeBase)
                elif node.attr == "time_context":
                    expr_value = U8Type(parent_value.timeContext)
                else:
                    assert False, node.attr
            else:
                assert False, parent_value

        assert expr_value is not None

        assert isinstance(expr_value, unconverted_type), (expr_value, unconverted_type)

        if converted_type != unconverted_type:
            expr_value = self.const_coerce_type(expr_value, converted_type, node, state)
            if expr_value is None:
                return
        state.expr_converted_values[node] = expr_value

    def visit_AstGetItem(self, node: AstGetItem, state: CompileState):
        ref = state.resolved_references[node]
        # get item can only be a field reference
        assert isinstance(ref, FieldReference), ref

        parent_value = state.expr_converted_values[node.parent]

        if parent_value is None:
            # no compile time constant value for our parent here
            state.expr_converted_values[node] = None
            return

        assert isinstance(parent_value, ArrayType), parent_value

        idx = state.expr_converted_values.get(node.item)
        if idx is None:
            # no compile time constant value for our index
            state.expr_converted_values[node] = None
            return

        assert isinstance(idx, U64Type)

        expr_value = parent_value._val[idx._val]

        uncoerced_type = state.expr_unconverted_types[node]
        assert isinstance(expr_value, uncoerced_type), (expr_value, uncoerced_type)

        coerced_type = state.expr_converted_types[node]
        if coerced_type != uncoerced_type:
            expr_value = self.const_coerce_type(expr_value, coerced_type, node, state)
            if expr_value is None:
                return
        state.expr_converted_values[node] = expr_value

    def visit_AstVar(self, node: AstVar, state: CompileState):
        unconverted_type = state.expr_unconverted_types[node]
        converted_type = state.expr_converted_types[node]
        ref = state.resolved_references[node]
        expr_value = None
        if isinstance(ref, (type, dict, FpyCallable)):
            # these types have no value
            state.expr_converted_values[node] = NothingType()
            assert unconverted_type == converted_type, (
                unconverted_type,
                converted_type,
            )
            return
        elif isinstance(ref, (ChTemplate, PrmTemplate, FpyVariable)):
            # has a value but won't try to calc at compile time
            state.expr_converted_values[node] = None
            return
        elif isinstance(ref, FppType):
            expr_value = ref
        elif isinstance(ref, FieldReference):
            assert False, ref

        assert expr_value is not None

        assert isinstance(expr_value, unconverted_type), (expr_value, unconverted_type)

        if converted_type != unconverted_type:
            expr_value = self.const_coerce_type(expr_value, converted_type, node, state)
            if expr_value is None:
                return
        state.expr_converted_values[node] = expr_value

    def visit_AstFuncCall(self, node: AstFuncCall, state: CompileState):
        func = state.resolved_references[node.func]
        assert isinstance(func, FpyCallable)
        # gather arg values
        arg_values = [
            state.expr_converted_values[e]
            for e in (node.args if node.args is not None else [])
        ]
        unknown_value = any(v for v in arg_values if v is None)
        if unknown_value:
            # we will have to calculate this at runtime
            state.expr_converted_values[node] = None
            return

        expr_value = None

        if isinstance(func, FpyTypeCtor):
            # actually construct the type
            if issubclass(func.type, StructType):
                instance = func.type()
                # pass in args as a dict
                # t[0] is the arg name
                arg_dict = {t[0]: v for t, v in zip(func.type.MEMBER_LIST, arg_values)}
                instance._val = arg_dict
                expr_value = instance

            elif issubclass(func.type, ArrayType):
                instance = func.type()
                instance._val = arg_values
                expr_value = instance

            elif func.type == TimeType:
                expr_value = TimeType(*[val.val for val in arg_values])

            else:
                # no other FppTypeClasses have ctors
                assert False, func.return_type
        else:
            # don't try to calculate the value of this function call
            # it's something like a cmd or macro
            state.expr_converted_values[node] = None
            return

        uncoerced_type = state.expr_unconverted_types[node]
        assert isinstance(expr_value, uncoerced_type), (expr_value, uncoerced_type)

        coerced_type = state.expr_converted_types[node]
        if coerced_type != uncoerced_type:
            expr_value = self.const_coerce_type(expr_value, coerced_type, node, state)
            if expr_value is None:
                return

        state.expr_converted_values[node] = expr_value

    def visit_AstOp(self, node: AstOp, state: CompileState):
        # we do not calculate compile time value of operators at the moment
        state.expr_converted_values[node] = None

    def visit_default(self, node, state):
        # coding error, missed an expr
        assert not is_instance_compat(node, AstExpr), node


class GenerateConstExprDirectives(Visitor):
    """for each expr with a constant compile time value, generate
    directives for how to put it in its register"""

    def visit_AstExpr(self, node: AstExpr, state: CompileState):
        if node in state.directives:
            # already have directives associated with this node
            return

        expr_value = state.expr_converted_values[node]

        if expr_value is None:
            # no const value
            return

        expr_type = state.expr_converted_types[node]

        assert isinstance(expr_value, expr_type), (
            expr_value,
            type(expr_value),
            expr_type,
        )

        if isinstance(expr_value, NothingType):
            # nothing type has no value
            state.directives[node] = []
            return

        if isinstance(expr_value, (InternalIntType, InternalStringType)):
            state.err("Expression is invalid when used here", node)
            return

        # it has a constant value at compile time
        serialized_expr_value = expr_value.serialize()

        # push it to the stack
        state.directives[node] = [PushValDirective(serialized_expr_value)]


class GenerateExprMacrosAndCmds(Visitor):
    """for each expr whose value is not known at compile time, but can be calculated at run time,
    generate directives to calculate the value and put it in its register. for each command
    or macro, generate directives for calling them with appropriate arg values"""

    def visit_AstGetItem(self, node: AstGetItem, state: CompileState):
        if node in state.directives:
            # already know how to put it on stack, or it is impossible
            return
        ref = state.resolved_references[node]

        assert isinstance(ref, FieldReference), ref

        # use the unconverted for this expr for now, because we haven't run conversion
        unconverted_type = state.expr_unconverted_types[node]
        # however, for parent, use converted because conversion has been run
        parent_type = state.expr_converted_types[node.parent]

        assert issubclass(parent_type, ArrayType)
        assert unconverted_type == parent_type.MEMBER_TYPE, (
            parent_type.MEMBER_TYPE,
            unconverted_type,
        )
        parent_dirs = state.directives[node.parent]
        # these are the dirs to put the parent on the stack
        # we want to put it on the stack and then grab a certain
        # size at a certain offset

        # optimization: leave it in the lvar array

        directives = parent_dirs.copy()

        # push the index (must be U64) to the stack
        index_dirs = state.directives[node.item]
        directives.extend(index_dirs)
        # okay now let's do an array oob check
        directives.append(
            DuplicateDirective(ArrayIndexType.getMaxSize())
        )  # duplicate the index
        # convert idx to u64
        directives.extend(convert_numeric_type(ArrayIndexType, U64Type))
        directives.append(
            PushValDirective(ArrayIndexType(parent_type.LENGTH))
        )  # push the length
        # convert len to u64
        directives.extend(convert_numeric_type(ArrayIndexType, U64Type))
        # check if idx < length
        directives.append(UnsignedLessThanDirective())
        # assert it's true
        # push the assert error code we should fail with if false
        directives.append(
            PushValDirective(
                U8Type(DirectiveErrorCode.ARRAY_OUT_OF_BOUNDS.value).serialize()
            )
        )
        directives.append(AssertDirective())
        # okay we're good. should still have the idx on the stack

        # multiply the index by the member type size
        directives.append(
            PushValDirective(U64Type(parent_type.MEMBER_TYPE.getMaxSize()))
        )
        directives.append(IntMultiplyDirective())

        # okay now we have the offset on the stack

        # get the member from the stack at this offset, discard the rest of
        # the parent
        directives.append(
            GetMemberDirective(
                parent_type.getMaxSize(), parent_type.MEMBER_TYPE.getMaxSize()
            )
        )

        # now convert the type if necessary
        converted_type = state.expr_converted_types[node]
        if unconverted_type != converted_type:
            directives.extend(convert_numeric_type(unconverted_type, converted_type))

        state.directives[node] = directives

    def visit_AstVar(self, node: AstVar, state: CompileState):
        if node in state.directives:
            # already know how to put it on stack, or it is impossible
            return

        ref = state.resolved_references.get(node)

        assert isinstance(ref, FpyVariable), ref

        # already should be in an lvar
        directives = [LoadDirective(ref.lvar_offset, ref.type.getMaxSize())]

        unconverted_type = state.expr_unconverted_types[node]
        converted_type = state.expr_converted_types[node]
        if unconverted_type != converted_type:
            directives.extend(convert_numeric_type(unconverted_type, converted_type))

        state.directives[node] = directives

    def visit_AstGetAttr(self, node: AstGetAttr, state: CompileState):
        if node in state.directives:
            # already know how to put it on stack, or it is impossible
            return

        ref = state.resolved_references.get(node)

        if isinstance(ref, dict):
            # don't generate code for it, it's a ref to a scope and
            # doesn't have a value
            state.directives[node] = []
            return

        # start with the unconverted type, because we haven't applied runtime type conversion yet
        unconverted_type = state.expr_unconverted_types[node]

        directives = []

        if isinstance(ref, ChTemplate):
            directives.append(PushTlmValDirective(ref.get_id()))
        elif isinstance(ref, PrmTemplate):
            directives.append(PushPrmDirective(ref.get_id()))
        elif isinstance(ref, FpyVariable):
            # already should be in an lvar
            directives.append(LoadDirective(ref.lvar_offset, ref.type.getMaxSize()))
        elif isinstance(ref, FieldReference):
            # okay, put parent dirs in first
            parent_dirs = state.directives[ref.parent_expr]
            # use the converted type of parent
            parent_type = state.expr_converted_types[ref.parent_expr]
            directives.extend(parent_dirs)
            assert ref.local_offset is not None
            # push the offset to the stack
            directives.append(PushValDirective(U64Type(ref.local_offset).serialize()))
            directives.append(
                GetMemberDirective(
                    parent_type.getMaxSize(), unconverted_type.getMaxSize()
                )
            )
        else:
            assert (
                False
            ), ref  # ref should either be impossible to put on stack or should have a compile time val

        converted_type = state.expr_converted_types[node]
        if converted_type != unconverted_type:
            directives.extend(convert_numeric_type(unconverted_type, converted_type))

        state.directives[node] = directives

    def visit_AstBinaryOp(self, node: AstBinaryOp, state: CompileState):
        if node in state.directives:
            # already know how to put it on stack
            return

        directives = []

        lhs_dirs = state.directives[node.lhs]
        rhs_dirs = state.directives[node.rhs]

        # which variant of the op did we pick?
        dir = state.stack_op_directives[node]

        # generate the actual op itself
        directives: list[Directive] = lhs_dirs + rhs_dirs
        if dir == MemCompareDirective:
            lhs_type = state.expr_converted_types[node.lhs]
            rhs_type = state.expr_converted_types[node.rhs]
            assert lhs_type == rhs_type, (lhs_type, rhs_type)
            directives.append(dir(lhs_type.getMaxSize()))
            if node.op == BinaryStackOp.NOT_EQUAL:
                directives.append(NotDirective())
        elif dir == NoOpDirective:
            # don't include no op
            pass
        else:
            directives.append(dir())

        # and convert the result of the op into the desired result of this expr
        unconverted_type = state.expr_unconverted_types[node]
        converted_type = state.expr_converted_types[node]
        if unconverted_type != converted_type:
            directives.extend(convert_numeric_type(unconverted_type, converted_type))

        state.directives[node] = directives

    def visit_AstUnaryOp(self, node: AstUnaryOp, state: CompileState):
        if node in state.directives:
            # already know how to put it on stack
            return

        directives = []

        val_dirs = state.directives[node.val]

        # which variant of the op did we pick?
        dir = state.stack_op_directives[node]
        # generate the actual op itself
        directives: list[Directive] = val_dirs

        if node.op == UnaryStackOp.NEGATE:
            # in this case, we also need to push -1
            if dir == FloatMultiplyDirective:
                directives.append(PushValDirective(F64Type(-1).serialize()))
            elif dir == IntMultiplyDirective:
                directives.append(PushValDirective(I64Type(-1).serialize()))

        directives.append(dir())
        # and convert the result of the op into the desired result of this expr
        unconverted_type = state.expr_unconverted_types[node]
        converted_type = state.expr_converted_types[node]
        if unconverted_type != converted_type:
            directives.extend(convert_numeric_type(unconverted_type, converted_type))

        state.directives[node] = directives

    def visit_AstFuncCall(self, node: AstFuncCall, state: CompileState):
        if node in state.directives:
            # already know how to put it on stack
            return

        node_args = node.args if node.args is not None else []
        func = state.resolved_references[node.func]
        directives = []
        if isinstance(func, FpyCmd):
            const_args = not any(
                state.expr_converted_values[arg_node] is None for arg_node in node_args
            )
            if const_args:
                # can just hardcode this cmd
                arg_bytes = bytes()
                for arg_node in node_args:
                    arg_value = state.expr_converted_values[arg_node]
                    arg_bytes += arg_value.serialize()
                directives.append(ConstCmdDirective(func.cmd.get_op_code(), arg_bytes))
            else:
                arg_byte_count = 0
                # push all args to the stack
                # keep track of how many bytes total we have pushed
                for arg_node in node_args:
                    node_dirs = state.directives[arg_node]
                    assert len(node_dirs) >= 1
                    directives.extend(node_dirs)
                    arg_converted_type = state.expr_converted_types[arg_node]
                    arg_byte_count += arg_converted_type.getMaxSize()
                # then push cmd opcode to stack as u32
                directives.append(
                    PushValDirective(U32Type(func.cmd.get_op_code()).serialize())
                )
                # now that all args are pushed to the stack, pop them and opcode off the stack
                # as a command
                directives.append(StackCmdDirective(arg_byte_count))
        elif isinstance(func, FpyMacro):
            # put all arg values on stack
            for arg_node in node_args:
                node_dirs = state.directives[arg_node]
                assert len(node_dirs) >= 1
                directives.extend(node_dirs)

            directives.append(func.dir())
        else:
            assert False, (node, func)

        # perform type conversion if called for
        unconverted_type = state.expr_unconverted_types[node]
        converted_type = state.expr_converted_types[node]
        if unconverted_type != converted_type:
            directives.extend(convert_numeric_type(unconverted_type, converted_type))
        state.directives[node] = directives

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        if node in state.directives:
            # already know how to do this assign
            return

        lhs = state.resolved_references[node.lhs]
        lvar_offset_dirs = []
        if isinstance(lhs, FpyVariable):
            state.directives[node] = state.directives[node.rhs] + [
                StoreConstOffsetDirective(lhs.lvar_offset, lhs.type.getMaxSize())
            ]
            return
        else:
            assert isinstance(lhs, FieldReference), lhs
            assert isinstance(lhs.base_ref, FpyVariable), lhs.base_ref

            # okay, are we assigning to a member or an element?

            if lhs.is_struct_member:
                # the offset in the base type, plus the offset of the base lvar
                # in the lvar array
                lvar_offset = lhs.base_offset + lhs.base_ref.lvar_offset
                lvar_offset_dirs.append(
                    PushValDirective(U32Type(lvar_offset).serialize())
                )
            else:
                assert lhs.is_array_element
                # again, offset is the offset in base type + offset of base lvar

                # however, because array idx can be variable, we don't know at compile time
                # the offset in base type. let's push the offset of base lvar first, then
                # calculate the offset in base type, then add

                # push as u64 because we're going to do math
                lvar_offset_dirs.append(
                    PushValDirective(U64Type(lhs.base_ref.lvar_offset).serialize())
                )

                # okay, so we have an index which might be variable
                lhs_parent_type = state.expr_converted_types[lhs.parent_expr]
                assert issubclass(lhs_parent_type, ArrayType), (
                    lhs_parent_type,
                    type(lhs_parent_type),
                )

                # push the index to the stack, do a bounds check,
                index_dirs = state.directives[lhs.idx_expr]
                lvar_offset_dirs.extend(index_dirs)
                # okay now let's do an array oob check
                lvar_offset_dirs.append(
                    DuplicateDirective(ArrayIndexType.getMaxSize())
                )  # duplicate the index
                # convert idx to u64
                lvar_offset_dirs.extend(convert_numeric_type(ArrayIndexType, U64Type))
                lvar_offset_dirs.append(
                    PushValDirective(ArrayIndexType(lhs_parent_type.LENGTH).serialize())
                )  # push the length
                # convert len to u64
                lvar_offset_dirs.extend(convert_numeric_type(ArrayIndexType, U64Type))
                # check if idx < length
                lvar_offset_dirs.append(UnsignedLessThanDirective())
                # assert it's true
                # push the assert error code we should fail with if false
                lvar_offset_dirs.append(
                    PushValDirective(
                        U8Type(DirectiveErrorCode.ARRAY_OUT_OF_BOUNDS.value).serialize()
                    )
                )
                lvar_offset_dirs.append(AssertDirective())
                # okay we're good. should still have the idx on the stack

                # multiply the index by the member type size
                lvar_offset_dirs.append(
                    PushValDirective(U64Type(lhs_parent_type.MEMBER_TYPE.getMaxSize()))
                )
                lvar_offset_dirs.append(IntMultiplyDirective())
                # okay, now we should have the offset wrt base of the parent type on the stack
                # right below it is the offset in the lvar array
                # add them
                lvar_offset_dirs.append(IntAddDirective())

                # and now convert the u64 back into the U32 that store expects
                lvar_offset_dirs.append(IntegerTruncate64To32Directive())

        # use the converted type, the node value has already had
        # conversion handled, so its stack value is converted
        converted_type = state.expr_converted_types[node.rhs]

        # start with the rhs on the stack
        directives = state.directives[node.rhs]
        # push the lvar offset
        directives.extend(lvar_offset_dirs)
        # then store in lvar array
        directives.append(StoreDirective(converted_type.getMaxSize()))

        state.directives[node] = directives

    def visit_AstAssert(self, node: AstAssert, state: CompileState):
        directives = state.directives[node.condition]
        # push the error code we should use if false, if one was given
        if node.exit_code is not None:
            directives.extend(state.directives[node.exit_code])
        else:
            # otherwise just use the default "ASSERTION_FAILURE error code"
            directives.append(
                PushValDirective(
                    U8Type(DirectiveErrorCode.ASSERTION_FAILURE.value).serialize()
                )
            )
        directives.append(AssertDirective())

        state.directives[node] = directives


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

    def visit_AstFor(self, node: AstFor, state: CompileState):
        count = 0
        # include upper bound push
        count += state.node_dir_counts[node.upper_bound]
        # include push val and store ub
        count += 2

        # include lb push
        count += state.node_dir_counts[node.lower_bound]
        # include push val and store lb
        count += 2
        # include end of loop check: load lv, load ub, cmp, if
        count += 4
        # include body
        count += state.node_dir_counts[node.body]
        # include increment lv: load lv, push 1, add, push lvar offset, store
        count += 5
        # include goto loop check
        count += 1

        state.node_dir_counts[node] = count

    def visit_AstBody(self, node: Union[AstBody, AstScopedBody], state: CompileState):
        count = 0
        if (
            isinstance(node, AstScopedBody)
            and state.scope_parents[state.local_scopes[node]] is None
        ):
            # only for the first scoped body:
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

    def visit_AstBody(self, node: Union[AstBody, AstScopedBody], state: CompileState):
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

    def visit_AstFor(self, node: AstFor, state: CompileState):
        start_line_idx = state.start_line_idx[node]
        # okay, start by calcing upper bound and storing it in upper bound var

        # push upper bound to stack
        dirs = state.directives[node.upper_bound]
        # now store in lvar
        upper_bound_var = state.for_loop_upper_bound_variables[node]
        assert state.expr_converted_types[node.upper_bound] == upper_bound_var.type
        # TODO figure out if we need conversions here
        # push lvar offset to stack
        dirs.append(PushValDirective(U32Type(upper_bound_var.lvar_offset).serialize()))
        # store in upper bound var
        dirs.append(
            StoreConstOffsetDirective(
                upper_bound_var.lvar_offset, upper_bound_var.type.getMaxSize()
            )
        )

        # set loop var to lower bound
        # push lower bound to stack
        dirs.extend(state.directives[node.lower_bound])
        # now store in lvar
        loop_var = state.for_loop_variables[node]
        assert state.expr_converted_types[node.lower_bound] == loop_var.type
        # store in loop var
        dirs.append(
            StoreConstOffsetDirective(loop_var.lvar_offset, loop_var.type.getMaxSize())
        )

        # okay, loop and UB vars have the right initial value

        # TODO should we store the loop vars as 64 bit? or should we do the conversion every time
        # for now going to assume they are stored as 64 bit

        end_of_loop_check_start_idx = start_line_idx + len(dirs)

        # now add the "end-of-loop" check
        # get the loop variable on the stack
        dirs.append(LoadDirective(loop_var.lvar_offset, loop_var.type.getMaxSize()))
        # get the UB on the stack
        dirs.append(
            LoadDirective(
                upper_bound_var.lvar_offset, upper_bound_var.type.getMaxSize()
            )
        )
        # check lhs < rhs else goto end
        # use a directive determined above
        cmp_dir = state.for_loop_comparison_directives[node]
        dirs.append(cmp_dir())

        if_dir = IfDirective(-1)
        dirs.append(if_dir)
        # okay now include body
        dirs.extend(state.directives[node.body])
        # okay increment loop var
        # push loop var to stack
        dirs.append(LoadDirective(loop_var.lvar_offset, loop_var.type.getMaxSize()))
        # push 1 to stack
        dirs.append(PushValDirective(U64Type(1).serialize()))
        # add them
        dirs.append(IntAddDirective())
        # store in lvar array
        dirs.append(
            StoreConstOffsetDirective(loop_var.lvar_offset, loop_var.type.getMaxSize())
        )
        # okay, done with this iteration of the loop. go back up to the end-of-loop check
        dirs.append(GotoDirective(end_of_loop_check_start_idx))

        # and now update the if directive to go to just past the end of the body
        if_dir.false_goto_dir_index = start_line_idx + len(dirs)

        # okay! all done

        state.directives[node] = dirs

    def visit_AstBody(self, node: Union[AstBody, AstScopedBody], state: CompileState):
        dirs = []
        if (
            isinstance(node, AstScopedBody)
            and state.scope_parents[state.local_scopes[node]] is None
        ):
            # only for the first scoped body
            dirs.append(AllocateDirective(state.lvar_array_size_bytes))
        for stmt in node.stmts:
            stmt_dirs = state.directives.get(stmt)
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
    event_json_dict_loader = EventJsonLoader(dictionary)
    (event_id_dict, event_name_dict, versions) = event_json_dict_loader.construct_dicts(
        dictionary
    )
    # the type name dict is a mapping of a fully qualified name to an fprime type
    # here we put into it all types found while parsing all cmds, params and tlm channels
    type_name_dict: dict[str, FppTypeClass] = cmd_json_dict_loader.parsed_types
    type_name_dict.update(ch_json_dict_loader.parsed_types)
    type_name_dict.update(prm_json_dict_loader.parsed_types)
    type_name_dict.update(event_json_dict_loader.parsed_types)

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
    for typ in SPECIFIC_NUMERIC_TYPES:
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
        if issubclass(typ, StructType):
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


def compile(body: AstScopedBody, dictionary: str) -> list[Directive] | CompileError:
    state = get_base_compile_state(dictionary)
    passes: list[Visitor] = [
        AssignIds(),
        AssignLocalScopes(),
        # based on assignment syntax nodes, we know which variables exist where
        CreateVariables(),
        CheckUseBeforeDeclare(),
        # now that variables have been defined, all names/attributes/indices (references)
        # should be defined
        ResolveVars(),
        # now that we know what all refs point to, we should be able to figure out the type
        # of every expression
        PickTypesAndResolveAttrsAndItems(),
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
        if len(state.errors) != 0:
            return state.errors[0]

    dirs = state.directives[body]
    if len(dirs) > MAX_DIRECTIVES_COUNT:
        err = CompileError(
            f"Too many directives in sequence (expected less than {MAX_DIRECTIVES_COUNT}, had {len(dirs)})"
        )
        return err

    # TODO check lvar array not > max stack size (AND TEST THIS!)

    return dirs
