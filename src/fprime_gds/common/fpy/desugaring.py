from __future__ import annotations
from fprime_gds.common.fpy.bytecode.directives import BinaryStackOp, Directive
from fprime_gds.common.fpy.syntax import (
    Ast,
    AstAssign,
    AstBinaryOp,
    AstFor,
    AstNumber,
    AstRange,
    AstVar,
    AstWhile,
)
from fprime_gds.common.fpy.types import (
    CompileState,
    ForLoopAnalysis,
    FppType,
    FpyReference,
    FpyIntegerValue,
    LoopVarValue,
    Transformer,
)
from fprime_gds.common.models.serialize.type_base import BaseType as FppValue
from fprime_gds.common.models.serialize.bool_type import BoolType as BoolValue


class DesugarForLoops(Transformer):

    # this function forces you to give values for all of these dicts
    # really the point is to make sure i don't forget to consider this
    # for one of the new nodes
    def new(
        self,
        state: CompileState,
        node: Ast,
        expr_converted_type: FppType | None,
        expr_unconverted_type: FppType | None,
        expr_converted_value: FppValue | None,
        op_intermediate_type: type[Directive] | None,
        resolved_reference: FpyReference | None,
    ) -> Ast:
        node.id = state.next_node_id
        state.next_node_id += 1
        state.expr_converted_types[node] = expr_converted_type
        state.expr_unconverted_types[node] = expr_unconverted_type
        state.expr_converted_values[node] = expr_converted_value
        state.op_intermediate_types[node] = op_intermediate_type
        state.resolved_references[node] = resolved_reference
        return node

    def initialize_loop_var(
        self, state: CompileState, loop_node: AstFor, loop_info: ForLoopAnalysis
    ) -> Ast:
        # 1 <node.loop_var>: LoopVarType = <node.range.lower_bound>
        # OR (depending on whether redeclaring or not)
        # 1 <node.loop_var> = <node.range.lower_bound>

        if loop_info.reuse_existing_loop_var:
            loop_var_type_var = None
        else:
            loop_var_type_name = LoopVarValue.get_canonical_name()
            # create a new node for the type_ann
            loop_var_type_var = self.new(state, AstVar(None, loop_var_type_name),
                                        expr_converted_type=None,
                                        expr_unconverted_type=None,
                                        expr_converted_value=None,
                                        op_intermediate_type=None,
                                        resolved_reference=LoopVarValue)

        lhs = loop_node.loop_var
        rhs = loop_node.range.lower_bound
        return self.new(
            state,
            AstAssign(None, lhs, loop_var_type_var, rhs),
            expr_converted_type=None,
            expr_unconverted_type=None,
            expr_converted_value=None,
            op_intermediate_type=None,
            resolved_reference=None,
        )

    def declare_upper_bound_var(
        self, state: CompileState, loop_node: AstFor, loop_info: ForLoopAnalysis
    ) -> Ast:
        # 2 $upper_bound_var: LoopVarType = <node.range.upper_bound>

        # ub var for use in assignment
        # type is gonna be loop var type
        # gonna be used in the astassign lhs, no need assign a type in the dict
        upper_bound_var: AstVar = self.new(
            state,
            AstVar(None, loop_info.upper_bound_var.name),
            expr_converted_type=None,
            expr_unconverted_type=None,
            expr_converted_value=None,
            op_intermediate_type=None,
            resolved_reference=loop_info.upper_bound_var,
        )

        loop_var_type_name = LoopVarValue.get_canonical_name()
        # create a new node for the type_ann
        loop_var_type_var = self.new(state, AstVar(None, loop_var_type_name),
                                     expr_converted_type=None,
                                     expr_unconverted_type=None,
                                     expr_converted_value=None,
                                     op_intermediate_type=None,
                                     resolved_reference=LoopVarValue)

        # assign ub to ub var
        # not an expr, not a ref
        return self.new(
            state,
            AstAssign(
                None, upper_bound_var, loop_var_type_var, loop_node.range.upper_bound
            ),
            expr_converted_type=None,
            expr_unconverted_type=None,
            expr_converted_value=None,
            op_intermediate_type=None,
            resolved_reference=None,
        )

    def loop_var_plus_one(
        self, state: CompileState, loop_node: AstFor, loop_info: ForLoopAnalysis
    ):
        # <node.loop_var> + 1
        # the expression adding one to the lv
        # will have conv type of lv, unconverted type depends what the addition intermediate type is
        # we've already determined the dir
        lhs = self.new(
            state,
            AstVar(None, loop_info.loop_var.name),
            expr_converted_type=LoopVarValue,
            expr_unconverted_type=LoopVarValue,
            expr_converted_value=None,
            op_intermediate_type=None,
            resolved_reference=loop_info.loop_var,
        )
        rhs = self.new(
            state,
            AstNumber(None, 1),
            expr_converted_type=LoopVarValue,
            expr_unconverted_type=FpyIntegerValue,
            expr_converted_value=LoopVarValue(1),
            op_intermediate_type=None,
            resolved_reference=None,
        )

        return self.new(
            state,
            AstBinaryOp(None, lhs, BinaryStackOp.ADD, rhs),
            expr_converted_type=LoopVarValue,
            expr_unconverted_type=LoopVarValue,
            expr_converted_value=None,
            op_intermediate_type=LoopVarValue,
            resolved_reference=None,
        )

    def increment_loop_var(
        self, state: CompileState, loop_node: AstFor, loop_info: ForLoopAnalysis
    ) -> Ast:
        # <node.loop_var> = <node.loop_var> + 1

        # create a new loop var ref for use in lhs of loop var inc
        lhs = self.new(
            state,
            AstVar(None, loop_info.loop_var.name),
            expr_converted_type=None,
            expr_unconverted_type=None,
            expr_converted_value=None,
            op_intermediate_type=None,
            resolved_reference=loop_info.loop_var,
        )

        rhs = self.loop_var_plus_one(state, loop_node, loop_info)

        return self.new(
            state,
            AstAssign(None, lhs, None, rhs),
            expr_converted_type=None,
            expr_unconverted_type=None,
            expr_converted_value=None,
            op_intermediate_type=None,
            resolved_reference=None,
        )

    def while_loop_condition(
        self, state: CompileState, loop_node: AstFor, loop_info: ForLoopAnalysis
    ) -> Ast:
        # <node.loop_var> < $upper_bound_var
        # create a new loop var ref for use in lhs
        lhs = self.new(
            state,
            AstVar(None, loop_info.loop_var.name),
            expr_converted_type=LoopVarValue,
            expr_unconverted_type=LoopVarValue,
            expr_converted_value=None,
            op_intermediate_type=None,
            resolved_reference=loop_info.loop_var,
        )
        rhs = self.new(
            state,
            AstVar(None, loop_info.upper_bound_var.name),
            expr_converted_type=LoopVarValue,
            expr_unconverted_type=LoopVarValue,
            expr_converted_value=None,
            op_intermediate_type=None,
            resolved_reference=loop_info.upper_bound_var,
        )

        return self.new(
            state,
            AstBinaryOp(None, lhs, BinaryStackOp.LESS_THAN, rhs),
            expr_converted_type=BoolValue,
            expr_unconverted_type=BoolValue,
            expr_converted_value=None,
            op_intermediate_type=LoopVarValue,
            resolved_reference=None,
        )

    def while_loop(
        self, state: CompileState, loop_node: AstFor, loop_info: ForLoopAnalysis
    ) -> Ast:
        #  while <node.loop_var> < $upper_bound_var:
        #     <node.body>
        #     <node.loop_var> = <node.loop_var> + 1

        condition = self.while_loop_condition(state, loop_node, loop_info)
        increment = self.increment_loop_var(state, loop_node, loop_info)

        body = loop_node.body

        body.stmts.append(increment)

        return self.new(
            state,
            AstWhile(None, condition, body),
            expr_converted_type=None,
            expr_unconverted_type=None,
            expr_converted_value=None,
            op_intermediate_type=None,
            resolved_reference=None,
        )

    def visit_AstFor(self, node: AstFor, state: CompileState):
        assert isinstance(node.range, AstRange), node.range

        # transform this:

        # for <node.loop_var> in <node.range>:
        #     <node.body>

        # to:

        # 1 <node.loop_var>: LoopVarType = <node.range.lower_bound>
        # OR (depending on whether redeclaring or not)
        # 1 <node.loop_var> = <node.range.lower_bound>
        # 2 $upper_bound_var: LoopVarType = <node.range.upper_bound>
        # 3 while <node.loop_var> < $upper_bound_var:
        #      <node.body>
        #      <node.loop_var> = <node.loop_var> + 1

        loop_info = state.for_loops[node]

        # 1
        initialize_loop_var = self.initialize_loop_var(state, node, loop_info)
        # 2
        declare_upper_bound_var = self.declare_upper_bound_var(state, node, loop_info)
        # 3
        while_loop: AstWhile = self.while_loop(state, node, loop_info)

        # this is the first and so far only piece of code in the compiler itself written by AI
        # Update any break/continue statements in the body to point to new while loop
        # instead of the original for loop
        for key, value in list(state.enclosing_loops.items()):
            if value == node: # If a break/continue was pointing to our for loop
                state.enclosing_loops[key] = while_loop # Point it to while loop instead

        state.desugared_for_loops[while_loop] = node

        # turn one node into three
        return [initialize_loop_var, declare_upper_bound_var, while_loop]
