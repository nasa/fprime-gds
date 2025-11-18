from __future__ import annotations
from decimal import Decimal
import decimal
from numbers import Number
import heapq
from typing import Union

from fprime_gds.common.fpy.error import CompileError
from fprime_gds.common.fpy.types import (
    ARBITRARY_PRECISION_TYPES,
    SIGNED_INTEGER_TYPES,
    SPECIFIC_NUMERIC_TYPES,
    UNSIGNED_INTEGER_TYPES,
    CompileState,
    FieldReference,
    ForLoopAnalysis,
    FppType,
    FpyCallable,
    FpyCast,
    FpyFloatValue,
    FpyReference,
    FpyScope,
    FpyTypeCtor,
    FpyVariable,
    FpyIntegerValue,
    FpyStringValue,
    LoopVarValue,
    NothingValue,
    RangeValue,
    TopDownVisitor,
    Visitor,
    is_instance_compat,
    resolve_var,
    typename,
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
    ArrayIndexType,
    BinaryStackOp,
    MemCompareDirective,
    UnaryStackOp,
)
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.prm_template import PrmTemplate
from fprime_gds.common.models.serialize.time_type import TimeType as TimeValue
from fprime_gds.common.models.serialize.type_base import ValueType
from fprime_gds.common.models.serialize.serializable_type import (
    SerializableType as StructValue,
)
from fprime_gds.common.models.serialize.array_type import ArrayType as ArrayValue
from fprime_gds.common.models.serialize.type_exceptions import TypeException
from fprime_gds.common.models.serialize.numerical_types import (
    U8Type as U8Value,
    U16Type as U16Value,
    U32Type as U32Value,
    U64Type as U64Value,
    I64Type as I64Value,
    F64Type as F64Value,
    FloatType as FloatValue,
    IntegerType as IntegerValue,
    NumericalType as NumericalValue,
)
from fprime_gds.common.models.serialize.string_type import StringType as StringValue
from fprime_gds.common.models.serialize.bool_type import BoolType as BoolValue
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
    AstRange,
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
from fprime_gds.common.models.serialize.type_base import BaseType as FppValue


class AssignIds(TopDownVisitor):
    """assigns a unique id to each node to allow it to be indexed in a dict"""

    def visit_default(self, node, state: CompileState):
        node.id = state.next_node_id
        state.next_node_id += 1


class SetLocalScope(Visitor):
    def __init__(self, scope: FpyScope):
        super().__init__()
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
        if not is_instance_compat(node.lhs, AstReference):
            state.err("Invalid assignment", node.lhs)
            return

        if not is_instance_compat(node.lhs, AstVar):
            # assigning to a member or array element. don't need to make a new variable,
            # space already exists
            if node.type_ann is not None:
                # type annotation on a field assignment... it already has a type!
                state.err("Cannot specify a type annotation for a field", node.type_ann)
                return
            # otherwise we good
            return

        if node.type_ann is not None:
            # new variable declaration
            # make sure it isn't defined in this scope
            # TODO shadowing check
            existing_local = state.local_scopes[node].get(node.lhs.var)
            if existing_local is not None:
                # redeclaring an existing variable
                state.err(f"'{node.lhs.var}' has already been declared", node)
                return
            # okay, declare the var
            var = FpyVariable(node.lhs.var, node.type_ann, node)
            # new var. put it in the table under this scope
            state.local_scopes[node][node.lhs.var] = var
            # also put it in the big list
            state.variables.append(var)
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

    def visit_AstFor(self, node: AstFor, state: CompileState):
        # for loops have an implicit loop variable that they can declare
        # if it isn't already declared in the local scope
        loop_var = state.local_scopes[node].get(node.loop_var.var)

        reuse_existing_loop_var = False
        if loop_var is not None:
            # this is okay as long as the variable is of the same type

            # what follows is a bit of a hack
            # there are two cases: either loop_var has been declared before but we only know the type expr (if it was an AstAssign decl)
            # or loop_var has been declared before and we only know the type, but have no type expr

            # case 1 is easy, just check the type == LoopVarType
            # case 2 is harder, we have to check if the type expr is an AstVar (assuming that LoopVarType is expressible thru an AstVar)
            # and that the var name is the canonical name of the LoopVarType

            # the alternative to this is that we do some primitive type resolution in the same pass as variable creation
            # i'm doing this hack because we're going to switch to type inference for variables later and that will make this go away

            if (loop_var.type_ref is None and loop_var.type != LoopVarValue) or (
                loop_var.type is None
                and not (
                    isinstance(loop_var.type_ref, AstVar)
                    and loop_var.type_ref.var == LoopVarValue.get_canonical_name()
                )
            ):
                state.err(
                    f"'{node.loop_var.var}' has already been declared as a type other than {typename(LoopVarValue)}",
                    node,
                )
                return
            reuse_existing_loop_var = True
        else:
            # new var. put it in the table under this scope
            loop_var = FpyVariable(node.loop_var.var, None, node, LoopVarValue)
            state.local_scopes[node][node.loop_var.var] = loop_var
            state.variables.append(loop_var)

        # each loop also declares an implicit ub variable
        # type of ub var is same as loop var type
        upper_bound_var = FpyVariable(
            state.new_anonymous_variable_name(), None, node, LoopVarValue
        )
        state.variables.append(upper_bound_var)
        analysis = ForLoopAnalysis(loop_var, upper_bound_var, reuse_existing_loop_var)
        state.for_loops[node] = analysis


class SetEnclosingLoops(Visitor):
    def __init__(self, loop: Union[AstFor, AstWhile]):
        super().__init__()
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


