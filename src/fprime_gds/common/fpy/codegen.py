from __future__ import annotations
from typing import Union

from fprime_gds.common.fpy.model import DirectiveErrorCode
from fprime_gds.common.fpy.types import (
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
    GetMemberDirective,
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
        # used for break in while and for loop
        self.while_loop_end_indices: dict[AstWhile, int] = {}
        # used for continue in while loop
        self.while_loop_start_indices: dict[AstWhile, int] = {}
        # used for continue in for loop
        self.for_loop_increment_indices: dict[AstWhile, int] = {}

    def try_emit_expr_as_const(self, node: AstExpr, state: CompileState) -> Union[list[Directive],None]:
        expr_value = state.expr_converted_values.get(node)

        if expr_value is None:
            # no const value
            return None

        assert not isinstance(expr_value, (InternalIntType, InternalStringType, InternalFloatType))

        if isinstance(expr_value, NothingValue):
            # nothing type has no value
            return []

        # it has a constant value at compile time
        serialized_expr_value = expr_value.serialize()

        # push it to the stack
        return [PushValDirective(serialized_expr_value)]


    def emit(self, node: Ast, start_idx: int, state: CompileState) -> list[Directive]:
        # if node is an expr, emit the code to push the expr to the stack, accounting
        # for type conversions


        pass

    def emit_AstScopedBody(self, node: AstScopedBody, start_idx: int, state: CompileState):
        dirs = []
        if state.root == node:
            dirs.append(AllocateDirective(state.lvar_array_size_bytes))
        for stmt in node.stmts:
            dirs.extend(self.emit(stmt, start_idx + len(dirs), state))
        return dirs

    def emit_AstBody(self, node: AstBody, start_idx: int, state: CompileState):
        dirs = []
        for stmt in node.stmts:
            dirs.extend(self.emit(stmt, start_idx + len(dirs), state))
        return dirs

    def emit_AstIf(self, node: AstIf, start_idx: int, state: CompileState):
        dirs = []

        cases: list[tuple[AstExpr, AstBody]] = []
        goto_ends: list[GotoDirective] = []

        cases.append((node.condition, node.body))

        if node.elifs is not None:
            for case in node.elifs.cases:
                cases.append((case.condition, case.body))

        for case in cases:
            case_dirs = []
            # put the conditional on top of stack
            case_dirs.extend(self.emit(case[0], start_idx + len(dirs), state))
            # include if stmt (update the end idx later)
            if_dir = IfDirective(-1)

            case_dirs.append(if_dir)
            # include body
            case_dirs.extend(self.emit(case[1], start_idx + len(dirs) + len(case_dirs), state))
            # include a temporary goto end of if, will be refined later
            goto_dir = GotoDirective(-1)
            case_dirs.append(goto_dir)
            goto_ends.append(goto_dir)

            # if false, skip the body and goto
            if_dir.false_goto_dir_index = (
                start_idx + len(dirs) + len(case_dirs)
            )

            dirs.extend(case_dirs)

        if node.els is not None:
            dirs.extend(self.emit(node.els, start_idx + len(dirs), state))

        for goto in goto_ends:
            goto.dir_idx = start_idx + len(dirs)

        return dirs

    def emit_AstWhile(self, node: AstWhile, start_idx: int, state: CompileState):
        # push the condition to the stack
        dirs = self.emit(node.condition, start_idx, state)
        # if the cond is true, fall thru, otherwise go to end
        if_dir = IfDirective(-1)
        dirs.append(if_dir)
        # run body
        last_stmt_dir_idx = -1
        for stmt_idx, stmt in enumerate(node.body.stmts):
            # we're going to manually emit the body's stmts instead
            # of just emitting the body, because A) it doesn't matter
            # and B) we need the index of the last statement in the body
            # if we're a for loop, because that's where the continue stmt
            # needs to go
            if stmt_idx == len(node.body.stmts) - 1:
                # last stmt
                last_stmt_dir_idx = start_idx + len(dirs)
            dirs.append(self.emit(stmt, start_idx + len(dirs), state))
        # go back to condition check
        dirs.append(GotoDirective(start_idx))
        end_line_idx = start_idx + len(dirs)
        if_dir.false_goto_dir_index = end_line_idx

        # save this so we know where to go with break and continue
        self.while_loop_end_indices[node] = end_line_idx
        self.while_loop_start_indices[node] = start_idx
        if node in state.desugared_for_loops:
            # there should be at least one stmt in a for loop's body (the inc stmt)
            assert last_stmt_dir_idx != -1
            self.for_loop_increment_indices[node] = last_stmt_dir_idx
        return dirs

    def emit_AstBreak(self, node: AstBreak, start_idx: int, state: CompileState):
        enclosing_loop = state.enclosing_loops[node]
        # go to end of enclosing loop
        end_of_loop_idx = self.while_loop_end_indices[enclosing_loop]

        return [GotoDirective(end_of_loop_idx)]

    def emit_AstContinue(self, node: AstContinue, start_idx: int, state: CompileState):
        enclosing_loop = state.enclosing_loops[node]
        # if it used to be a for loop, go to the increment statement
        if enclosing_loop in state.desugared_for_loops:
            # the last stmt in the body of the while loop is the increment stmt
            end_of_loop_idx = self.for_loop_increment_indices[enclosing_loop]
        else:
            # if it's a while loop, go to the beginning
            end_of_loop_idx = self.while_loop_start_indices[enclosing_loop]
        return [GotoDirective(end_of_loop_idx)]

    def emit_AstFor(self, node: AstFor, start_idx: int, state: CompileState):
        # should have been desugared out
        assert False, node

    def emit_AstGetItem(self, node: AstGetItem, start_idx: int, state: CompileState):
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

        dirs = self.emit(node.parent, start_idx, state)

        # push the index (must be U64) to the stack
        dirs.extend(self.emit(node.item, start_idx + len(dirs), state))
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
        dirs.append(
            PushValDirective(U64Type(parent_type.MEMBER_TYPE.getMaxSize()))
        )
        dirs.append(IntMultiplyDirective())

        # okay now we have the offset on the stack

        # get the member from the stack at this offset, discard the rest of
        # the parent
        dirs.append(
            GetMemberDirective(
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

    def emit_AstGetAttr(self, node: AstGetAttr, start_idx: int, state: CompileState):
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
            dirs.extend(self.emit(ref.parent_expr, start_idx + len(dirs), state))
            assert ref.local_offset is not None
            # use the converted type of parent
            parent_type = state.expr_converted_types[ref.parent_expr]
            # push the offset to the stack
            dirs.append(PushValDirective(U64Type(ref.local_offset).serialize()))
            dirs.append(
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
            dirs.extend(convert_numeric_type(unconverted_type, converted_type))

        return dirs

    def emit_AstBinaryOp(self, node: AstBinaryOp, start_idx: int, state: CompileState):
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
        dirs = [self.emit(node.lhs, start_idx, state)]
        dirs.extend(self.emit(node.rhs, start_idx + len(dirs), state))
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

    def emit_AstUnaryOp(self, node: AstUnaryOp, start_idx: int, state: CompileState):
        const_dirs = self.try_emit_expr_as_const(node, state)
        if const_dirs is not None:
            return const_dirs

        # push val to stack
        dirs = [self.emit(node.val, start_idx, state)]

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

    def emit_AstFuncCall(self, node: AstFuncCall, start_idx: int, state: CompileState):
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
                    dirs.extend(self.emit(arg_node, start_idx + len(dirs), state))
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
                dirs.extend(self.emit(arg_node, start_idx + len(dirs), state))

            dirs.append(func.dir())
        elif isinstance(func, FpyTypeCtor):
            # put arg values onto stack in correct order for serialization
            for arg_node in node_args:
                dirs.extend(self.emit(arg_node, start_idx + len(dirs), state))
        elif isinstance(func, FpyCast):
            # just putting the arg value on the stack should be good enough, the
            # conversion will happen below
            dirs.extend(self.emit(node_args[0], start_idx + len(dirs), state))
        else:
            assert False, func

        # perform type conversion if called for
        unconverted_type = state.expr_unconverted_types[node]
        converted_type = state.expr_converted_types[node]
        if unconverted_type != converted_type:
            dirs.extend(convert_numeric_type(unconverted_type, converted_type))

        return dirs

    def emit_AstAssign(self, node: AstAssign, start_idx: int, state: CompileState):
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
                    assert issubclass(lhs_parent_type, ArrayType), (
                        lhs_parent_type,
                        type(lhs_parent_type),
                    )
                    const_lvar_offset = lhs.base_ref.lvar_offset + const_idx_expr_value.val * lhs.type.ELEMENT_TYPE.getMaxSize()
                # otherwise, the array idx is unknown at compile time. we will have to calculate it

        # start with rhs on stack
        dirs = self.emit(node.rhs, start_idx, state)
        
        if const_lvar_offset != -1:
            # in this case, we can use StoreConstOffset
            dirs.append(StoreConstOffsetDirective(const_lvar_offset, lhs.type.getMaxSize()))

                # let's push the offset of base lvar first, then
                # calculate the offset in base type, then add

                # push as u64 because we're going to do math
                dirs.append(
                    PushValDirective(U64Type(lhs.base_ref.lvar_offset).serialize())
                )


                # push the index to the stack, do a bounds check,
                index_dirs = state.directives[lhs.idx_expr]
                dirs.extend(index_dirs)
                # okay now let's do an array oob check
                dirs.append(
                    DuplicateDirective(ArrayIndexType.getMaxSize())
                )  # duplicate the index
                # convert idx to u64
                dirs.extend(convert_numeric_type(ArrayIndexType, U64Type))
                dirs.append(
                    PushValDirective(ArrayIndexType(lhs_parent_type.LENGTH).serialize())
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

        # use the converted type, the node value has already had
        # conversion handled, so its stack value is converted
        converted_type = state.expr_converted_types[node.rhs]

        # now that lvar array offset is pushed, use it to store in lvar array
        dirs.append(StoreDirective(converted_type.getMaxSize()))

        state.directives[node] = dirs
        
    def emit_AstLiteral(self, node: AstLiteral, start_idx: int, state: CompileState):
        const_dirs = self.try_emit_expr_as_const(node, state)
        assert const_dirs is not None
        return const_dirs

    def emit_AstAssert(self, node: AstAssert, state: CompileState):
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
