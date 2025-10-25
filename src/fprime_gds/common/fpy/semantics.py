from __future__ import annotations
from numbers import Number
from typing import Union

from fprime_gds.common.fpy.types import (
    SIGNED_INTEGER_TYPES,
    SPECIFIC_NUMERIC_TYPES,
    UNSIGNED_INTEGER_TYPES,
    ArrayIndexType,
    CompileState,
    FieldReference,
    ForLoopAnalysis,
    FppType,
    FpyCallable,
    FpyCast,
    FpyScope,
    FpyTypeCtor,
    FpyVariable,
    InternalFloatType,
    InternalIntType,
    InternalStringType,
    NothingValue,
    TopDownVisitor,
    Visitor,
    get_ref_fpp_type_class,
    is_instance_compat,
    resolve_var,
)

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
    BinaryStackOp,
    MemCompareDirective,
    UnaryStackOp,
)
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.prm_template import PrmTemplate
from fprime.common.models.serialize.time_type import TimeType
from fprime.common.models.serialize.type_base import ValueType
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
    F64Type,
    FloatType,
    IntegerType,
    NumericalType,
)
from fprime.common.models.serialize.string_type import StringType
from fprime.common.models.serialize.bool_type import BoolType
from fprime_gds.common.fpy.syntax import (
    AstAssert,
    AstBinaryOp,
    AstBoolean,
    AstBreak,
    AstContinue,
    AstElif,
    AstExpr,
    AstFor,
    AstGetAttr,
    AstGetItem,
    AstNumber,
    AstReference,
    AstScopedBody,
    AstStmtWithExpr,
    AstString,
    Ast,
    AstScopedBody,
    AstLiteral,
    AstIf,
    AstAssign,
    AstFuncCall,
    AstUnaryOp,
    AstVar,
    AstWhile,
)
from fprime.common.models.serialize.type_base import BaseType as FppValue


class AssignIds(TopDownVisitor):
    """assigns a unique id to each node to allow it to be indexed in a dict"""

    def visit_default(self, node, state: CompileState):
        node.id = state.next_node_id
        state.next_node_id += 1


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
            if node.type_ann is not None:
                # new variable declaration
                # make sure it isn't defined in this scope
                existing_local = state.local_scopes[node].get(node.lhs.var)
                if existing_local is not None:
                    # redeclaring an existing variable
                    state.err(f"'{node.lhs.var}' has already been declared", node)
                    return
                # okay, declare the var
                var = FpyVariable(node.lhs.var, node.type_ann, node)
                # new var. put it in the table under this scope
                state.local_scopes[node][node.lhs.var] = var
            else:
                # otherwise, it's a reference to an existing var
                resolved = resolve_var(node, node.lhs.var, state)
                if resolved is None:
                    # unable to find this symbol
                    state.err(
                        f"'{node.lhs.var}' has not been declared",
                        node.lhs,
                    )
                    return
                # okay, we were able to resolve it

        else:
            # assigning to a member or array element. don't need to make a new variable,
            # space already exists
            if node.type_ann is not None:
                # type annotation on a field assignment... it already has a type!
                state.err("Cannot specify a type annotation for a field", node.type_ann)
                return

    def visit_AstFor(self, node: AstFor, state: CompileState):
        # for loops have an implicit loop variable that they declare
        existing = state.local_scopes[node].get(node.loop_var.var)

        if existing:
            state.err(f"'{node.loop_var.var}' has already been declared", node)
            return

        var = FpyVariable(node.loop_var.var, node.loop_var_type, node)
        # new var. put it in the table under this scope
        state.local_scopes[node][node.loop_var.var] = var
        analysis = ForLoopAnalysis(var)
        state.for_loops[node] = analysis


class SetEnclosingLoops(Visitor):
    def __init__(self, loop: Union[AstFor, AstWhile]):
        self.loop = loop

    def visit_AstBreak_AstContinue(
        self, node: Union[AstBreak, AstContinue], state: CompileState
    ):
        state.enclosing_loops[node] = self.loop


class CheckBreakAndContinueInLoop(TopDownVisitor):
    def visit_AstFor_AstWhile(self, node: Union[AstFor, AstWhile], state: CompileState):
        SetEnclosingLoops(node).run(node.body, state)

    def visit_AstBreak_AstContinue(
        self, node: Union[AstBreak, AstContinue], state: CompileState
    ):
        if node not in state.enclosing_loops:
            state.err("Not inside of a loop", node)
            return


