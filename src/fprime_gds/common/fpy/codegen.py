from __future__ import annotations
from dataclasses import dataclass
import inspect
from typing import Callable, Union, get_args, get_origin
import typing

# In Python 3.10+, the `|` operator creates a `types.UnionType`.
# We need to handle this for forward compatibility, but it won't exist in 3.9.
try:
    from types import UnionType

    UNION_TYPES = (Union, UnionType)
except ImportError:
    UNION_TYPES = (Union,)

from fprime_gds.common.fpy.ir import Ir, IrGoto, IrIf, IrLabel
from fprime_gds.common.fpy.model import DirectiveErrorCode
from fprime_gds.common.fpy.types import (
    MAX_DIRECTIVES_COUNT,
    MAX_STACK_SIZE,
    SIGNED_INTEGER_TYPES,
    SPECIFIC_FLOAT_TYPES,
    SPECIFIC_INTEGER_TYPES,
    SPECIFIC_NUMERIC_TYPES,
    UNSIGNED_INTEGER_TYPES,
    CompileState,
    FieldReference,
    FppType,
    FpyCast,
    FpyCmd,
    FpyFloatValue,
    FpyMacro,
    FpyTypeCtor,
    FpyVariable,
    FpyIntegerValue,
    FpyStringValue,
    NothingValue,
    is_instance_compat,
)

from fprime_gds.common.fpy.bytecode.directives import (
    BINARY_STACK_OPS,
    UNARY_STACK_OPS,
    AllocateDirective,
    ArrayIndexType,
    BinaryStackOp,
    ConstCmdDirective,
    DiscardDirective,
    ExitDirective,
    FloatDivideDirective,
    FloatExtendDirective,
    FloatToSignedIntDirective,
    FloatToUnsignedIntDirective,
    FloatTruncateDirective,
    FwOpcodeType,
    IntegerSignedExtend16To64Directive,
    IntegerSignedExtend32To64Directive,
    IntegerSignedExtend8To64Directive,
    IntegerTruncate64To16Directive,
    IntegerTruncate64To8Directive,
    IntegerZeroExtend16To64Directive,
    IntegerZeroExtend32To64Directive,
    IntegerZeroExtend8To64Directive,
    PeekDirective,
    FloatMultiplyDirective,
    GetFieldDirective,
    IntAddDirective,
    IntMultiplyDirective,
    LoadDirective,
    MemCompareDirective,
    NoOpDirective,
    IntegerTruncate64To32Directive,
    SignedIntToFloatDirective,
    StackCmdDirective,
    Directive,
    GotoDirective,
    IfDirective,
    NotDirective,
    PushValDirective,
    StackSizeType,
    StoreConstOffsetDirective,
    StoreDirective,
    PushPrmDirective,
    PushTlmValDirective,
    UnaryStackOp,
    UnsignedGreaterThanOrEqualDirective,
    UnsignedIntToFloatDirective,
    UnsignedLessThanDirective,
)
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.prm_template import PrmTemplate
from fprime_gds.common.models.serialize.array_type import ArrayType as ArrayValue
from fprime_gds.common.models.serialize.numerical_types import (
    U8Type as U8Value,
    U64Type as U64Value,
    I64Type as I64Value,
    F32Type as F32Value,
    F64Type as F64Value,
    IntegerType as IntegerValue,
)
from fprime_gds.common.fpy.syntax import (
    Ast,
    AstAssert,
    AstBinaryOp,
    AstBody,
    AstBreak,
    AstContinue,
    AstExpr,
    AstFor,
    AstGetAttr,
    AstGetItem,
    AstLiteral,
    AstNodeWithSideEffects,
    AstScopedBody,
    AstScopedBody,
    AstIf,
    AstAssign,
    AstFuncCall,
    AstUnaryOp,
    AstVar,
    AstWhile,
)


