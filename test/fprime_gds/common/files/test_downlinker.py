"""Tests for FileDownlinker.sanitize() containment.

Every case asserts the sanitized name stays inside the downlink directory
under BOTH posixpath and ntpath, so the guarantee does not depend on os.sep.
"""
import ntpath
import posixpath

import pytest

from fprime_gds.common.files.downlinker import FileDownlinker

CASES = [
    ("report.bin", "report.bin"),
    ("sub/dir/file.bin", "file.bin"),
    ("back\\slash\\file.bin", "file.bin"),
    ("../../evil.txt", "evil.txt"),
    ("../../../Users/Public/evil.txt", "evil.txt"),
    ("a/../../b", "b"),
    ("....//....//x", "x"),
    ("/etc/passwd", "passwd"),
    ("C:/Windows/Temp/evil.txt", "evil.txt"),
    ("C:evil.txt", "C_evil.txt"),
    ("C:\\", "C_"),
    ("\\\\server\\share\\x", "x"),
    ("notes.txt:hidden", "notes.txt_hidden"),
    ("", "_unnamed_downlink"),
    (".", "_unnamed_downlink"),
    ("..", "_unnamed_downlink"),
    ("...", "_unnamed_downlink"),
    ("/", "_unnamed_downlink"),
    ("///", "_unnamed_downlink"),
]


@pytest.mark.parametrize("dest_path,expected", CASES)
def test_sanitize_returns_bare_filename(dest_path, expected):
    assert FileDownlinker.sanitize(dest_path) == expected


@pytest.mark.parametrize("dest_path,_expected", CASES)
def test_sanitize_result_stays_in_downlink_directory(dest_path, _expected):
    name = FileDownlinker.sanitize(dest_path)
    assert ntpath.normpath(ntpath.join(r"C:\gds\dl", name)).startswith("C:\\gds\\dl\\")
    assert posixpath.normpath(posixpath.join("/gds/dl", name)).startswith("/gds/dl/")