class ResolveVarsAndTypes(TopDownVisitor):

    def resolve_type_reference(self, node: Ast, state: CompileState) -> bool:

        # we have some special logic for types because we want them resolved early,
        # and they are easy to resolve

        def resolve(n: Ast):

            if not isinstance(n, (AstVar, AstGetAttr)):
                state.err("Unknown type", node)
                return None

            if isinstance(n, AstVar):
                parent_scope = state.types
                name = n.var
            else:
                parent_scope = resolve(n.parent)
                name = n.attr

            if parent_scope is None:
                # error already raised
                return None

            assert isinstance(parent_scope, dict), parent_scope

            node_type = parent_scope.get(name)
            if node_type is None:
                state.err("Unknown type", node)
                return None

            state.resolved_references[n] = node_type
            return node_type

        ret_type = resolve(node)
        return ret_type is not None

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
            node.func, state.callables, "function", state
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
            # in this pass, we also go ahead and finish up the types because they're easy
            if not self.resolve_type_reference(node.type_ann, state):
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
        # in this pass, we also go ahead and finish up the types because they're easy
        if not self.resolve_type_reference(node.loop_var_type, state):
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
        # usually this would just mean it's on its own on a line
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


class CheckUseBeforeDeclare(Visitor):

    def __init__(self):
        self.currently_declared_vars: list[FpyVariable] = []

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        if not isinstance(node.lhs, AstVar):
            # definitely not a declaration, it's a field assignment
            return

        var = state.resolved_references[node.lhs]

        if var is None or var.declaration != node:
            # either not declared in this scope, or this is not a
            # declaration of this var
            return

        # this node declares this variable

        self.currently_declared_vars.append(var)

    def visit_AstVar(self, node: AstVar, state: CompileState):
        ref = state.resolved_references[node]
        if not isinstance(ref, FpyVariable):
            # not a variable, might be a type name or smth
            return

        if isinstance(ref.declaration, AstFor):
            # this will be handled  by other pass
            return
        if isinstance(ref.declaration, AstAssign) and ref.declaration.lhs == node:
            # this is the initial name of the variable. don't crash
            return

        if ref not in self.currently_declared_vars:
            state.err(f"'{node.var}' used before declared", node)
            return


class CheckVariableNotReferenced(Visitor):
    def __init__(self, var: FpyVariable):
        self.var = var

    def visit_AstVar(self, node: AstVar, state: CompileState):
        ref = state.resolved_references[node]
        if ref == self.var:
            state.err(f"'{node.var}' used before declared", node)
            return


class CheckUseBeforeDeclareForLoopVariables(TopDownVisitor):

    def __init__(self):
        self.currently_declared_vars: list[FpyVariable] = []

    def visit_AstFor(self, node: AstFor, state: CompileState):
        var = state.resolved_references[node.loop_var]

        self.currently_declared_vars.append(var)
        # also double check that the vars aren't referenced in the ub and lb
        CheckVariableNotReferenced(var).run(node.lower_bound, state)
        CheckVariableNotReferenced(var).run(node.upper_bound, state)

    def visit_AstVar(self, node: AstVar, state: CompileState):
        ref = state.resolved_references[node]
        if not isinstance(ref, FpyVariable):
            # not a variable, might be a type name or smth
            return

        if isinstance(ref.declaration, AstAssign):
            # handled by prev pass
            return
        if isinstance(ref.declaration, AstFor) and ref.declaration.loop_var == node:
            # this is the initial name of the variable. don't crash
            return

        if ref not in self.currently_declared_vars:
            state.err(f"'{node.var}' used before declared", node)
            return


