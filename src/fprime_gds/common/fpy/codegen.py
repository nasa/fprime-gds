from __future__ import annotations
from typing import Union

from fprime_gds.common.fpy.model import DirectiveErrorCode
from fprime_gds.common.fpy.types import (
    ArrayIndexType,
    CompileState,
    FieldReference,
    FpyCmd,
    FpyMacro,
    FpyVariable,
    InternalIntType,
    InternalStringType,
    NothingType,
    TopDownVisitor,
    Visitor,
    convert_numeric_type,
)

from fprime_gds.common.fpy.bytecode.directives import (
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
    AstAssert,
    AstBinaryOp,
    AstBody,
    AstElif,
    AstElifs,
    AstExpr,
    AstFor,
    AstGetAttr,
    AstGetItem,
    AstScopedBody,
    AstScopedBody,
    AstIf,
    AstAssign,
    AstFuncCall,
    AstUnaryOp,
    AstVar,
    AstWhile,
)

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
            # TODO how can i be sure that i'm using the right combination of converted/unconverted?
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

    def visit_AstFor(self, node: AstFor, state: CompileState):
        # convert the lower bound into the intermediate type
        pass


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

    def visit_AstWhile(self, node: AstWhile, state: CompileState):
        count = 0
        # include the condition
        count += state.node_dir_counts[node.condition]
        # include if stmt
        count += 1
        # include body
        count += state.node_dir_counts[node.body]
        # include a goto begin of while
        count += 1
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

    def visit_AstBody(
        self, node: Union[AstScopedBody, AstBody], state: CompileState
    ):
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

    def visit_AstBody(
        self, node: Union[AstScopedBody, AstBody], state: CompileState
    ):
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

    def visit_AstWhile(self, node: AstWhile, state: CompileState):
        line_idx = state.start_line_idx[node]
        state.start_line_idx[node.condition] = line_idx
        line_idx += state.node_dir_counts[node.condition]
        # include if stmt
        line_idx += 1
        state.start_line_idx[node.body] = line_idx
        line_idx += state.node_dir_counts[node.body]
        # include goto stmt begin
        line_idx += 1

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

    def visit_AstWhile(self, node: AstWhile, state: CompileState):
        start_line_idx = state.start_line_idx[node]
        # push the condition to the stack
        dirs = state.directives[node.condition]
        # if the cond is true, fall thru, otherwise go to end
        if_dir = IfDirective(-1)
        dirs.append(if_dir)
        # run body
        dirs.extend(state.directives[node.body])
        # go back to condition check
        dirs.append(GotoDirective(start_line_idx))
        end_line_idx = start_line_idx + len(dirs)
        if_dir.false_goto_dir_index = end_line_idx

        state.directives[node] = dirs


    def visit_AstFor(self, node: AstFor, state: CompileState):
        # should have been desugared out
        assert False, node


    def visit_AstBody(
        self, node: Union[AstScopedBody, AstBody], state: CompileState
    ):
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