class GenerateCode:

    def __init__(self):
        self.emitters: dict[type[Ast], Callable] = {}
        """dict of node type to handler function"""
        self.build_emitter_dict()

    def try_emit_expr_as_const(
        self, node: AstExpr, state: CompileState
    ) -> Union[list[Directive | Ir], None]:
        """if the expr has a compile time const value, emit that as a PUSH_VAL"""
        expr_value = state.expr_converted_values.get(node)

        if expr_value is None:
            # no const value
            return None

        assert not is_instance_compat(
            expr_value, (FpyIntegerValue, FpyStringValue, FpyFloatValue)
        ), expr_value

        if is_instance_compat(expr_value, NothingValue):
            # nothing type has no value
            return []

        # it has a constant value at compile time
        serialized_expr_value = expr_value.serialize()

        # push it to the stack
        return [PushValDirective(serialized_expr_value)]

    def discard_expr_result(self, node: Ast, state: CompileState) -> list[Directive]:
        """if the node is an expr, generate code to discard its stack value"""
        if not is_instance_compat(node, AstExpr):
            # nothing to discard
            return []

        result_type = state.expr_converted_types[node]
        if result_type == NothingValue:
            return []
        if result_type.getMaxSize() > 0:
            return [DiscardDirective(result_type.getMaxSize())]
        return []

    def get_64_bit_numeric_type(self, type: FppType) -> FppType:
        """return the 64 bit version of the input numeric type"""
        assert type in SPECIFIC_NUMERIC_TYPES, type
        return (
            I64Value
            if type in SIGNED_INTEGER_TYPES
            else U64Value if type in UNSIGNED_INTEGER_TYPES else F64Value
        )

    def convert_numeric_type(
        self, from_type: FppType, to_type: FppType
    ) -> list[Directive]:
        """
        return a list of dirs needed to convert a numeric stack value of from_type to a stack value of to_type"""
        if from_type == to_type:
            return []

        # only valid runtime type conversion is between two numeric types
        assert (
            from_type in SPECIFIC_NUMERIC_TYPES and to_type in SPECIFIC_NUMERIC_TYPES
        ), (
            from_type,
            to_type,
        )

        dirs = []
        # first go to 64 bit width
        dirs.extend(self.extend_numeric_type_to_64_bits(from_type))
        from_64_bit = self.get_64_bit_numeric_type(from_type)
        to_64_bit = self.get_64_bit_numeric_type(to_type)

        # now convert between int and float if necessary
        if from_64_bit == U64Value and to_64_bit == F64Value:
            dirs.append(UnsignedIntToFloatDirective())
            from_64_bit = F64Value
        elif from_64_bit == I64Value and to_64_bit == F64Value:
            dirs.append(SignedIntToFloatDirective())
            from_64_bit = F64Value
        elif from_64_bit == U64Value or from_64_bit == I64Value:
            assert to_64_bit == U64Value or to_64_bit == I64Value
            # conversion from signed to unsigned int is implicit, doesn't need code gen
            from_64_bit = to_64_bit
        elif from_64_bit == F64Value and to_64_bit == I64Value:
            dirs.append(FloatToSignedIntDirective())
            from_64_bit = I64Value
        elif from_64_bit == F64Value and to_64_bit == U64Value:
            dirs.append(FloatToUnsignedIntDirective())
            from_64_bit = U64Value

        assert from_64_bit == to_64_bit, (from_64_bit, to_64_bit)

        # now truncate back down to desired size
        dirs.extend(
            self.truncate_numeric_type_from_64_bits(to_64_bit, to_type.getMaxSize())
        )
        return dirs

    def truncate_numeric_type_from_64_bits(
        self, from_type: FppType, new_size: int
    ) -> list[Directive]:

        assert new_size in (1, 2, 4, 8), new_size
        assert from_type.getMaxSize() == 8, from_type.getMaxSize()

        if new_size == 8:
            # already correct size
            return []

        if from_type == F64Value:
            # only one option for float trunc
            assert new_size == 4, new_size
            return [FloatTruncateDirective()]

        # must be an int
        assert issubclass(from_type, IntegerValue), from_type

        if new_size == 1:
            return [IntegerTruncate64To8Directive()]
        elif new_size == 2:
            return [IntegerTruncate64To16Directive()]

        return [IntegerTruncate64To32Directive()]

    def extend_numeric_type_to_64_bits(self, type: FppType) -> list[Directive]:
        if type.getMaxSize() == 8:
            # already 8 bytes
            return []
        if type == F32Value:
            return [FloatExtendDirective()]

        # must be an int
        assert issubclass(type, IntegerValue), type

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

    def calc_lvar_offset_of_array_element(self, node: Ast, idx_expr: AstExpr, array_type: FppType, state: CompileState) -> list[Directive|Ir]:
        """generates code to push to stack the U64 byte offset in the array for an array access, while performing an array oob
        check. idx_expr is the expression to calculate the index, and dest is the FieldReference containing info about the
        dest array"""
        dirs = []
        # let's push the offset of base lvar first, then
        # calculate the offset in base type, then add

        # push the index to the stack, do a bounds check,
        dirs.extend(self.emit(idx_expr, state))
        # okay now let's do an array oob check
        # we want to peek the index so we can consume it for the oob check
        # byte count
        dirs.append(
            PushValDirective(StackSizeType(ArrayIndexType.getMaxSize()).serialize())
        )
        # offset
        dirs.append(PushValDirective(StackSizeType(0).serialize()))
        dirs.append(PeekDirective())  # duplicate the index
        # convert idx to u64
        dirs.extend(self.convert_numeric_type(ArrayIndexType, U64Value))
        dirs.append(
            PushValDirective(U64Value(array_type.LENGTH).serialize())
        )  # push the length as U64
        # check if idx >= length
        dirs.append(UnsignedGreaterThanOrEqualDirective())
        # if true, fail with error code, otherwise go to after check
        oob_check_end_label = IrLabel(node, "oob_check_end")
        dirs.append(IrIf(oob_check_end_label))
        # push the error code we should fail with if false
        dirs.append(
            PushValDirective(
                U8Value(DirectiveErrorCode.ARRAY_OUT_OF_BOUNDS.value).serialize()
            )
        )
        dirs.append(ExitDirective())
        dirs.append(oob_check_end_label)
        # okay we're good. should still have the idx on the stack

        # multiply the index by the member type size
        dirs.append(
            PushValDirective(U64Value(array_type.MEMBER_TYPE.getMaxSize()))
        )
        dirs.append(IntMultiplyDirective())
        return dirs


    def build_emitter_dict(self):
        for name, func in inspect.getmembers(type(self), inspect.isfunction):
            if not name.startswith("emit_"):
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
                    self.emitters[t] = getattr(self, name)
            else:
                # It's not a Union, so it's a regular type
                self.emitters[param_type] = getattr(self, name)

    def emit(self, node: Ast, state: CompileState) -> list[Directive | Ir]:
        return self.emitters[type(node)](node, state)

    def emit_AstScopedBody(self, node: AstScopedBody, state: CompileState):
        dirs = []
        if state.root == node:
            # calculate lvar array size bytes, also assign lvar offsets
            for var in state.variables:
                # doesn't have an lvar idx, allocate one
                lvar_offset = state.lvar_array_size_bytes
                state.lvar_array_size_bytes += var.type.getMaxSize()
                var.lvar_offset = lvar_offset

            dirs.append(AllocateDirective(state.lvar_array_size_bytes))
        for stmt in node.stmts:
            if not is_instance_compat(stmt, AstNodeWithSideEffects):
                # if the stmt can't do anything on its own, ignore it
                # TODO warn
                continue
            dirs.extend(self.emit(stmt, state))
            # discard stack value if it was an expr
            dirs.extend(self.discard_expr_result(stmt, state))
        return dirs

    def emit_AstBody(self, node: AstBody, state: CompileState):
        dirs = []
        for stmt in node.stmts:
            if not is_instance_compat(stmt, AstNodeWithSideEffects):
                # if the stmt can't do anything on its own, ignore it
                # TODO warn
                continue
            dirs.extend(self.emit(stmt, state))
            # discard stack value if it was an expr
            dirs.extend(self.discard_expr_result(stmt, state))
        return dirs

    def emit_AstIf(self, node: AstIf, state: CompileState):
        dirs = []

        cases: list[tuple[AstExpr, AstBody]] = []

        cases.append((node.condition, node.body))

        if node.elifs is not None:
            for case in node.elifs.cases:
                cases.append((case.condition, case.body))

        if_end_label = IrLabel(node, "end")

        for case in cases:
            case_end_label = IrLabel(case[1], "end")
            case_dirs = []
            # put the conditional on top of stack
            case_dirs.extend(self.emit(case[0], state))
            # include if stmt (update the end idx later)
            if_dir = IrIf(case_end_label)

            case_dirs.append(if_dir)
            # include body
            case_dirs.extend(self.emit(case[1], state))
            # once we've finished executing the body:
            # include a goto end of if
            case_dirs.append(IrGoto(if_end_label))
            case_dirs.append(case_end_label)

            dirs.extend(case_dirs)

        if node.els is not None:
            dirs.extend(self.emit(node.els, state))

        dirs.append(if_end_label)

        return dirs

    def emit_AstWhile(self, node: AstWhile, state: CompileState):
        # start by creating labels. store them in dicts so that break/continue
        # can use them
        while_start_label = IrLabel(node, "start")
        while_end_label = IrLabel(node, "end")
        for_loop_increment_label = None
        state.while_loop_start_labels[node] = while_start_label
        state.while_loop_end_labels[node] = while_end_label
        # if this used to be a for loop:
        if node in state.desugared_for_loops:
            # there should be at least one stmt in a for loop's body (the inc stmt)
            for_loop_increment_label = IrLabel(node, "increment")
            state.for_loop_inc_labels[node] = for_loop_increment_label

        dirs = [while_start_label]
        # push the condition to the stack
        dirs.extend(self.emit(node.condition, state))
        # if the cond is true, fall thru, otherwise go to end
        dirs.append(IrIf(while_end_label))
        # run body

        for stmt_idx, stmt in enumerate(node.body.stmts):
            if not is_instance_compat(stmt, AstNodeWithSideEffects):
                # if the stmt can't do anything on its own, ignore it
                continue
            # we're going to manually emit the body's stmts instead
            # of just emitting the body, because A) it doesn't matter
            # and B) we need the index of the last statement in the body
            # if we're a for loop, because that's where the continue stmt
            # needs to go
            if (
                stmt_idx == len(node.body.stmts) - 1
                and for_loop_increment_label is not None
            ):
                # last stmt, it must be the inc stmt, add the label before it
                dirs.append(for_loop_increment_label)
            dirs.extend(self.emit(stmt, state))
            # discard stack value if it was an expr
            dirs.extend(self.discard_expr_result(stmt, state))
        # go back to condition check
        dirs.append(IrGoto(while_start_label))
        dirs.append(while_end_label)

        return dirs

    def emit_AstBreak(self, node: AstBreak, state: CompileState):
        enclosing_loop = state.enclosing_loops[node]
        loop_end = state.while_loop_end_labels[enclosing_loop]
        return [IrGoto(loop_end)]

    def emit_AstContinue(self, node: AstContinue, state: CompileState):
        enclosing_loop = state.enclosing_loops[node]
        if enclosing_loop in state.desugared_for_loops:
            loop_start = state.for_loop_inc_labels[enclosing_loop]
        else:
            loop_start = state.while_loop_end_labels[enclosing_loop]
        return [IrGoto(loop_start)]

    def emit_AstFor(self, node: AstFor, state: CompileState):
        # should have been desugared out
        assert False, node

    def emit_AstGetItem(self, node: AstGetItem, state: CompileState):
        const_dirs = self.try_emit_expr_as_const(node, state)
        if const_dirs is not None:
            return const_dirs
        ref = state.resolved_references[node]

        assert is_instance_compat(ref, FieldReference), ref

        # use the unconverted for this expr for now, because we haven't run conversion
        unconverted_type = state.expr_unconverted_types[node]
        # however, for parent, use converted because conversion has been run
        parent_type = state.expr_converted_types[node.parent]

        assert issubclass(parent_type, ArrayValue)
        assert unconverted_type == parent_type.MEMBER_TYPE, (
            parent_type.MEMBER_TYPE,
            unconverted_type,
        )
        
        # okay, we want to get an element from an array on the stack

        # TODO optimization: leave it in the lvar array instead of pushing the whole thing to stack
        # for now we push the whole thing
        dirs = self.emit(node.parent, state)

        # calculate the offset in the parent array
        dirs.extend(self.calc_lvar_offset_of_array_element(node, node.item, parent_type, state))
        # truncate back to StackSizeType which is what get field uses
        dirs.extend(self.convert_numeric_type(U64Value, StackSizeType))

        # get the member from the stack at this offset, discard the rest of
        # the parent
        dirs.append(
            GetFieldDirective(
                parent_type.getMaxSize(), parent_type.MEMBER_TYPE.getMaxSize()
            )
        )

        # now convert the type if necessary
        converted_type = state.expr_converted_types[node]
        if unconverted_type != converted_type:
            dirs.extend(self.convert_numeric_type(unconverted_type, converted_type))

        return dirs

    def emit_AstVar(self, node: AstVar, state: CompileState):
        const_dirs = self.try_emit_expr_as_const(node, state)
        if const_dirs is not None:
            return const_dirs

        ref = state.resolved_references.get(node)

        assert is_instance_compat(ref, FpyVariable), ref

        # already should be in an lvar
        dirs = [LoadDirective(ref.lvar_offset, ref.type.getMaxSize())]

        unconverted_type = state.expr_unconverted_types[node]
        converted_type = state.expr_converted_types[node]
        if unconverted_type != converted_type:
            dirs.extend(self.convert_numeric_type(unconverted_type, converted_type))

        return dirs

    def emit_AstGetAttr(self, node: AstGetAttr, state: CompileState):
        const_dirs = self.try_emit_expr_as_const(node, state)
        if const_dirs is not None:
            return const_dirs

        ref = state.resolved_references.get(node)

        if is_instance_compat(ref, dict):
            # don't generate code for it, it's a ref to a scope and
            # doesn't have a value
            return []

        # start with the unconverted type, because we haven't applied runtime type conversion yet
        unconverted_type = state.expr_unconverted_types[node]

        dirs = []

        if is_instance_compat(ref, ChTemplate):
            dirs.append(PushTlmValDirective(ref.get_id()))
        elif is_instance_compat(ref, PrmTemplate):
            dirs.append(PushPrmDirective(ref.get_id()))
        elif is_instance_compat(ref, FpyVariable):
            # already should be in an lvar
            dirs.append(LoadDirective(ref.lvar_offset, ref.type.getMaxSize()))
        elif is_instance_compat(ref, FieldReference):
            # okay, put parent dirs in first
            dirs.extend(self.emit(ref.parent_expr, state))
            assert ref.local_offset is not None
            # use the converted type of parent
            parent_type = state.expr_converted_types[ref.parent_expr]
            # push the offset to the stack
            dirs.append(PushValDirective(StackSizeType(ref.local_offset).serialize()))
            dirs.append(
                GetFieldDirective(
                    parent_type.getMaxSize(), unconverted_type.getMaxSize()
                )
            )
        else:
            assert (
                False
            ), ref  # ref should either be impossible to put on stack or should have a compile time val

        converted_type = state.expr_converted_types[node]
        if converted_type != unconverted_type:
            dirs.extend(self.convert_numeric_type(unconverted_type, converted_type))

        return dirs

    def emit_AstBinaryOp(self, node: AstBinaryOp, state: CompileState):
        const_dirs = self.try_emit_expr_as_const(node, state)
        if const_dirs is not None:
            return const_dirs

        # push lhs and rhs to stack
        dirs = self.emit(node.lhs, state)
        dirs.extend(self.emit(node.rhs, state))

        intermediate_type = state.op_intermediate_types[node]

        if (
            node.op == BinaryStackOp.EQUAL or node.op == BinaryStackOp.NOT_EQUAL
        ) and intermediate_type not in SPECIFIC_NUMERIC_TYPES:
            lhs_type = state.expr_converted_types[node.lhs]
            rhs_type = state.expr_converted_types[node.rhs]
            assert lhs_type == rhs_type, (lhs_type, rhs_type)
            dirs.append(MemCompareDirective(lhs_type.getMaxSize()))
            if node.op == BinaryStackOp.NOT_EQUAL:
                dirs.append(NotDirective())
        elif node.op == BinaryStackOp.FLOOR_DIVIDE and intermediate_type == F64Value:
            # for float floor division, do float division, then convert to int, then
            # back to float
            dirs.append(FloatDivideDirective())
            dirs.append(FloatToSignedIntDirective())
            dirs.append(SignedIntToFloatDirective())
        else:

            dir = BINARY_STACK_OPS[node.op][intermediate_type]
            if dir != NoOpDirective:
                # don't include no op
                dirs.append(dir())

        # and convert the result of the op into the desired result of this expr
        unconverted_type = state.expr_unconverted_types[node]
        converted_type = state.expr_converted_types[node]
        if unconverted_type != converted_type:
            dirs.extend(self.convert_numeric_type(unconverted_type, converted_type))

        return dirs

    def emit_AstUnaryOp(self, node: AstUnaryOp, state: CompileState):
        const_dirs = self.try_emit_expr_as_const(node, state)
        if const_dirs is not None:
            return const_dirs

        # push val to stack
        dirs = self.emit(node.val, state)

        # generate the actual op itself
        # which dir should we use?
        intermediate_type = state.op_intermediate_types[node]
        dir = UNARY_STACK_OPS[node.op][intermediate_type]

        if node.op == UnaryStackOp.NEGATE:
            # in this case, we also need to push -1
            if dir == FloatMultiplyDirective:
                dirs.append(PushValDirective(F64Value(-1).serialize()))
            elif dir == IntMultiplyDirective:
                dirs.append(PushValDirective(I64Value(-1).serialize()))

        dirs.append(dir())

        # and convert the result of the op into the desired result of this expr
        unconverted_type = state.expr_unconverted_types[node]
        converted_type = state.expr_converted_types[node]
        if unconverted_type != converted_type:
            dirs.extend(self.convert_numeric_type(unconverted_type, converted_type))

        return dirs

    def emit_AstFuncCall(self, node: AstFuncCall, state: CompileState):
        const_dirs = self.try_emit_expr_as_const(node, state)
        if const_dirs is not None:
            return const_dirs

        node_args = node.args if node.args is not None else []
        func = state.resolved_references[node.func]
        dirs = []
        if is_instance_compat(func, FpyCmd):
            const_args = not any(
                state.expr_converted_values[arg_node] is None for arg_node in node_args
            )
            if const_args:
                # can just hardcode this cmd
                arg_bytes = bytes()
                for arg_node in node_args:
                    arg_value = state.expr_converted_values[arg_node]
                    arg_bytes += arg_value.serialize()
                dirs.append(ConstCmdDirective(func.cmd.get_op_code(), arg_bytes))
            else:
                arg_byte_count = 0
                # push all args to the stack
                # keep track of how many bytes total we have pushed
                for arg_node in node_args:
                    dirs.extend(self.emit(arg_node, state))
                    arg_converted_type = state.expr_converted_types[arg_node]
                    arg_byte_count += arg_converted_type.getMaxSize()
                # then push cmd opcode to stack as u32
                dirs.append(
                    PushValDirective(FwOpcodeType(func.cmd.get_op_code()).serialize())
                )
                # now that all args are pushed to the stack, pop them and opcode off the stack
                # as a command
                dirs.append(StackCmdDirective(arg_byte_count))
        elif is_instance_compat(func, FpyMacro):
            # put all arg values on stack
            for arg_node in node_args:
                dirs.extend(self.emit(arg_node, state))

            dirs.extend(func.generate(node))
        elif is_instance_compat(func, FpyTypeCtor):
            # put arg values onto stack in correct order for serialization
            for arg_node in node_args:
                dirs.extend(self.emit(arg_node, state))
        elif is_instance_compat(func, FpyCast):
            # just putting the arg value on the stack should be good enough, the
            # conversion will happen below
            dirs.extend(self.emit(node_args[0], state))
        else:
            assert False, func

        # perform type conversion if called for
        unconverted_type = state.expr_unconverted_types[node]
        converted_type = state.expr_converted_types[node]
        if unconverted_type != converted_type:
            dirs.extend(self.convert_numeric_type(unconverted_type, converted_type))

        return dirs

    def emit_AstAssign(self, node: AstAssign, state: CompileState):
        lhs = state.resolved_references[node.lhs]

        const_lvar_offset = -1
        if is_instance_compat(lhs, FpyVariable):
            const_lvar_offset = lhs.lvar_offset
        else:
            # okay now push the lvar arr offset to stack
            assert is_instance_compat(lhs, FieldReference), lhs
            assert is_instance_compat(lhs.base_ref, FpyVariable), lhs.base_ref

            # is the lvar array offset a constant?
            # okay, are we assigning to a member or an element?
            if lhs.is_struct_member:
                # if it's a struct, then the lvar offset is always constant
                const_lvar_offset = lhs.base_offset + lhs.base_ref.lvar_offset
            else:
                assert lhs.is_array_element
                # again, offset is the offset in base type + offset of base lvar

                # however, because array idx can be variable, we might not know at compile time
                # the offset in base type.

                # check if we have a value for it
                const_idx_expr_value = state.expr_converted_values.get(lhs.idx_expr)
                if const_idx_expr_value is not None:
                    assert is_instance_compat(const_idx_expr_value, ArrayIndexType)
                    # okay, so we have a constant value index
                    lhs_parent_type = state.expr_converted_types[lhs.parent_expr]
                    const_lvar_offset = (
                        lhs.base_ref.lvar_offset
                        + const_idx_expr_value.val
                        * lhs_parent_type.MEMBER_TYPE.getMaxSize()
                    )
                # otherwise, the array idx is unknown at compile time. we will have to calculate it

        # start with rhs on stack
        dirs = self.emit(node.rhs, state)

        if const_lvar_offset != -1:
            # in this case, we can use StoreConstOffset
            dirs.append(
                StoreConstOffsetDirective(const_lvar_offset, lhs.type.getMaxSize())
            )
        else:
            # okay we don't know the offset at compile time
            # only one case where that can be:
            assert is_instance_compat(lhs, FieldReference) and lhs.is_array_element, lhs


            # we need to calculate absolute offset in lvar array
            # == (parent offset) + (offset in parent)

            # offset in parent:
            lhs_parent_type = state.expr_converted_types[lhs.parent_expr]
            dirs.extend(self.calc_lvar_offset_of_array_element(node, lhs.idx_expr, lhs_parent_type, state))

            # parent offset:
            dirs.append(PushValDirective(U64Value(lhs.base_ref.lvar_offset).serialize()))

            # add them
            dirs.append(IntAddDirective())

            # and now convert the u64 back into the StackSizeType that store expects
            dirs.extend(self.convert_numeric_type(U64Value, StackSizeType))

            # now that lvar array offset is pushed, use it to store in lvar array
            dirs.append(StoreDirective(lhs.type.getMaxSize()))

        return dirs

    def emit_AstLiteral(self, node: AstLiteral, state: CompileState):
        const_dirs = self.try_emit_expr_as_const(node, state)
        assert const_dirs is not None
        return const_dirs

    def emit_AstAssert(self, node: AstAssert, state: CompileState):
        dirs = self.emit(node.condition, state)
        # invert the condition, we want to continue to exit if fail
        dirs.append(NotDirective())
        end_label = IrLabel(node, f"pass")
        dirs.append(IrIf(end_label))
        # push the error code we should use if false, if one was given
        if node.exit_code is not None:
            dirs.extend(self.emit(node.exit_code, state))
        else:
            # otherwise just use the default EXIT_WITH_ERROR error code
            dirs.append(
                PushValDirective(
                    U8Value(DirectiveErrorCode.EXIT_WITH_ERROR.value).serialize()
                )
            )
        dirs.append(ExitDirective())
        dirs.append(end_label)

        return dirs