class PickTypesAndResolveAttrsAndItems(Visitor):

    def coerce_expr_type(
        self, node: AstExpr, type: FppType, state: CompileState
    ) -> bool:
        unconverted_type = state.expr_unconverted_types[node]
        # make sure it isn't already being coerced
        assert unconverted_type == state.expr_converted_types[node], (
            unconverted_type,
            state.expr_converted_types[node],
        )
        if self.can_coerce_type(unconverted_type, type):
            state.expr_converted_types[node] = type
            return True
        state.err(f"Expected {type.__name__}, found {unconverted_type.__name__}", node)
        return False

    def can_coerce_type(self, type: FppType, to_type: FppType) -> bool:
        if type == to_type:
            return True
        if type == InternalStringType and issubclass(to_type, StringType):
            # we can convert the internal String type to any string type
            return True
        if not issubclass(type, NumericalType) or not issubclass(to_type, NumericalType):
            # if one of the src or dest aren't numerical, we can't coerce
            return False
        # for numeric types
        # ints can only go to >= size ints, or floats
        # and floats can only go into >= size floats
        if issubclass(type, IntegerType):
            if issubclass(to_type, FloatType):
                # int to a float is allowed. yes this can cause
                # loss of precision for large integer values
                # TODO is this the right call?
                return True
            assert issubclass(to_type, IntegerType), to_type
            # if the from_type is internal int, then it has infinite precision
            # we'll allow interpreting this as any integer, regardless of dest bitwidth

            # i think this should be impossible rn
            assert to_type != InternalIntType
            return type == InternalIntType or type.get_bits() <= to_type.get_bits()
        if issubclass(type, FloatType):
            if not issubclass(to_type, FloatType):
                # definitely will fail, cannot coerce float into non float
                return False
            if type == InternalFloatType:
                # can convert the internal float type into any float type
                return True
            # otherwise we're going from a specific float type

            # i think this should be impossible rn
            assert to_type != InternalFloatType

            return type.get_bits() <= to_type.get_bits()
        return False

    def pick_intermediate_type(
        self, arg_types: list[FppType], op: BinaryStackOp | UnaryStackOp
    ) -> FppType:

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

        arbitrary_precision = all(
            t == InternalIntType or t == InternalFloatType for t in arg_types
        )
        float = any(issubclass(t, FloatType) for t in arg_types)

        if arbitrary_precision:
            # all arguments are arbitrary precision
            # the return value should be arbitrary precision
            if op == BinaryStackOp.DIVIDE or op == BinaryStackOp.EXPONENT:
                # always do true division over floats, python style
                return InternalFloatType
            if float:
                # at least one arg is a float
                return InternalFloatType
            # no args are floats
            return InternalIntType

        unsigned = any(t in UNSIGNED_INTEGER_TYPES for t in arg_types)

        if op == BinaryStackOp.DIVIDE or op == BinaryStackOp.EXPONENT:
            # always do true division over floats, python style
            return F64Type

        if float:
            # at least one arg is a float
            return F64Type

        if op == UnaryStackOp.NEGATE and unsigned:
            # negation of an unsigned integer always returns a signed int
            return I64Type

        if unsigned:
            # at least one arg is unsigned
            return U64Type

        return I64Type

    def is_type_constant_size(self, type: FppType) -> bool:
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
        self, node: Ast, parent_type: FppType, state: CompileState
    ) -> list[tuple[str, FppType]] | None:
        if not issubclass(parent_type, (StructType, TimeType)):
            return {}

        if not self.is_type_constant_size(parent_type):
            state.err(
                f"{parent_type} has dynamically-sized members, cannot access members",
                node,
            )
            return None

        member_list: list[tuple[str, FppType]] = None
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
            result_type = InternalFloatType
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

        result_type = None
        if node.op in NUMERIC_OPERATORS:
            result_type = intermediate_type
        else:
            result_type = BoolType

        state.op_intermediate_types[node] = intermediate_type
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

        result_type = None
        if node.op in NUMERIC_OPERATORS:
            result_type = intermediate_type
        else:
            result_type = BoolType

        state.op_intermediate_types[node] = intermediate_type
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
        if func is None:
            # if it were a reference to a callable, it would have already been resolved
            # if it were a ref to smth else, it would have already errored
            # so it's not even a ref
            state.err(f"Unknown function", node.func)
            return

        func_args = func.args
        node_args = node.args if node.args else []

        if len(node_args) < len(func_args):
            state.err(
                f"Missing arguments (expected {len(func_args)} found {len(node_args)})",
                node,
            )
            return
        if len(node_args) > len(func_args):
            state.err(
                f"Too many arguments (expected {len(func_args)} found {len(node_args)})",
                node,
            )
            return

        if isinstance(func, FpyCast):
            # casts do not follow coercion rules, because casting is the counterpart of coercion!
            # coercion is implicit, casting is explicit. if they say they want to cast, we let them
            node_arg = node_args[0]
            input_type = state.expr_unconverted_types[node_arg]
            output_type = func.to_type
            # right now we only have casting to numbers
            assert output_type in SPECIFIC_NUMERIC_TYPES
            if not issubclass(input_type, NumericalType):
                # cannot convert a non-numeric type to a numeric type
                state.err(f"Expected a number, found {input_type.__name__}", node_arg)
                return
            # we're going from input_type to output type, and we're going to ignore
            # the coercion rules
            state.expr_converted_types[node_arg] = output_type
            state.expr_explicit_casts.append(node_arg)
        else:
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
        # okay we have three types, but lb gets converted to lv, so we just have lv and ub
        # so we're going to be comparing lv to ub type, so find an intermediate

        loop_info = state.for_loops[node]
        loop_var = loop_info.loop_var
        loop_var_type = loop_var.type

        # handle the loop condition check
        # find intermediate type. we compare two variables of loop_var_type
        cmp_intermediate_type = self.pick_intermediate_type(
            [loop_var_type, loop_var_type], BinaryStackOp.LESS_THAN
        )

        if cmp_intermediate_type is None or issubclass(
            cmp_intermediate_type, FloatType
        ):
            state.err(
                f"Loop variable type must be a signed or unsigned integer type",
                node,
            )
            return

        loop_info.cmp_intermediate_type = cmp_intermediate_type
        assert cmp_intermediate_type is not None and not issubclass(
            cmp_intermediate_type, FloatType
        ), cmp_intermediate_type

        # upper and lower bounds must be coercible to loop variable type
        if not self.coerce_expr_type(node.lower_bound, loop_var_type, state):
            return
        if not self.coerce_expr_type(node.upper_bound, loop_var_type, state):
            return

        # handle increment loop var
        # this looks like:
        # loop_var = loop_var + 1
        inc_intermediate_type = self.pick_intermediate_type(
            [loop_var_type, loop_var_type], BinaryStackOp.ADD
        )
        loop_info.inc_intermediate_type = inc_intermediate_type

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

        loop_info = state.for_loops[node]

        # allocate space for the loop var
        loop_var = loop_info.loop_var
        assert isinstance(loop_var, FpyVariable)
        lvar_offset = state.lvar_array_size_bytes
        state.lvar_array_size_bytes += loop_var.type.getMaxSize()
        loop_var.lvar_offset = lvar_offset

        # allocate space for the upper bound var
        # type of ub var is same as loop var type
        lvar_offset = state.lvar_array_size_bytes
        upper_bound_var = FpyVariable(
            state.new_anonymous_variable_name(), None, node, loop_var.type, lvar_offset
        )
        state.lvar_array_size_bytes += upper_bound_var.type.getMaxSize()
        upper_bound_var.lvar_offset = lvar_offset
        # store ub var in a dict for later
        loop_info.upper_bound_var = upper_bound_var


