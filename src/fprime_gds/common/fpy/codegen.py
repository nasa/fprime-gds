from __future__ import annotations
from dataclasses import dataclass
import inspect
from typing import Union
import typing

from fprime_gds.common.fpy.error import BackendError, CompileError
from fprime_gds.common.fpy.model import DirectiveErrorCode
from fprime_gds.common.fpy.types import (
    MAX_DIRECTIVES_COUNT,
    MAX_STACK_SIZE,
    SPECIFIC_NUMERIC_TYPES,
    ArrayIndexType,
    CompileState,
    FieldReference,
    FpyCast,
    FpyCmd,
    FpyMacro,
    FpyTypeCtor,
    FpyVariable,
    InternalFloatType,
    InternalIntType,
    InternalStringType,
    NothingValue,
    TopDownVisitor,
    Visitor,
    convert_numeric_type,
    is_instance_compat,
)

from fprime_gds.common.fpy.bytecode.directives import (
    BINARY_STACK_OPS,
    UNARY_STACK_OPS,
    AllocateDirective,
    AssertDirective,
    BinaryStackOp,
    ConstCmdDirective,
    DuplicateDirective,
    FloatMultiplyDirective,
    GetFieldDirective,
    IntAddDirective,
    IntMultiplyDirective,
    LoadDirective,
    MemCompareDirective,
    NoOpDirective,
    IntegerTruncate64To32Directive,
    StackCmdDirective,
    Directive,
    GotoDirective,
    IfDirective,
    NotDirective,
    PushValDirective,
    StoreConstOffsetDirective,
    StoreDirective,
    PushPrmDirective,
    PushTlmValDirective,
    UnaryStackOp,
    UnsignedLessThanDirective,
)
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.prm_template import PrmTemplate
from fprime.common.models.serialize.array_type import ArrayType
from fprime.common.models.serialize.numerical_types import (
    U32Type,
    U64Type,
    U8Type,
    I64Type,
    F64Type,
)
from fprime_gds.common.fpy.syntax import (
    Ast,
    AstAssert,
    AstBinaryOp,
    AstBody,
    AstBreak,
    AstContinue,
    AstElif,
    AstElifs,
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


@dataclass(frozen=True, unsafe_hash=True)
class Ir:
    pass


@dataclass(frozen=True, unsafe_hash=True)
class IrLabel(Ir):
    label: str


@dataclass(frozen=True, unsafe_hash=True)
class IrGoto(Ir):
    label: Union[str, IrLabel]


@dataclass(frozen=True, unsafe_hash=True)
class IrIf(Ir):
    goto_if_false_label: Union[str, IrLabel]


class GenerateCode:

    def try_emit_expr_as_const(
        self, node: AstExpr, state: CompileState
    ) -> Union[list[Directive|Ir], None]:
        expr_value = state.expr_converted_values.get(node)

        if expr_value is None:
            # no const value
            return None

        assert not isinstance(
            expr_value, (InternalIntType, InternalStringType, InternalFloatType)
        )

        if isinstance(expr_value, NothingValue):
            # nothing type has no value
            return []

        # it has a constant value at compile time
        serialized_expr_value = expr_value.serialize()

        # push it to the stack
        return [PushValDirective(serialized_expr_value)]

    def emit(self, node: Ast, state: CompileState) -> list[Directive|Ir]:
        # if node is an expr, emit the code to push the expr to the stack, accounting
        # for type conversions

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
            if is_instance_compat(node, param_type):
                return getattr(self, name)(node, state)
        raise NotImplementedError(node)

    def emit_AstScopedBody(self, node: AstScopedBody, state: CompileState):
        dirs = []
        if state.root == node:
            dirs.append(AllocateDirective(state.lvar_array_size_bytes))
        for stmt in node.stmts:
            if not isinstance(stmt, AstNodeWithSideEffects):
                # if the stmt can't do anything on its own, ignore it
                # TODO warn
                continue
            dirs.extend(self.emit(stmt, state))
        return dirs

    def emit_AstBody(self, node: AstBody, state: CompileState):
        dirs = []
        for stmt in node.stmts:
            if not isinstance(stmt, AstNodeWithSideEffects):
                # if the stmt can't do anything on its own, ignore it
                # TODO warn
                continue
            dirs.extend(self.emit(stmt, state))
        return dirs

    def emit_AstIf(self, node: AstIf, state: CompileState):
        dirs = []

        cases: list[tuple[AstExpr, AstBody]] = []

        cases.append((node.condition, node.body))

        if node.elifs is not None:
            for case in node.elifs.cases:
                cases.append((case.condition, case.body))

        if_end_label = IrLabel(f"{node.id}.end")

        for case in cases:
            case_end_label = IrLabel(f"{case[1].id}.end")
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
        while_start_label = IrLabel(f"{node.id}.start")
        while_end_label = IrLabel(f"{node.id}.end")
        for_loop_increment_label = None
        state.while_loop_start_labels[node] = while_start_label
        state.while_loop_end_labels[node] = while_end_label
        # if this used to be a for loop:
        if node in state.desugared_for_loops:
            # there should be at least one stmt in a for loop's body (the inc stmt)
            for_loop_increment_label = IrLabel(f"{node.id}.increment")
            state.for_loop_inc_labels[node] = for_loop_increment_label

        dirs = [while_start_label]
        # push the condition to the stack
        dirs.extend(self.emit(node.condition, state))
        # if the cond is true, fall thru, otherwise go to end
        dirs.append(IrIf(while_end_label))
        # run body

        for stmt_idx, stmt in enumerate(node.body.stmts):
            if not isinstance(stmt, AstNodeWithSideEffects):
                # if the stmt can't do anything on its own, ignore it
                continue
            # we're going to manually emit the body's stmts instead
            # of just emitting the body, because A) it doesn't matter
            # and B) we need the index of the last statement in the body
            # if we're a for loop, because that's where the continue stmt
            # needs to go
            if stmt_idx == len(node.body.stmts) - 1 and for_loop_increment_label is not None:
                # last stmt, it must be the inc stmt, add the label before it
                dirs.append(for_loop_increment_label)
            dirs.extend(self.emit(stmt, state))
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
        # these are the dirs to put the parent on the stack
        # we want to put it on the stack and then grab a certain
        # size at a certain offset

        # optimization: leave it in the lvar array

        dirs = self.emit(node.parent, state)

        # push the index (must be U64) to the stack
        dirs.extend(self.emit(node.item, state))
        # okay now let's do an array oob check
        dirs.append(
            DuplicateDirective(ArrayIndexType.getMaxSize())
        )  # duplicate the index
        # convert idx to u64
        dirs.extend(convert_numeric_type(ArrayIndexType, U64Type))
        dirs.append(
            PushValDirective(ArrayIndexType(parent_type.LENGTH))
        )  # push the length
        # convert len to u64
        dirs.extend(convert_numeric_type(ArrayIndexType, U64Type))
        # check if idx < length
        dirs.append(UnsignedLessThanDirective())
        # assert it's true
        # push the assert error code we should fail with if false
        dirs.append(
            PushValDirective(
                U8Type(DirectiveErrorCode.ARRAY_OUT_OF_BOUNDS.value).serialize()
            )
        )
        dirs.append(AssertDirective())
        # okay we're good. should still have the idx on the stack

        # multiply the index by the member type size
        dirs.append(PushValDirective(U64Type(parent_type.MEMBER_TYPE.getMaxSize())))
        dirs.append(IntMultiplyDirective())

        # okay now we have the offset on the stack
        # have to truncate to 32 bits
        dirs.append(IntegerTruncate64To32Directive())

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
            dirs.extend(convert_numeric_type(unconverted_type, converted_type))

        return dirs

    def emit_AstVar(self, node: AstVar, state: CompileState):
        const_dirs = self.try_emit_expr_as_const(node, state)
        if const_dirs is not None:
            return const_dirs

        ref = state.resolved_references.get(node)

        assert isinstance(ref, FpyVariable), ref

        # already should be in an lvar
        dirs = [LoadDirective(ref.lvar_offset, ref.type.getMaxSize())]

        unconverted_type = state.expr_unconverted_types[node]
        converted_type = state.expr_converted_types[node]
        if unconverted_type != converted_type:
            dirs.extend(convert_numeric_type(unconverted_type, converted_type))

        return dirs

    def emit_AstGetAttr(self, node: AstGetAttr, state: CompileState):
        const_dirs = self.try_emit_expr_as_const(node, state)
        if const_dirs is not None:
            return const_dirs

        ref = state.resolved_references.get(node)

        if isinstance(ref, dict):
            # don't generate code for it, it's a ref to a scope and
            # doesn't have a value
            return []

        # start with the unconverted type, because we haven't applied runtime type conversion yet
        unconverted_type = state.expr_unconverted_types[node]

        dirs = []

        if isinstance(ref, ChTemplate):
            dirs.append(PushTlmValDirective(ref.get_id()))
        elif isinstance(ref, PrmTemplate):
            dirs.append(PushPrmDirective(ref.get_id()))
        elif isinstance(ref, FpyVariable):
            # already should be in an lvar
            dirs.append(LoadDirective(ref.lvar_offset, ref.type.getMaxSize()))
        elif isinstance(ref, FieldReference):
            # okay, put parent dirs in first
            dirs.extend(self.emit(ref.parent_expr, state))
            assert ref.local_offset is not None
            # use the converted type of parent
            parent_type = state.expr_converted_types[ref.parent_expr]
            # push the offset to the stack
            dirs.append(PushValDirective(U32Type(ref.local_offset).serialize()))
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
            dirs.extend(convert_numeric_type(unconverted_type, converted_type))

        return dirs

    def emit_AstBinaryOp(self, node: AstBinaryOp, state: CompileState):
        const_dirs = self.try_emit_expr_as_const(node, state)
        if const_dirs is not None:
            return const_dirs

        # which dir should we use?
        intermediate_type = state.op_intermediate_types[node]
        dir = None
        if (
            node.op == BinaryStackOp.EQUAL or node.op == BinaryStackOp.NOT_EQUAL
        ) and intermediate_type not in SPECIFIC_NUMERIC_TYPES:
            dir = MemCompareDirective
        else:
            dir = BINARY_STACK_OPS[node.op][intermediate_type]

        # push lhs and rhs to stack
        dirs = self.emit(node.lhs, state)
        dirs.extend(self.emit(node.rhs, state))
        # generate the actual op itself
        if dir == MemCompareDirective:
            lhs_type = state.expr_converted_types[node.lhs]
            rhs_type = state.expr_converted_types[node.rhs]
            assert lhs_type == rhs_type, (lhs_type, rhs_type)
            dirs.append(dir(lhs_type.getMaxSize()))
            if node.op == BinaryStackOp.NOT_EQUAL:
                dirs.append(NotDirective())
        elif dir == NoOpDirective:
            # don't include no op
            pass
        else:
            dirs.append(dir())

        # and convert the result of the op into the desired result of this expr
        unconverted_type = state.expr_unconverted_types[node]
        converted_type = state.expr_converted_types[node]
        if unconverted_type != converted_type:
            dirs.extend(convert_numeric_type(unconverted_type, converted_type))

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
                dirs.append(PushValDirective(F64Type(-1).serialize()))
            elif dir == IntMultiplyDirective:
                dirs.append(PushValDirective(I64Type(-1).serialize()))

        dirs.append(dir())

        # and convert the result of the op into the desired result of this expr
        unconverted_type = state.expr_unconverted_types[node]
        converted_type = state.expr_converted_types[node]
        if unconverted_type != converted_type:
            dirs.extend(convert_numeric_type(unconverted_type, converted_type))

        return dirs

    def emit_AstFuncCall(self, node: AstFuncCall, state: CompileState):
        const_dirs = self.try_emit_expr_as_const(node, state)
        if const_dirs is not None:
            return const_dirs

        node_args = node.args if node.args is not None else []
        func = state.resolved_references[node.func]
        dirs = []
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
                    PushValDirective(U32Type(func.cmd.get_op_code()).serialize())
                )
                # now that all args are pushed to the stack, pop them and opcode off the stack
                # as a command
                dirs.append(StackCmdDirective(arg_byte_count))
        elif isinstance(func, FpyMacro):
            # put all arg values on stack
            for arg_node in node_args:
                dirs.extend(self.emit(arg_node, state))

            dirs.append(func.dir())
        elif isinstance(func, FpyTypeCtor):
            # put arg values onto stack in correct order for serialization
            for arg_node in node_args:
                dirs.extend(self.emit(arg_node, state))
        elif isinstance(func, FpyCast):
            # just putting the arg value on the stack should be good enough, the
            # conversion will happen below
            dirs.extend(self.emit(node_args[0], state))
        else:
            assert False, func

        # perform type conversion if called for
        unconverted_type = state.expr_unconverted_types[node]
        converted_type = state.expr_converted_types[node]
        if unconverted_type != converted_type:
            dirs.extend(convert_numeric_type(unconverted_type, converted_type))

        return dirs

    def emit_AstAssign(self, node: AstAssign, state: CompileState):
        lhs = state.resolved_references[node.lhs]

        const_lvar_offset = -1
        if isinstance(lhs, FpyVariable):
            const_lvar_offset = lhs.lvar_offset
        else:
            # okay now push the lvar arr offset to stack
            assert isinstance(lhs, FieldReference), lhs
            assert isinstance(lhs.base_ref, FpyVariable), lhs.base_ref

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
                    assert isinstance(const_idx_expr_value, ArrayIndexType)
                    # okay, so we have an index which might be variable
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
            # okay we don't know the offset
            assert lhs.is_array_element
            # let's push the offset of base lvar first, then
            # calculate the offset in base type, then add

            # push as u64 because we're going to do math
            dirs.append(PushValDirective(U64Type(lhs.base_ref.lvar_offset).serialize()))

            # push the index to the stack, do a bounds check,
            dirs.extend(self.emit(lhs.idx_expr, state))
            # okay now let's do an array oob check
            dirs.append(
                DuplicateDirective(ArrayIndexType.getMaxSize())
            )  # duplicate the index
            # convert idx to u64
            dirs.extend(convert_numeric_type(ArrayIndexType, U64Type))
            lhs_parent_type = state.expr_converted_types[lhs.parent_expr]
            dirs.append(
                PushValDirective(U64Type(lhs_parent_type.LENGTH).serialize())
            )  # push the length as U64
            # check if idx < length
            dirs.append(UnsignedLessThanDirective())
            # assert it's true
            # push the assert error code we should fail with if false
            dirs.append(
                PushValDirective(
                    U8Type(DirectiveErrorCode.ARRAY_OUT_OF_BOUNDS.value).serialize()
                )
            )
            dirs.append(AssertDirective())
            # okay we're good. should still have the idx on the stack

            # multiply the index by the member type size
            dirs.append(
                PushValDirective(U64Type(lhs_parent_type.MEMBER_TYPE.getMaxSize()))
            )
            dirs.append(IntMultiplyDirective())
            # okay, now we should have the offset wrt base of the parent type on the stack
            # right below it is the offset in the lvar array
            # add them
            dirs.append(IntAddDirective())

            # and now convert the u64 back into the U32 that store expects
            dirs.append(IntegerTruncate64To32Directive())

            # now that lvar array offset is pushed, use it to store in lvar array
            dirs.append(StoreDirective(lhs.type.getMaxSize()))

        return dirs

    def emit_AstLiteral(self, node: AstLiteral, state: CompileState):
        const_dirs = self.try_emit_expr_as_const(node, state)
        assert const_dirs is not None
        return const_dirs

    def emit_AstAssert(self, node: AstAssert, state: CompileState):
        dirs = self.emit(node.condition, state)
        # push the error code we should use if false, if one was given
        if node.exit_code is not None:
            dirs.extend(self.emit(node.exit_code, state))
        else:
            # otherwise just use the default "ASSERTION_FAILURE error code"
            dirs.append(
                PushValDirective(
                    U8Type(DirectiveErrorCode.ASSERTION_FAILURE.value).serialize()
                )
            )
        dirs.append(AssertDirective())

        return dirs