class ResolveVarsTypesAndFuncs(TopDownVisitor):

    def fully_resolve_ref(
        self,
        node: Ast,
        global_scope: FpyScope,
        global_scope_name: str,
        state: CompileState,
    ) -> FpyReference | None:
        """resolves the given node recursively, if it is fully a reference. if at any point it
        is not a ref, or if it is a ref to something which doesn't exist, generate a compile error.

        return the resolved reference"""

        if not is_instance_compat(node, (AstVar, AstGetAttr)):
            state.err(f"Unknown {global_scope_name}", node)
            return None

        if is_instance_compat(node, AstVar):
            parent_scope = global_scope
            name = node.var
        else:
            parent_scope = self.fully_resolve_ref(
                node.parent, global_scope, global_scope_name, state
            )
            name = node.attr

        if parent_scope is None:
            # parent doesn't exist
            # error already raised
            return None

        if not is_instance_compat(parent_scope, dict):
            # parent scope is something other than a namespace
            # this is not possible for fprime types based on the system we have
            state.err(f"Unknown {global_scope_name}", node)
            return None

        resolved_ref = parent_scope.get(name)
        if resolved_ref is None:
            state.err(f"Unknown {global_scope_name}", node)
            return None

        state.resolved_references[node] = resolved_ref
        return resolved_ref

    def try_resolve_var_as_value(
        self,
        node: Ast,
        state: CompileState,
    ) -> bool:
        if not is_instance_compat(node, AstReference):
            # not a reference, nothing to resolve
            return True

        if not is_instance_compat(node, AstVar):
            # it is a reference but it's not a var
            # recurse until we find the var
            return self.try_resolve_var_as_value(node.parent, state)

        local_scope = state.local_scopes[node]
        resolved = None
        while local_scope is not None and resolved is None:
            resolved = local_scope.get(node.var)
            local_scope = state.scope_parents[local_scope]

        if resolved is None:
            # unable to find this symbol in the hierarchy of local scopes
            # look it up in the global scope
            resolved = state.runtime_values.get(node.var)

        if resolved is None:
            state.err(f"Unknown value", node)
            return False

        state.resolved_references[node] = resolved
        return True

    def visit_AstFuncCall(self, node: AstFuncCall, state: CompileState):
        func = self.fully_resolve_ref(node.func, state.callables, "function", state)
        if func is None:
            return
        if is_instance_compat(func, dict):
            # this is a ref to a namespace which contains a func, but not a func itself
            state.err(f"Unknown function", node.func)
            return
        # otherwise:
        # must be a callable because we resolved it in callables
        assert is_instance_compat(func, FpyCallable), func

        for arg in node.args if node.args is not None else []:
            # arg value refs must have values at runtime
            if not self.try_resolve_var_as_value(arg, state):
                return

    def visit_AstIf_AstElif(self, node: Union[AstIf, AstElif], state: CompileState):
        # if condition expr refs must be "runtime values" (tlm/prm/const/etc)
        if not self.try_resolve_var_as_value(node.condition, state):
            return

    def visit_AstBinaryOp(self, node: AstBinaryOp, state: CompileState):
        # lhs/rhs side of stack op, if they are refs, must be refs to "runtime vals"
        if not self.try_resolve_var_as_value(node.lhs, state):
            return
        if not self.try_resolve_var_as_value(node.rhs, state):
            return

    def visit_AstUnaryOp(self, node: AstUnaryOp, state: CompileState):
        if not self.try_resolve_var_as_value(node.val, state):
            return

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        if not self.try_resolve_var_as_value(node.lhs, state):
            return

        if node.type_ann is not None:
            # in this pass, we also go ahead and finish up the types because they're easy
            var_type = self.fully_resolve_ref(node.type_ann, state.types, "type", state)
            if var_type is None:
                # already errored
                return
            if is_instance_compat(var_type, dict):
                # this is a ref to a namespace which contains a type, but not a type itself
                state.err(f"Unknown type", node.type_ann)
                return
            # must be a type because we resolved it in type
            assert is_instance_compat(var_type, type), var_type
            # okay, we know the var, we know the type, let's update the var type
            # in the struct
            var = state.resolved_references[node.lhs]
            assert is_instance_compat(var, FpyVariable), var
            assert is_instance_compat(var_type, type), var_type
            var.type = var_type

        if not self.try_resolve_var_as_value(node.rhs, state):
            return

    def visit_AstFor(self, node: AstFor, state: CompileState):
        if not self.try_resolve_var_as_value(node.loop_var, state):
            return

        # this really shouldn't be possible to be a var right now
        # but this is future proof
        if not self.try_resolve_var_as_value(node.range, state):
            return

    def visit_AstWhile(self, node: AstWhile, state: CompileState):
        if not self.try_resolve_var_as_value(node.condition, state):
            return

    def visit_AstAssert(self, node: AstAssert, state: CompileState):
        if not self.try_resolve_var_as_value(node.condition, state):
            return
        if node.exit_code is not None:
            if not self.try_resolve_var_as_value(node.exit_code, state):
                return

    def visit_AstVar(self, node: AstVar, state: CompileState):
        # make sure that all vars are resolved when we get to them
        # if not resolved, then the var is "outside" of a context which could resolve it
        # usually this would just mean it's on its own on a line. what is it referring to?
        # idk
        if node not in state.resolved_references:
            state.err("Expression is invalid when used here", node)
            return

    def visit_AstGetItem(self, node: AstGetItem, state: CompileState):
        if not self.try_resolve_var_as_value(node.item, state):
            return

    def visit_AstRange(self, node: AstRange, state: CompileState):
        if not self.try_resolve_var_as_value(node.lower_bound, state):
            return
        if not self.try_resolve_var_as_value(node.upper_bound, state):
            return

    def visit_AstLiteral_AstGetAttr(
        self, node: Union[AstLiteral, AstGetAttr], state: CompileState
    ):
        # don't need to do anything for literals or getattr, but just have this here for completion's sake
        # the reason we don't need to do anything for getattr is because the point of this
        # pass is explicitly not to resolve getattr, just resolve vars (and types), not general
        # getattr
        # we don't do this now because we need to resolve all expr types first
        # before we can figure out whether a getattr is correct, and this pass lets
        # us now do that (i.e. after this pass, we have enough info about the program
        # that we can decide types of any expr)
        pass

    def visit_default(self, node, state):
        # coding error, missed an expr
        assert not is_instance_compat(node, AstStmtWithExpr), node