class CalculateConstExprValues(Visitor):
    """for each expr, try to calculate its constant value and store it in a map. stores None if no value could be
    calculated at compile time, and NothingType if the expr had no value"""

    def const_convert_type(
        self,
        from_val: FppValue,
        to_type: FppType,
        node: Ast,
        state: CompileState,
        explicit_cast: bool = False,
    ) -> FppValue | None:
        try:
            if type(from_val) == to_type:
                return from_val
            if issubclass(to_type, StringType):
                assert type(from_val) == InternalStringType, type(from_val)
                return to_type(from_val.val)
            if issubclass(to_type, FloatType):
                assert issubclass(type(from_val), NumericalType), type(from_val)
                # based on inspection of the underlying FloatType classes,
                # floats do not need narrowing handling
                return to_type(float(from_val.val))
            if issubclass(to_type, IntegerType):
                assert issubclass(type(from_val), NumericalType), type(from_val)
                if not explicit_cast:
                    # if this was a coercion, we can actually perform one additional check
                    # before we convert it: does it fit within bounds?
                    assert isinstance(from_val, IntegerType), from_val
                    # this is an implicit cast, check that the value can fit in the dest type
                    dest_min, dest_max = to_type.range()
                    if from_val.val < dest_min or from_val.val > dest_max:
                        state.err(
                            f"{from_val.val} is out of range for type {to_type.__name__}",
                            node,
                        )
                        return None
                # handle narrowing, if necessary
                value = int(from_val.val)
                mask = (1 << to_type.get_bits()) - 1
                value &= mask
                if to_type in SIGNED_INTEGER_TYPES:
                    sign_bit = 1 << (to_type.get_bits() - 1)
                    if value & sign_bit:
                        # the sign bit is set, the result should be negative
                        # subtract the max value as this is how two's complement works
                        value -= 1 << to_type.get_bits()
                return to_type(value)
            assert False, (from_val, type(from_val), to_type)
        except TypeException as e:
            state.err(f"For type {type(from_val).__name__}: {e}", node)
            return None

    def visit_AstLiteral(self, node: AstLiteral, state: CompileState):
        unconverted_type = state.expr_unconverted_types[node]

        try:
            expr_value = unconverted_type(node.value)
        except TypeException as e:
            # TODO can this be reached any more? maybe for string types
            state.err(f"For type {unconverted_type.__name__}: {e}", node)
            return

        explicit_cast = node in state.expr_explicit_casts
        converted_type = state.expr_converted_types[node]
        if converted_type != unconverted_type:
            expr_value = self.const_convert_type(
                expr_value, converted_type, node, state, explicit_cast
            )
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
            state.expr_converted_values[node] = NothingValue()
            assert unconverted_type == converted_type, (
                unconverted_type,
                converted_type,
            )
            return
        elif isinstance(ref, (ChTemplate, PrmTemplate, FpyVariable)):
            # has a value but won't try to calc at compile time
            state.expr_converted_values[node] = None
            return
        elif isinstance(ref, FppValue):
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
            expr_value = self.const_convert_type(
                expr_value, converted_type, node, state
            )
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

        unconverted_type = state.expr_unconverted_types[node]
        assert isinstance(expr_value, unconverted_type), (expr_value, unconverted_type)

        converted_type = state.expr_converted_types[node]
        if converted_type != unconverted_type:
            expr_value = self.const_convert_type(
                expr_value, converted_type, node, state
            )
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
            state.expr_converted_values[node] = NothingValue()
            assert unconverted_type == converted_type, (
                unconverted_type,
                converted_type,
            )
            return
        elif isinstance(ref, (ChTemplate, PrmTemplate, FpyVariable)):
            # has a value but won't try to calc at compile time
            state.expr_converted_values[node] = None
            return
        elif isinstance(ref, FppValue):
            expr_value = ref
        elif isinstance(ref, FieldReference):
            assert False, ref

        assert expr_value is not None

        assert isinstance(expr_value, unconverted_type), (expr_value, unconverted_type)

        if converted_type != unconverted_type:
            expr_value = self.const_convert_type(
                expr_value, converted_type, node, state
            )
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
        unknown_value = any(v is None for v in arg_values)
        if unknown_value:
            # we will have to calculate this at runtime
            state.expr_converted_values[node] = None
            return

        expr_value = None

        # whether the conversion that will happen is due to an explicit cast
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
                # no other FppTypees have ctors
                assert False, func.return_type
        elif isinstance(func, FpyCast):
            # should only be one value. it should be of some numeric type
            # our const convert type func will convert it for us
            expr_value = arg_values[0]
        else:
            # don't try to calculate the value of this function call
            # it's something like a cmd or macro
            state.expr_converted_values[node] = None
            return

        unconverted_type = state.expr_unconverted_types[node]
        assert isinstance(expr_value, unconverted_type), (expr_value, unconverted_type)

        converted_type = state.expr_converted_types[node]
        if converted_type != unconverted_type:
            expr_value = self.const_convert_type(
                expr_value, converted_type, node, state
            )
            if expr_value is None:
                return

        state.expr_converted_values[node] = expr_value

    def visit_AstBinaryOp(self, node: AstBinaryOp, state: CompileState):
        # Check if both left-hand side (lhs) and right-hand side (rhs) are constants
        lhs_value: FppValue = state.expr_converted_values.get(node.lhs)
        rhs_value: FppValue = state.expr_converted_values.get(node.rhs)

        if lhs_value is None or rhs_value is None:
            state.expr_converted_values[node] = None
            return

        # Both sides are constants, evaluate the operation if the operator is supported

        if not isinstance(lhs_value, ValueType) or not isinstance(rhs_value, ValueType):
            # if one of them isn't a ValueType, assume it must be TimeType
            assert lhs_value == rhs_value and lhs_value == TimeType, (
                lhs_value,
                rhs_value,
            )
        else:
            # get the actual pythonic value from the fpp type
            lhs_value = lhs_value.val
            rhs_value = rhs_value.val

        folded_value = None
        # Arithmetic operations
        if node.op == BinaryStackOp.ADD:
            folded_value = lhs_value + rhs_value
        elif node.op == BinaryStackOp.SUBTRACT:
            folded_value = lhs_value - rhs_value
        elif node.op == BinaryStackOp.MULTIPLY:
            folded_value = lhs_value * rhs_value
        elif node.op == BinaryStackOp.DIVIDE:
            folded_value = lhs_value / rhs_value
        elif node.op == BinaryStackOp.EXPONENT:
            folded_value = lhs_value**rhs_value
        elif node.op == BinaryStackOp.FLOOR_DIVIDE:
            folded_value = lhs_value // rhs_value
        elif node.op == BinaryStackOp.MODULUS:
            folded_value = lhs_value % rhs_value
        # Boolean logic operations
        elif node.op == BinaryStackOp.AND:
            folded_value = lhs_value and rhs_value
        elif node.op == BinaryStackOp.OR:
            folded_value = lhs_value or rhs_value
        # Inequalities
        elif node.op == BinaryStackOp.GREATER_THAN:
            folded_value = lhs_value > rhs_value
        elif node.op == BinaryStackOp.GREATER_THAN_OR_EQUAL:
            folded_value = lhs_value >= rhs_value
        elif node.op == BinaryStackOp.LESS_THAN:
            folded_value = lhs_value < rhs_value
        elif node.op == BinaryStackOp.LESS_THAN_OR_EQUAL:
            folded_value = lhs_value <= rhs_value
        # Equality Checking
        elif node.op == BinaryStackOp.EQUAL:
            if not isinstance(lhs_value, Number):
                # comparing two complex types
                assert type(lhs_value) == type(rhs_value), (lhs_value, rhs_value)
                # for now we don't fold this
                folded_value = None
            else:
                folded_value = lhs_value == rhs_value
        elif node.op == BinaryStackOp.NOT_EQUAL:
            if not isinstance(lhs_value, Number):
                # comparing two complex types
                assert type(lhs_value) == type(rhs_value), (lhs_value, rhs_value)
                # for now we don't fold this
                folded_value = None
            else:
                folded_value = lhs_value != rhs_value
        else:
            # missing an operation
            assert False, node.op

        if folded_value is None:
            # give up, don't try to calculate the value of this expr at compile time
            state.expr_converted_values[node] = None
            return

        if type(folded_value) == int:
            folded_value = InternalIntType(folded_value)
        elif type(folded_value) == float:
            folded_value = InternalFloatType(folded_value)
        elif type(folded_value) == bool:
            folded_value = BoolType(folded_value)
        else:
            assert False, folded_value

        unconverted_type = state.expr_unconverted_types.get(node)
        converted_type = state.expr_converted_types.get(node)
        if converted_type != unconverted_type:
            folded_value = self.const_convert_type(
                folded_value, converted_type, node, state
            )
            if folded_value is None:
                return
        state.expr_converted_values[node] = folded_value

    def visit_AstUnaryOp(self, node: AstUnaryOp, state: CompileState):
        value: FppValue = state.expr_converted_values.get(node.val)

        if value is None:
            state.expr_converted_values[node] = None
            return

        # input is constant, evaluate the operation if the operator is supported
        assert isinstance(value, ValueType), value

        # get the actual pythonic value from the fpp type
        value = value.val
        folded_value = None

        if node.op == UnaryStackOp.NEGATE:
            folded_value = -value
        elif node.op == UnaryStackOp.IDENTITY:
            folded_value = value
        elif node.op == UnaryStackOp.NOT:
            folded_value = not value
        else:
            # missing an operation
            assert False, node.op

        assert folded_value is not None

        if type(folded_value) == int:
            folded_value = InternalIntType(folded_value)
        elif type(folded_value) == float:
            folded_value = InternalFloatType(folded_value)
        elif type(folded_value) == bool:
            folded_value = BoolType(folded_value)
        else:
            assert False, folded_value

        unconverted_type = state.expr_unconverted_types.get(node)
        converted_type = state.expr_converted_types.get(node)
        if converted_type != unconverted_type:
            folded_value = self.const_convert_type(
                folded_value, converted_type, node, state
            )
            if folded_value is None:
                return
        state.expr_converted_values[node] = folded_value

    def visit_default(self, node, state):
        # coding error, missed an expr
        assert not is_instance_compat(node, AstExpr), node


class CheckConstArrayAccesses(Visitor):
    def visit_AstGetItem(self, node: AstGetItem, state: CompileState):
        # if the index is a const, we should be able to check if it's in bounds
        idx_value = state.expr_converted_values.get(node.item)
        if idx_value is None:
            # can't check at compile time
            return

        parent_type = state.expr_converted_types[node.parent]
        assert issubclass(parent_type, ArrayType), parent_type

        if idx_value.val < 0 or idx_value.val >= parent_type.LENGTH:
            state.err(
                f"Index {idx_value.val} out of bounds for array type {parent_type.__name__} with length {parent_type.LENGTH}",
                node.item,
            )
            return
