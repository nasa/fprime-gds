from types import SimpleNamespace

import pytest

from fprime_gds.common.fpy.syntax import (
    AstAssign,
    AstBoolean,
    AstLiteral,
    AstNumber,
    AstPass,
    AstScopedBody,
    AstString,
    AstVar,
)
from fprime_gds.common.fpy.types import Transformer, Visitor, TopDownVisitor


class _State(SimpleNamespace):
    def __init__(self):
        super().__init__(errors=[])

    def err(self, msg, node):  # pragma: no cover - forwarded through tests
        self.errors.append((msg, node))


def _make_state():
    return _State()


def test_visitor_registers_union_types():
    class LiteralVisitor(Visitor):
        def __init__(self):
            self.seen = []
            super().__init__()

        def visit_literals(self, node: AstLiteral, state):
            self.seen.append(type(node))

    visitor = LiteralVisitor()
    state = _make_state()

    string_node = AstString(meta=None, value="value")
    boolean_node = AstBoolean(meta=None, value=True)

    visitor.run(string_node, state)
    visitor.run(boolean_node, state)

    assert visitor.visitors.get(AstString).__func__ is LiteralVisitor.visit_literals
    assert visitor.visitors.get(AstBoolean).__func__ is LiteralVisitor.visit_literals
    assert visitor.seen == [AstString, AstBoolean]


def test_visitor_depth_first_traversal():
    class RecordingVisitor(Visitor):
        def __init__(self):
            self.visited = []
            super().__init__()

        def visit_var(self, node: AstVar, state):
            self.visited.append(f"var:{node.var}")

        def visit_number(self, node: AstNumber, state):
            self.visited.append(f"number:{node.value}")

        def visit_assign(self, node: AstAssign, state):
            self.visited.append("assign")

    visitor = RecordingVisitor()
    state = _make_state()

    lhs = AstVar(meta=None, var="x")
    rhs = AstNumber(meta=None, value=7)
    assign = AstAssign(meta=None, lhs=lhs, type_ann=None, rhs=rhs)

    visitor.run(assign, state)

    assert visitor.visited == ["var:x", "number:7", "assign"]

def test_top_down_visitor_breadth_first_order():
    class RecordingTopDownVisitor(TopDownVisitor):
        def __init__(self):
            self.visited = []
            super().__init__()

        def visit_assign(self, node: AstAssign, state):
            self.visited.append("assign")

        def visit_var(self, node: AstVar, state):
            self.visited.append(f"var:{node.var}")

        def visit_number(self, node: AstNumber, state):
            self.visited.append(f"number:{node.value}")

    visitor = RecordingTopDownVisitor()
    state = _make_state()

    lhs = AstVar(meta=None, var="x")
    rhs = AstNumber(meta=None, value=5)
    assign = AstAssign(meta=None, lhs=lhs, type_ann=None, rhs=rhs)

    visitor.run(assign, state)

    assert visitor.visited == ["assign", "var:x", "number:5"]


def test_visitor_default_handler_invoked():
    class DefaultingVisitor(Visitor):
        def __init__(self):
            self.default_hits = []
            super().__init__()

        def visit_default(self, node, state):
            self.default_hits.append(type(node))

        def visit_assign(self, node: AstAssign, state):
            pass

    visitor = DefaultingVisitor()
    state = _make_state()

    node = AstVar(meta=None, var="y")
    visitor.run(node, state)

    assert visitor.default_hits == [AstVar]


def test_visitor_stops_on_error():
    class ErroringVisitor(Visitor):
        def __init__(self):
            super().__init__()

        def visit_var(self, node: AstVar, state):
            state.err("boom", node)

        def visit_number(self, node: AstNumber, state):
            raise AssertionError("should not be reached")

    visitor = ErroringVisitor()
    state = _make_state()

    lhs = AstVar(meta=None, var="x")
    rhs = AstNumber(meta=None, value=9)
    assign = AstAssign(meta=None, lhs=lhs, type_ann=None, rhs=rhs)

    visitor.run(assign, state)

    assert state.errors == [("boom", lhs)]


def test_visitor_handler_exception_propagates():
    class ExplodingVisitor(Visitor):
        def visit_var(self, node: AstVar, state):
            raise RuntimeError("should fail")

    visitor = ExplodingVisitor()
    state = _make_state()

    node = AstVar(meta=None, var="z")

    with pytest.raises(RuntimeError, match="should fail"):
        visitor.run(node, state)

def test_transformer_replaces_child_nodes():
    class ZeroingTransformer(Transformer):
        def visit_number(self, node: AstNumber, state):
            if node.value == 42:
                return AstNumber(meta=node.meta, value=0)
            return None

    transformer = ZeroingTransformer()
    state = _make_state()

    lhs = AstVar(meta=None, var="answer")
    rhs = AstNumber(meta=None, value=42)
    assign = AstAssign(meta=None, lhs=lhs, type_ann=None, rhs=rhs)

    transformer.run(assign, state)

    assert isinstance(assign.rhs, AstNumber)
    assert assign.rhs is not rhs
    assert assign.rhs.value == 0


def test_transformer_deletes_nodes_from_lists():
    class DropPassesTransformer(Transformer):
        def visit_pass(self, node: AstPass, state):
            return Transformer.Delete

    transformer = DropPassesTransformer()
    state = _make_state()

    body = AstScopedBody(meta=None, stmts=[AstPass(meta=None), AstPass(meta=None)])

    transformer.run(body, state)

    assert body.stmts == []


def test_transformer_expands_nodes_in_lists():
    class ExpandPassTransformer(Transformer):
        def visit_pass(self, node: AstPass, state):
            first = AstPass(meta=node.meta)
            first.tag = "first"  # type: ignore[attr-defined]
            second = AstPass(meta=node.meta)
            second.tag = "second"  # type: ignore[attr-defined]
            return [first, second]

    transformer = ExpandPassTransformer()
    state = _make_state()

    original = AstPass(meta=None)
    body = AstScopedBody(meta=None, stmts=[original])

    transformer.run(body, state)

    assert len(body.stmts) == 2
    assert getattr(body.stmts[0], "tag") == "first"
    assert getattr(body.stmts[1], "tag") == "second"
    assert body.stmts[0] is not original
    assert body.stmts[1] is not original