class CheckUseBeforeDeclare(Visitor):

    def __init__(self):
        super().__init__()
        self.currently_declared_vars: list[FpyVariable] = []

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        if not is_instance_compat(node.lhs, AstVar):
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
        if not is_instance_compat(ref, FpyVariable):
            # not a variable, might be a type name or smth
            return

        if is_instance_compat(ref.declaration, AstFor):
            # this will be handled  by other pass
            return
        if (
            is_instance_compat(ref.declaration, AstAssign)
            and ref.declaration.lhs == node
        ):
            # this is the initial name of the variable. don't crash
            return

        if ref not in self.currently_declared_vars:
            state.err(f"'{node.var}' used before declared", node)
            return


class EnsureVariableNotReferenced(Visitor):
    def __init__(self, var: FpyVariable):
        super().__init__()
        self.var = var

    def visit_AstVar(self, node: AstVar, state: CompileState):
        ref = state.resolved_references[node]
        if ref == self.var:
            state.err(f"'{node.var}' used before declared", node)
            return


class CheckUseBeforeDeclareForLoopVariables(TopDownVisitor):

    def __init__(self):
        super().__init__()
        self.currently_declared_vars: list[FpyVariable] = []

    def visit_AstFor(self, node: AstFor, state: CompileState):
        var = state.resolved_references[node.loop_var]

        self.currently_declared_vars.append(var)
        # also double check that the loop var isn't referenced in the range
        EnsureVariableNotReferenced(var).run(node.range, state)

    def visit_AstVar(self, node: AstVar, state: CompileState):
        ref = state.resolved_references[node]
        if not is_instance_compat(ref, FpyVariable):
            # not a variable, might be a type name or smth
            return

        if is_instance_compat(ref.declaration, AstAssign):
            # handled by prev pass
            return
        if (
            is_instance_compat(ref.declaration, AstFor)
            and ref.declaration.loop_var == node
        ):
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
        state.err(
            f"Expected {typename(type)}, found {typename(unconverted_type)}", node
        )
        return False

    def can_coerce_type(self, from_type: FppType, to_type: FppType) -> bool:
        """return True if the type coercion rules allow from_type to be implicitly converted to to_type"""
        if from_type == to_type:
            # no coercion necessary
            return True
        if from_type == FpyStringValue and issubclass(to_type, StringValue):
            # we can convert the literal String type to any string type
            return True
        if not issubclass(from_type, NumericalValue) or not issubclass(
            to_type, NumericalValue
        ):
            # if one of the src or dest aren't numerical, we can't coerce
            return False

        # now we must answer:
        # are all values of from_type representable in the destination type?

        # if going from float to integer, definitely not
        if issubclass(from_type, FloatValue) and issubclass(to_type, IntegerValue):
            return False

        # in general: if either src or dest is one of our FpyXYZValue types, which are
        # arb precision, we allow this coercion.
        # it's easy to argue we should allow converting to arb precision. but why would
        # we allow arb precision to go to an 8 bit type, e.g.?
        # we have a big advantage: the arb precision types are only used for constants. that
        # means we actually know what the value is, so we can actually check!
        # however, we won't perform that check here. That will happen later in the
        # const_convert_type func in the CalcConstExprValues
        # for now, we will let the compilation proceed if either side is arb precision

        if (
            from_type in ARBITRARY_PRECISION_TYPES
            or to_type in ARBITRARY_PRECISION_TYPES
        ):
            return True

        # otherwise, both src and dest have finite bits

        # if we currently have a float
        if issubclass(from_type, FloatValue):
            # the dest must be a float and must be >= width
            return issubclass(to_type, FloatValue) and to_type.get_bits() >= from_type.get_bits()

        # otherwise must be an int
        assert issubclass(from_type, IntegerValue)
        # int to float is allowed in any case.
        # this is the big exception to our rule about full representation. this can cause loss of precision
        # for large integer values
        if issubclass(to_type, FloatValue):
            return True

        # the dest must be an int with the same signedness and >= width
        from_unsigned = from_type in UNSIGNED_INTEGER_TYPES
        to_unsigned = to_type in UNSIGNED_INTEGER_TYPES
        return (
            from_unsigned == to_unsigned and to_type.get_bits() >= from_type.get_bits()
        )

    def pick_intermediate_type(
        self, arg_types: list[FppType], op: BinaryStackOp | UnaryStackOp
    ) -> FppType:
        """return the intermediate type that all arguments should be converted to for the given operator"""

        if op in BOOLEAN_OPERATORS:
            return BoolValue

        non_numeric = any(not issubclass(t, NumericalValue) for t in arg_types)

        if (op == BinaryStackOp.EQUAL or op == BinaryStackOp.NOT_EQUAL) and non_numeric:
            # comparison of complex types (structs/strings/arrays/enum consts)
            if len(set(arg_types)) != 1:
                # can only compare equality between the same types
                return None
            return arg_types[0]

        # all other cases require that arguments are numeric
        if non_numeric:
            return None

        # we split this algo up into two stages: picking the type category (float, uint or int), and picking the type bitwidth

        # pick the type category:
        type_category = None
        if op == BinaryStackOp.DIVIDE or op == BinaryStackOp.EXPONENT:
            # always do true division and exponentiation over floats, python style
            # this is because, for the given op, even with integer inputs, we might get
            # float outputs
            type_category = "float"
            # TODO problem: this means that if we do I32 / F32, it doesn't work b/c we can't convert I32 to F32
        elif any(issubclass(t, FloatValue) for t in arg_types):
            # otherwise if any args are floats, use float
            type_category = "float"
        elif any(t in UNSIGNED_INTEGER_TYPES for t in arg_types):
            # otherwise if any args are unsigned, use unsigned
            type_category = "uint"
        else:
            # otherwise use signed int
            type_category = "int"

        # pick the bitwidth
        # we only use the arb precision types for constants, so if theyre all arb precision, they're consts
        constants = all(t in ARBITRARY_PRECISION_TYPES for t in arg_types)

        if constants:
            # we can constant fold this, so use infinite bitwidth
            if type_category == "float":
                return FpyFloatValue
            assert type_category == "int" or type_category == "uint"
            return FpyIntegerValue

        # can't const fold
        if type_category == "float":
            return F64Value
        if type_category == "uint":
            return U64Value
        assert type_category == "int"
        return I64Value

    def is_type_constant_size(self, type: FppType) -> bool:
        """return true if the type is statically sized"""
        if issubclass(type, StringValue):
            return False

        if issubclass(type, ArrayValue):
            return self.is_type_constant_size(type.MEMBER_TYPE)

        if issubclass(type, StructValue):
            for _, arg_type, _, _ in type.MEMBER_LIST:
                if not self.is_type_constant_size(arg_type):
                    return False
            return True

        return True

    def get_members(
        self, node: Ast, parent_type: FppType, state: CompileState
    ) -> list[tuple[str, FppType]] | None:
        if not issubclass(parent_type, (StructValue, TimeValue)):
            return {}

        if not self.is_type_constant_size(parent_type):
            state.err(
                f"{parent_type} has non-constant sized members, cannot access members",
                node,
            )
            return None

        member_list: list[tuple[str, FppType]] = None
        if issubclass(parent_type, StructValue):
            member_list = [t[0:2] for t in parent_type.MEMBER_LIST]
        else:
            # if it is a time type, there are some "implied" members
            member_list = []
            member_list.append(("time_base", U16Value))
            member_list.append(("time_context", U8Value))
            member_list.append(("seconds", U32Value))
            member_list.append(("useconds", U32Value))
        return member_list

    def get_ref_type(self, ref: FpyReference) -> FppType:
        """returns the fprime type of the ref, if it were to be evaluated as an expression"""
        if isinstance(ref, ChTemplate):
            result_type = ref.ch_type_obj
        elif isinstance(ref, PrmTemplate):
            result_type = ref.prm_type_obj
        elif isinstance(ref, FppValue):
            # constant value
            result_type = type(ref)
        elif isinstance(ref, FpyCallable):
            # a reference to a callable isn't a type in and of itself
            # it has a return type but you have to call it (with an AstFuncCall)
            # consider making a separate "reference" type
            result_type = NothingValue
        elif isinstance(ref, FpyVariable):
            result_type = ref.type
        elif isinstance(ref, type):
            # a reference to a type doesn't have a value, and so doesn't have a type,
            # in and of itself. if this were a function call to the type's ctor then
            # it would have a value and thus a type
            result_type = NothingValue
        elif isinstance(ref, FieldReference):
            result_type = ref.type
        elif isinstance(ref, dict):
            # reference to a scope. scopes don't have values
            result_type = NothingValue
        else:
            assert False, ref

        return result_type

    def visit_AstGetAttr(self, node: AstGetAttr, state: CompileState):
        parent_ref = state.resolved_references.get(node.parent)

        if is_instance_compat(parent_ref, (type, FpyCallable)):
            state.err("Unknown attribute", node)
            return

        ref = None
        if is_instance_compat(parent_ref, dict):
            # getattr of a namespace
            # parent won't actually have a type
            ref = parent_ref.get(node.attr)
            if ref is None:
                state.err("Unknown attribute", node)
                return
            # GetAttr should never resolve to a lexical variable; variables are accessed directly
            assert not is_instance_compat(
                ref, FpyVariable
            ), "Field resolution unexpectedly found a local variable"
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
                if not is_instance_compat(parent_ref, FieldReference)
                else parent_ref.base_ref
            )
            # we also calculate a "base offset" wrt. the start of the base_ref type, so you
            # can easily pick out this field from a value of the base ref type
            base_offset = (
                0
                if not is_instance_compat(parent_ref, FieldReference)
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
                f"{typename(parent_type)} has no member named {node.attr}",
                node,
            )
            return

        ref_type = self.get_ref_type(ref)

        state.resolved_references[node] = ref
        state.expr_unconverted_types[node] = ref_type
        state.expr_converted_types[node] = ref_type

    def visit_AstGetItem(self, node: AstGetItem, state: CompileState):
        parent_ref = state.resolved_references.get(node.parent)

        if is_instance_compat(parent_ref, (type, FpyCallable, dict)):
            state.err("Unknown item", node)
            return

        # otherwise, we should definitely have a well-defined type for our parent expr

        parent_type = state.expr_unconverted_types[node.parent]

        if not self.is_type_constant_size(parent_type):
            state.err(
                f"{typename(parent_type)} has non-constant sized members, cannot access items",
                node,
            )
            return

        if not issubclass(parent_type, ArrayValue):
            state.err(f"{typename(parent_type)} is not an array", node)
            return

        # coerce the index expression to array index type
        if not self.coerce_expr_type(node.item, ArrayIndexType, state):
            return

        base_ref = (
            parent_ref
            if not is_instance_compat(parent_ref, FieldReference)
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
        ref_type = self.get_ref_type(ref)

        state.expr_unconverted_types[node] = ref_type
        state.expr_converted_types[node] = ref_type

    def visit_AstNumber(self, node: AstNumber, state: CompileState):
        # give a best guess as to the final type of this node. we don't actually know
        # its bitwidth or signedness yet
        if is_instance_compat(node.value, Decimal):
            result_type = FpyFloatValue
        else:
            result_type = FpyIntegerValue

        state.expr_unconverted_types[node] = result_type
        state.expr_converted_types[node] = result_type

    def visit_AstBinaryOp(self, node: AstBinaryOp, state: CompileState):
        lhs_type = state.expr_unconverted_types[node.lhs]
        rhs_type = state.expr_unconverted_types[node.rhs]

        intermediate_type = self.pick_intermediate_type([lhs_type, rhs_type], node.op)
        if intermediate_type is None:
            state.err(
                f"Op {node.op} undefined for {typename(lhs_type)}, {typename(rhs_type)}",
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
            result_type = BoolValue

        state.op_intermediate_types[node] = intermediate_type
        state.expr_unconverted_types[node] = result_type
        state.expr_converted_types[node] = result_type

    def visit_AstUnaryOp(self, node: AstUnaryOp, state: CompileState):
        val_type = state.expr_unconverted_types[node.val]

        intermediate_type = self.pick_intermediate_type([val_type], node.op)
        if intermediate_type is None:
            state.err(f"Op {node.op} undefined for {typename(val_type)}", node)
            return

        if not self.coerce_expr_type(node.val, intermediate_type, state):
            return

        result_type = None
        if node.op in NUMERIC_OPERATORS:
            result_type = intermediate_type
        else:
            result_type = BoolValue

        state.op_intermediate_types[node] = intermediate_type
        state.expr_unconverted_types[node] = result_type
        state.expr_converted_types[node] = result_type

    def visit_AstString(self, node: AstString, state: CompileState):
        state.expr_unconverted_types[node] = FpyStringValue
        state.expr_converted_types[node] = FpyStringValue

    def visit_AstBoolean(self, node: AstBoolean, state: CompileState):
        state.expr_unconverted_types[node] = BoolValue
        state.expr_converted_types[node] = BoolValue

    def check_args_coercible_to_func(
        self,
        node: AstFuncCall,
        func: FpyCallable,
        node_args: list[AstExpr],
        state: CompileState,
    ) -> CompileError | None:
        """check if a function call matches the expected arguments.
        given args must be coercible to expected args, with a special case for casting
        where any numeric type is accepted.
        returns a compile error if no match, otherwise none"""
        func_args = func.args
        if len(node_args) < len(func_args):
            return CompileError(
                f"Missing arguments (expected {len(func_args)} found {len(node_args)})",
                node,
            )
        if len(node_args) > len(func_args):
            return CompileError(
                f"Too many arguments (expected {len(func_args)} found {len(node_args)})",
                node,
            )
        if is_instance_compat(func, FpyCast):
            # casts do not follow coercion rules, because casting is the counterpart of coercion!
            # coercion is implicit, casting is explicit. if they say they want to cast, we let them
            node_arg = node_args[0]
            input_type = state.expr_unconverted_types[node_arg]
            output_type = func.to_type
            # right now we only have casting to numbers
            assert output_type in SPECIFIC_NUMERIC_TYPES
            if not issubclass(input_type, NumericalValue):
                # cannot convert a non-numeric type to a numeric type
                return CompileError(
                    f"Expected a number, found {typename(input_type)}", node_arg
                )
            # no error! looks good to me
            return

        for value_expr, arg in zip(node_args, func_args):
            arg_name, arg_type = arg

            unconverted_type = state.expr_unconverted_types[value_expr]
            if not self.can_coerce_type(unconverted_type, arg_type):
                return CompileError(
                    f"Expected {typename(arg_type)}, found {typename(unconverted_type)}",
                    node,
                )
        # all args r good
        return

    def visit_AstFuncCall(self, node: AstFuncCall, state: CompileState):
        func = state.resolved_references.get(node.func)
        if func is None:
            # if it were a reference to a callable, it would have already been resolved
            # if it were a ref to smth else, it would have already errored
            # so it's not even a ref, just some expr
            state.err(f"Unknown function", node.func)
            return
        node_args = node.args if node.args else []

        error_or_none = self.check_args_coercible_to_func(node, func, node_args, state)
        if is_instance_compat(error_or_none, CompileError):
            state.errors.append(error_or_none)
            return
        # otherwise, no error, we're good!

        # okay, we've made sure that the func is possible
        # to call with these args

        # go handle coercion/casting
        if is_instance_compat(func, FpyCast):
            node_arg = node_args[0]
            output_type = func.to_type
            # we're going from input_type to output type, and we're going to ignore
            # the coercion rules
            state.expr_converted_types[node_arg] = output_type
            # keep track of which ones we explicitly cast. this will
            # let us turn off some checks for boundaries later when we do const folding
            # we turn off the checks because the user is asking us to force this!
            state.expr_explicit_casts.append(node_arg)
        else:
            for value_expr, arg in zip(node_args, func.args):
                arg_name, arg_type = arg

                # should be good 2 go based on the check func above
                state.expr_converted_types[value_expr] = arg_type

        state.expr_unconverted_types[node] = func.return_type
        state.expr_converted_types[node] = func.return_type

    def visit_AstRange(self, node: AstRange, state: CompileState):
        if not self.coerce_expr_type(node.lower_bound, LoopVarValue, state):
            return
        if not self.coerce_expr_type(node.upper_bound, LoopVarValue, state):
            return

        state.expr_unconverted_types[node] = RangeValue
        state.expr_converted_types[node] = RangeValue

    def visit_AstAssign(self, node: AstAssign, state: CompileState):
        # should be present in resolved refs because we only let it through if
        # variable is attr, item or var
        lhs_ref = state.resolved_references[node.lhs]
        if not is_instance_compat(lhs_ref, (FpyVariable, FieldReference)):
            state.err("Invalid assignment", node.lhs)
            return

        lhs_type = None
        if is_instance_compat(lhs_ref, FpyVariable):
            lhs_type = lhs_ref.type
        else:
            # briefly check that we're only trying
            # to modify an fpy var
            if not is_instance_compat(lhs_ref.base_ref, FpyVariable):
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
        if not self.coerce_expr_type(node.condition, BoolValue, state):
            return
        if node.exit_code is not None:
            if not self.coerce_expr_type(node.exit_code, U8Value, state):
                return

    def visit_AstFor(self, node: AstFor, state: CompileState):
        # range must coerce to a range!
        if not self.coerce_expr_type(node.range, RangeValue, state):
            return

    def visit_AstWhile(self, node: AstWhile, state: CompileState):
        if not self.coerce_expr_type(node.condition, BoolValue, state):
            return

    def visit_AstIf_AstElif(self, node: Union[AstIf, AstElif], state: CompileState):
        if not self.coerce_expr_type(node.condition, BoolValue, state):
            return

    def visit_default(self, node, state):
        # coding error, missed an expr
        assert not is_instance_compat(node, AstStmtWithExpr), node


class CalculateConstExprValues(Visitor):
    """for each expr, try to calculate its constant value and store it in a map. stores None if no value could be
    calculated at compile time, and NothingType if the expr had no value"""

    def const_convert_type(
        self,
        from_val: FppValue,
        to_type: FppType,
        node: Ast,
        state: CompileState,
        skip_range_check: bool = False,
    ) -> FppValue | None:
        try:
            from_type = type(from_val)

            if from_type == to_type:
                # no conversion necessary
                return from_val

            if issubclass(to_type, StringValue):
                assert from_type == FpyStringValue, from_type
                return to_type(from_val.val)

            if issubclass(to_type, FloatValue):
                assert issubclass(from_type, NumericalValue), from_type
                from_val = from_val.val

                if to_type == FpyFloatValue:
                    # arbitrary precision
                    # decimal constructor should handle all cases: int, float, or other Decimal
                    return FpyFloatValue(Decimal(from_val))

                # otherwise, we're going to a finite bitwidth float type

                # based on inspection of the underlying FloatValue classes,
                # floats do not need narrowing handling
                coerced_value = float(from_val)
                converted = to_type(coerced_value)
                try:
                    # catch if we would crash the struct packing lib
                    converted.serialize()
                except OverflowError:
                    state.err(
                        f"{from_val} is out of range for type {typename(to_type)}",
                        node,
                    )
                    return None
                return converted
            if issubclass(to_type, IntegerValue):
                assert issubclass(from_type, NumericalValue), from_type
                from_val = from_val.val

                if to_type == FpyIntegerValue:
                    # arbitrary precision
                    # int constructor should handle all cases: int, float, or Decimal
                    return FpyIntegerValue(int(from_val))

                # otherwise going to a finite bitwidth integer type

                if not skip_range_check:
                    # does it fit within bounds?
                    # check that the value can fit in the dest type
                    dest_min, dest_max = to_type.range()
                    if from_val < dest_min or from_val > dest_max:
                        state.err(
                            f"{from_val} is out of range for type {typename(to_type)}",
                            node,
                        )
                        return None

                    # just convert it
                    from_val = int(from_val)
                else:
                    # we skipped the range check, but it's still gotta fit. cut it down

                    # handle narrowing, if necessary
                    from_val = int(from_val)
                    # if signed, convert to unsigned (bit representation should be the same)
                    # first cut down to bitwidth. performed in two's complement
                    mask = (1 << to_type.get_bits()) - 1
                    # this also implicitly converts value to an unsigned number
                    from_val &= mask
                    if to_type in SIGNED_INTEGER_TYPES:
                        # now if the target was signed:
                        sign_bit = 1 << (to_type.get_bits() - 1)
                        if from_val & sign_bit:
                            # the sign bit is set, the result should be negative
                            # subtract the max value as this is how two's complement works
                            from_val -= 1 << to_type.get_bits()

                # okay, we either checked that the value fits in the dest, or we've skipped
                # the check and changed the value to fit
                return to_type(from_val)

            assert False, (from_val, from_type, to_type)
        except TypeException as e:
            state.err(f"For type {typename(from_type)}: {e}", node)
            return None

    def visit_AstLiteral(self, node: AstLiteral, state: CompileState):
        unconverted_type = state.expr_unconverted_types[node]

        try:
            expr_value = unconverted_type(node.value)
        except TypeException as e:
            # TODO can this be reached any more? maybe for string types
            state.err(f"For type {typename(unconverted_type)}: {e}", node)
            return

        skip_range_check = node in state.expr_explicit_casts
        converted_type = state.expr_converted_types[node]
        if converted_type != unconverted_type:
            expr_value = self.const_convert_type(
                expr_value, converted_type, node, state, skip_range_check
            )
            if expr_value is None:
                return

        state.expr_converted_values[node] = expr_value

    def visit_AstGetAttr(self, node: AstGetAttr, state: CompileState):
        unconverted_type = state.expr_unconverted_types[node]
        converted_type = state.expr_converted_types[node]
        ref = state.resolved_references[node]
        expr_value = None
        if is_instance_compat(ref, (type, dict, FpyCallable)):
            # these types have no value
            state.expr_converted_values[node] = NothingValue()
            assert unconverted_type == converted_type, (
                unconverted_type,
                converted_type,
            )
            return
        elif is_instance_compat(ref, (ChTemplate, PrmTemplate, FpyVariable)):
            # has a value but won't try to calc at compile time
            state.expr_converted_values[node] = None
            return
        elif is_instance_compat(ref, FppValue):
            expr_value = ref
        elif is_instance_compat(ref, FieldReference):
            parent_value = state.expr_converted_values[node.parent]
            if parent_value is None:
                # no compile time constant value for our parent here
                state.expr_converted_values[node] = None
                return

            # we are accessing an attribute of something with an fprime value at compile time
            # we must be getting a member
            if is_instance_compat(parent_value, StructValue):
                expr_value = parent_value._val[node.attr]
            elif is_instance_compat(parent_value, TimeValue):
                if node.attr == "seconds":
                    expr_value = U32Value(parent_value.seconds)
                elif node.attr == "useconds":
                    expr_value = U32Value(parent_value.useconds)
                elif node.attr == "time_base":
                    expr_value = U16Value(parent_value.timeBase)
                elif node.attr == "time_context":
                    expr_value = U8Value(parent_value.timeContext)
                else:
                    assert False, node.attr
            else:
                assert False, parent_value

        assert expr_value is not None

        assert is_instance_compat(expr_value, unconverted_type), (
            expr_value,
            unconverted_type,
        )

        skip_range_check = node in state.expr_explicit_casts
        if converted_type != unconverted_type:
            expr_value = self.const_convert_type(
                expr_value, converted_type, node, state, skip_range_check
            )
            if expr_value is None:
                return
        state.expr_converted_values[node] = expr_value

    def visit_AstGetItem(self, node: AstGetItem, state: CompileState):
        ref = state.resolved_references[node]
        # get item can only be a field reference
        assert is_instance_compat(ref, FieldReference), ref

        parent_value = state.expr_converted_values[node.parent]

        if parent_value is None:
            # no compile time constant value for our parent here
            state.expr_converted_values[node] = None
            return

        assert is_instance_compat(parent_value, ArrayValue), parent_value

        idx = state.expr_converted_values.get(node.item)
        if idx is None:
            # no compile time constant value for our index
            state.expr_converted_values[node] = None
            return

        assert is_instance_compat(idx, U64Value)

        expr_value = parent_value._val[idx._val]

        unconverted_type = state.expr_unconverted_types[node]
        assert is_instance_compat(expr_value, unconverted_type), (
            expr_value,
            unconverted_type,
        )

        skip_range_check = node in state.expr_explicit_casts
        converted_type = state.expr_converted_types[node]
        if converted_type != unconverted_type:
            expr_value = self.const_convert_type(
                expr_value, converted_type, node, state, skip_range_check
            )
            if expr_value is None:
                return
        state.expr_converted_values[node] = expr_value

    def visit_AstVar(self, node: AstVar, state: CompileState):
        unconverted_type = state.expr_unconverted_types[node]
        converted_type = state.expr_converted_types[node]
        ref = state.resolved_references[node]
        expr_value = None
        if is_instance_compat(ref, (type, dict, FpyCallable)):
            # these types have no value
            state.expr_converted_values[node] = NothingValue()
            assert unconverted_type == converted_type, (
                unconverted_type,
                converted_type,
            )
            return
        elif is_instance_compat(ref, (ChTemplate, PrmTemplate, FpyVariable)):
            # has a value but won't try to calc at compile time
            state.expr_converted_values[node] = None
            return
        elif is_instance_compat(ref, FppValue):
            expr_value = ref
        elif is_instance_compat(ref, FieldReference):
            assert False, ref

        assert expr_value is not None

        assert is_instance_compat(expr_value, unconverted_type), (
            expr_value,
            unconverted_type,
        )

        skip_range_check = node in state.expr_explicit_casts
        if converted_type != unconverted_type:
            expr_value = self.const_convert_type(
                expr_value, converted_type, node, state, skip_range_check
            )
            if expr_value is None:
                return
        state.expr_converted_values[node] = expr_value

    def visit_AstFuncCall(self, node: AstFuncCall, state: CompileState):
        func = state.resolved_references[node.func]
        assert is_instance_compat(func, FpyCallable)
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
        if is_instance_compat(func, FpyTypeCtor):
            # actually construct the type
            if issubclass(func.type, StructValue):
                instance = func.type()
                # pass in args as a dict
                # t[0] is the arg name
                arg_dict = {t[0]: v for t, v in zip(func.type.MEMBER_LIST, arg_values)}
                instance._val = arg_dict
                expr_value = instance

            elif issubclass(func.type, ArrayValue):
                instance = func.type()
                instance._val = arg_values
                expr_value = instance

            elif func.type == TimeValue:
                expr_value = TimeValue(*[val.val for val in arg_values])

            else:
                # no other FppTypees have ctors
                assert False, func.return_type
        elif is_instance_compat(func, FpyCast):
            # should only be one value. it should be of some numeric type
            # our const convert type func will convert it for us
            expr_value = arg_values[0]
        else:
            # don't try to calculate the value of this function call
            # it's something like a cmd or macro
            state.expr_converted_values[node] = None
            return

        unconverted_type = state.expr_unconverted_types[node]
        assert is_instance_compat(expr_value, unconverted_type), (
            expr_value,
            unconverted_type,
        )

        skip_range_check = node in state.expr_explicit_casts
        converted_type = state.expr_converted_types[node]
        if converted_type != unconverted_type:
            expr_value = self.const_convert_type(
                expr_value, converted_type, node, state, skip_range_check
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

        if not is_instance_compat(lhs_value, ValueType) or not is_instance_compat(
            rhs_value, ValueType
        ):
            # if one of them isn't a ValueType, assume it must be TimeValue
            assert type(lhs_value) == type(rhs_value) and is_instance_compat(
                lhs_value, TimeValue
            ), (
                lhs_value,
                rhs_value,
            )
        else:
            # get the actual pythonic value from the fpp type
            lhs_value = lhs_value.val
            rhs_value = rhs_value.val

        folded_value = None
        # Arithmetic operations
        try:
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
                if not is_instance_compat(lhs_value, Number):
                    # comparing two complex types
                    assert type(lhs_value) == type(rhs_value), (lhs_value, rhs_value)
                    # for now we don't fold this
                    folded_value = None
                else:
                    folded_value = lhs_value == rhs_value
            elif node.op == BinaryStackOp.NOT_EQUAL:
                if not is_instance_compat(lhs_value, Number):
                    # comparing two complex types
                    assert type(lhs_value) == type(rhs_value), (lhs_value, rhs_value)
                    # for now we don't fold this
                    folded_value = None
                else:
                    folded_value = lhs_value != rhs_value
            else:
                # missing an operation
                assert False, node.op
        except ZeroDivisionError:
            state.err("Divide by zero error", node)
            return
        except OverflowError:
            state.err("Overflow error", node)
            return
        except ValueError as err:
            state.err(str(err) if str(err) else "Domain error", node)
            return
        except decimal.InvalidOperation:
            state.err("Domain error", node)
            return

        if folded_value is None:
            # give up, don't try to calculate the value of this expr at compile time
            state.expr_converted_values[node] = None
            return

        if type(folded_value) == int:
            folded_value = FpyIntegerValue(folded_value)
        elif type(folded_value) == Decimal:
            folded_value = FpyFloatValue(folded_value)
        elif type(folded_value) == bool:
            folded_value = BoolValue(folded_value)
        else:
            assert False, folded_value

        # first fold, store the result in arbitrary precision

        # then if the expression is some other type, convert:
        skip_range_check = node in state.expr_explicit_casts
        unconverted_type = state.expr_unconverted_types.get(node)
        # the intent of this is to handle situations where we're constant folding and the results cannot be arbitrary precision
        folded_value = self.const_convert_type(
            folded_value, unconverted_type, node, state, skip_range_check=False
        )

        converted_type = state.expr_converted_types.get(node)
        # okay and now perform type coercion/casting
        if converted_type != unconverted_type:
            folded_value = self.const_convert_type(
                folded_value, converted_type, node, state, skip_range_check
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
        assert is_instance_compat(value, ValueType), value

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
            folded_value = FpyIntegerValue(folded_value)
        elif type(folded_value) == Decimal:
            folded_value = FpyFloatValue(folded_value)
        elif type(folded_value) == bool:
            folded_value = BoolValue(folded_value)
        else:
            assert False, folded_value

        # first fold, store the result in arbitrary precision

        # then if the expression is some other type, convert:
        skip_range_check = node in state.expr_explicit_casts
        unconverted_type = state.expr_unconverted_types.get(node)
        # the intent of this is to handle situations where we're constant folding and the results cannot be arbitrary precision
        folded_value = self.const_convert_type(
            folded_value, unconverted_type, node, state, skip_range_check=False
        )

        converted_type = state.expr_converted_types.get(node)
        if converted_type != unconverted_type:
            folded_value = self.const_convert_type(
                folded_value, converted_type, node, state, skip_range_check
            )
            if folded_value is None:
                return
        state.expr_converted_values[node] = folded_value

    def visit_AstRange(self, node: AstRange, state: CompileState):
        # ranges don't really end up having a value, they kinda just exist as a type
        state.expr_converted_values[node] = None

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
        assert issubclass(parent_type, ArrayValue), parent_type

        if idx_value.val < 0 or idx_value.val >= parent_type.LENGTH:
            state.err(
                f"Index {idx_value.val} out of bounds for array type {typename(parent_type)} with length {parent_type.LENGTH}",
                node.item,
            )
            return


class WarnRangesAreNotEmpty(Visitor):
    def visit_AstRange(self, node: AstRange, state: CompileState):
        # if the index is a const, we should be able to check if it's in bounds
        lower_value: LoopVarValue = state.expr_converted_values.get(node.lower_bound)
        upper_value: LoopVarValue = state.expr_converted_values.get(node.lower_bound)
        if lower_value is None or upper_value is None:
            # cannot check at compile time
            return

        if lower_value.val >= upper_value.val:
            state.warn("Range is empty", node)
