import ast
from pathlib import Path
from fprime_gds.common.sequence.compiler import compile
def test_basic_seq():
    seq = \
"""
Ref.fileManager.RemoveFile("test", True)
Ref.fileManager.RemoveFile("test", False)
"""
    assert compile(ast.parse(seq), Path(__file__).parent / "RefTopologyDictionary.json") == 0

def test_basic_seq_kwargs():
    seq = \
"""
Ref.fileManager.RemoveFile("test", ignoreErrors=True)
"""
    assert compile(ast.parse(seq), Path(__file__).parent / "RefTopologyDictionary.json") == 0

def test_basic_seq_missing_arg():
    seq = \
"""
Ref.fileManager.RemoveFile("test")
"""
    assert compile(ast.parse(seq), Path(__file__).parent / "RefTopologyDictionary.json") == 1

def test_invalid_seq():
    seq = \
"""
"test"
"""
    assert compile(ast.parse(seq), Path(__file__).parent / "RefTopologyDictionary.json") == 1

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

def test_struct_arg_wrong_type():
    seq = \
"""
Ref.typeDemo.CHOICE_PAIR(Ref.ChoicePair(1, Ref.Choice.TWO))
"""
    assert compile(ast.parse(seq), Path(__file__).parent / "RefTopologyDictionary.json") == 1

def test_unknown_enum_const():
    seq = \
"""
Ref.typeDemo.CHOICE_PAIR(Ref.ChoicePair(Ref.Choice.FAIL, Ref.Choice.TWO))
"""
    assert compile(ast.parse(seq), Path(__file__).parent / "RefTopologyDictionary.json") == 1

def test_array_arg():
    seq = \
"""
Ref.typeDemo.CHOICES(Ref.ManyChoices(Ref.Choice.TWO, Ref.Choice.RED))
"""
    assert compile(ast.parse(seq), Path(__file__).parent / "RefTopologyDictionary.json") == 0

def test_array_kwarg():
    seq = \
"""
Ref.typeDemo.CHOICES(Ref.ManyChoices(e0=Ref.Choice.TWO, e1=Ref.Choice.RED))
"""
    assert compile(ast.parse(seq), Path(__file__).parent / "RefTopologyDictionary.json") == 0

def test_fail_call_cmd():
    seq = \
"""
Ref.typeDemo.CHOICES(Ref.typeDemo.CHOICES(Ref.ManyChoices(Ref.Choice.TWO, Ref.Choice.RED)))
"""
    assert compile(ast.parse(seq), Path(__file__).parent / "RefTopologyDictionary.json") == 0