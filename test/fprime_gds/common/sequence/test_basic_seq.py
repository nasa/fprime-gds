import ast
from pathlib import Path
from fprime_gds.common.sequence.compiler import compile
def test_basic_seq():
    seq = \
"""
Ref.fileManager.RemoveFile("test", False)
"""
    assert compile(ast.parse(seq), Path(__file__).parent / "RefTopologyDictionary.json") == 0

def test_enum_arg():
    seq = \
"""
Ref.typeDemo.CHOICE(Ref.Choice.ONE)
"""
    assert compile(ast.parse(seq), Path(__file__).parent / "RefTopologyDictionary.json") == 0

def test_struct_arg():
    seq = \
"""
Ref.typeDemo.CHOICE_PAIR(Ref.ChoicePair(Ref.Choice.ONE, Ref.Choice.TWO))
"""
    assert compile(ast.parse(seq), Path(__file__).parent / "RefTopologyDictionary.json") == 0