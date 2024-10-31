import ast
from pathlib import Path
from fprime_gds.common.sequence.compiler import compile


def run_seq(seq: str, should_succeed: bool):
    assert compile(
        ast.parse(seq), Path(__file__).parent / "RefTopologyDictionary.json"
    ) == (0 if should_succeed else 1)


def test_basic_seq():
    seq = """
Ref.fileManager.RemoveFile("test", True)
Ref.fileManager.RemoveFile("test", False)
"""
    run_seq(seq, True)


def test_basic_seq_kwargs():
    seq = """
Ref.fileManager.RemoveFile("test", ignoreErrors=True)
"""
    run_seq(seq, True)


def test_basic_seq_missing_arg():
    seq = """
Ref.fileManager.RemoveFile("test")
"""
    run_seq(seq, False)


def test_invalid_seq():
    seq = """
"test"
"""
    run_seq(seq, False)


def test_enum_arg():
    seq = """
Ref.typeDemo.CHOICE(Ref.Choice.ONE)
"""
    run_seq(seq, True)


def test_struct_arg():
    seq = """
Ref.typeDemo.CHOICE_PAIR(Ref.ChoicePair(Ref.Choice.ONE, Ref.Choice.TWO))
"""
    run_seq(seq, True)


def test_struct_arg_wrong_type():
    seq = """
Ref.typeDemo.CHOICE_PAIR(Ref.ChoicePair(1, Ref.Choice.TWO))
"""
    run_seq(seq, False)


def test_unknown_enum_const():
    seq = """
Ref.typeDemo.CHOICE_PAIR(Ref.ChoicePair(Ref.Choice.FAIL, Ref.Choice.TWO))
"""
    run_seq(seq, False)


def test_array_arg():
    seq = """
Ref.typeDemo.CHOICES(Ref.ManyChoices(Ref.Choice.TWO, Ref.Choice.RED))
"""
    run_seq(seq, True)


def test_array_kwarg():
    seq = """
Ref.typeDemo.CHOICES(Ref.ManyChoices(e0=Ref.Choice.TWO, e1=Ref.Choice.RED))
"""
    run_seq(seq, True)


def test_fail_call_cmd():
    seq = """
Ref.typeDemo.CHOICES(Ref.typeDemo.CHOICES(Ref.ManyChoices(Ref.Choice.TWO, Ref.Choice.RED)))
"""
    run_seq(seq, False)


def test_rel_sleep():
    seq = """
seq.sleep(Time(55,55,55,55))
"""
    run_seq(seq, True)


def test_abs_sleep():
    seq = """
seq.sleep_until(Time(0,1,2,3))
"""
    run_seq(seq, True)


def test_seq_dir_bad_args():
    seq = """
seq.sleep_until(1)
"""
    run_seq(seq, False)


def test_bad_seq_directive():
    seq = """
seq.fail()
"""
    run_seq(seq, False)
