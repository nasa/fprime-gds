import ast
from pathlib import Path
from fprime_gds.common.sequence.compiler import compile


def run_seq(seq: str, should_succeed: bool):
    result = compile(
        ast.parse(seq), Path(__file__).parent / "RefTopologyDictionary.json"
    )
    if should_succeed:
        assert result is not None
    else:
        assert result is None


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


def test_wrong_enum_arg():
    seq = """
Ref.typeDemo.CHOICE(Fw.Wait.WAIT)
"""
    run_seq(seq, False)


def test_struct_arg():
    seq = """
Ref.typeDemo.CHOICE_PAIR(Ref.ChoicePair(Ref.Choice.ONE, Ref.Choice.TWO))
"""
    run_seq(seq, True)


def test_wrong_struct_arg():
    seq = """
Ref.typeDemo.CHOICE_PAIR(Ref.SignalPair(0.0, 0.0))
"""
    run_seq(seq, False)


def test_struct_ctor_arg_wrong_type():
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
sleep_rel(Time(0, 55,55,55))
"""
    run_seq(seq, True)


def test_abs_sleep():
    seq = """
sleep_abs(Time(0,1,2,3))
"""
    run_seq(seq, True)


def test_timebase_fail():
    seq = """
sleep_abs(Time(1231,1,2,3))
"""
    run_seq(seq, False)


def test_int_out_of_bounds():
    seq = """
sleep_abs(Time(0,1,2,123123123123123123))
"""
    run_seq(seq, False)


def test_seq_dir_bad_args():
    seq = """
sleep_abs(1)
"""
    run_seq(seq, False)


def test_bad_seq_directive():
    seq = """
fail()
"""
    run_seq(seq, False)


def test_empty_seq():
    run_seq("", False)


def test_two_sleeps_fail_1():
    seq = """
sleep_abs(Time(0,1,2,3))
sleep_abs(Time(0,1,2,3))
"""
    run_seq(seq, False)


def test_two_sleeps_fail_2():
    seq = """
sleep_abs(Time(0,1,2,3))
sleep_rel(Time(0,1,2,3))
"""
    run_seq(seq, False)