class IrPass:
    def run(
        self, ir: list[Directive | Ir], state: CompileState
    ) -> Union[list[Directive | Ir], BackendError]:
        pass


class ResolveLabels(IrPass):
    def run(self, ir, state: CompileState):
        labels: dict[str, int] = {}
        idx = 0
        dirs = []
        for dir in ir:
            if isinstance(dir, IrLabel):
                if dir.label in labels:
                    return BackendError(f"Label {dir.label} already exists")
                labels[dir.label] = idx
                continue
            idx += 1

        # okay, we have all the labels
        for dir in ir:
            if isinstance(dir, IrLabel):
                # drop these from the result
                continue
            elif isinstance(dir, IrGoto):
                label = dir.label.label if isinstance(dir.label, IrLabel) else dir.label
                if label not in labels:
                    return BackendError(f"Unknown label {label}")
                dirs.append(GotoDirective(labels[label]))
            elif isinstance(dir, IrIf):
                label = dir.goto_if_false_label.label if isinstance(dir.goto_if_false_label, IrLabel) else dir.goto_if_false_label
                if label not in labels:
                    return BackendError(f"Unknown label {label}")
                dirs.append(IfDirective(labels[label]))
            else:
                dirs.append(dir)

        return dirs


class FinalChecks(IrPass):
    def run(self, ir, state):
        if state.lvar_array_size_bytes > MAX_STACK_SIZE:
            return BackendError(
                f"Stack size too big (expected less than {MAX_STACK_SIZE}, had {state.lvar_array_size_bytes})"
            )
        if len(ir) > MAX_DIRECTIVES_COUNT:
            return BackendError(
                f"Too many directives in sequence (expected less than {MAX_DIRECTIVES_COUNT}, had {len(ir)})"
            )

        for dir in ir:
            # double check we've got rid of all the IR
            assert isinstance(dir, Directive), dir

        return ir
