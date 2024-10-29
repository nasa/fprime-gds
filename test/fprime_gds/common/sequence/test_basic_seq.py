import ast
from pathlib import Path
from fprime_gds.common.sequence.compiler import compile
def test_basic_seq():
    seq = \
"""
Ref.fileManager.RemoveFile(Ref.MyEnum.TEST, arg=Ref.MyType(asdf))
"""
    assert compile(ast.parse(seq), Path(__file__).parent / "RefTopologyDictionary.json") == 0
