"""Unit tests for :mod:`fprime_gds.flask.logs`.

The interesting behaviour is the incremental tail support on
``LogFile.get``: a polling client should be able to pass back the byte
offset returned by the previous response and only receive the bytes
written since then.  Without this, a 1-second poll on a multi-megabyte
log redownloads the whole file on every tick.
"""

from __future__ import annotations

import os

import flask
import pytest

from fprime_gds.flask.logs import LogFile, LogList


@pytest.fixture
def app():
    """Minimal Flask app providing a request context for ``reqparse``."""
    application = flask.Flask(__name__)
    return application


def _make_log(tmp_path, name: str, contents: str) -> str:
    path = tmp_path / name
    path.write_text(contents)
    return str(tmp_path)


def test_loglist_returns_only_dot_log_files(tmp_path):
    (tmp_path / "channel.log").write_text("a")
    (tmp_path / "event.log").write_text("b")
    (tmp_path / "notes.txt").write_text("ignore me")
    resource = LogList(str(tmp_path))
    result = resource.get()
    assert set(result["logs"]) == {"channel.log", "event.log"}


def test_logfile_full_read_when_no_offset_param(app, tmp_path):
    logdir = _make_log(tmp_path, "channel.log", "hello world\n")
    resource = LogFile(logdir)
    with app.test_request_context("/logdata/channel.log"):
        result = resource.get("channel.log")
    # Legacy shape: just ``{name: body}``, no offset/size fields.
    assert result == {"channel.log": "hello world\n"}


def test_logfile_incremental_tail_returns_only_new_bytes(app, tmp_path):
    path = tmp_path / "channel.log"
    path.write_text("first chunk\n")
    resource = LogFile(str(tmp_path))

    # First poll with offset=0 returns the full current contents.
    with app.test_request_context("/logdata/channel.log?offset=0"):
        first = resource.get("channel.log")
    assert first["channel.log"] == "first chunk\n"
    assert first["offset"] == len("first chunk\n")
    assert first["size"] == len("first chunk\n")

    # Append more data, then poll again with the previously returned
    # offset.  Should only get the new tail back.
    with open(path, "a") as fh:
        fh.write("second chunk\n")
    with app.test_request_context(
        f"/logdata/channel.log?offset={first['offset']}"
    ):
        second = resource.get("channel.log")
    assert second["channel.log"] == "second chunk\n"
    assert second["offset"] == len("first chunk\nsecond chunk\n")


def test_logfile_offset_at_eof_returns_empty_delta(app, tmp_path):
    path = tmp_path / "channel.log"
    path.write_text("done\n")
    resource = LogFile(str(tmp_path))
    size = os.path.getsize(path)
    with app.test_request_context(f"/logdata/channel.log?offset={size}"):
        result = resource.get("channel.log")
    assert result["channel.log"] == ""
    assert result["offset"] == size
    assert result["size"] == size


def test_logfile_truncation_resets_offset_to_zero(app, tmp_path):
    path = tmp_path / "channel.log"
    path.write_text("aaaaaaaaaa")  # 10 bytes
    resource = LogFile(str(tmp_path))

    # Client claims to have read past current EOF (file rotated).
    with app.test_request_context("/logdata/channel.log?offset=999"):
        result = resource.get("channel.log")
    # The whole current file comes back; offset/size reflect the actual
    # current size, not the bogus client-supplied offset.
    assert result["channel.log"] == "aaaaaaaaaa"
    assert result["offset"] == 10
    assert result["size"] == 10


def test_logfile_negative_offset_treated_as_zero(app, tmp_path):
    path = tmp_path / "channel.log"
    path.write_text("payload")
    resource = LogFile(str(tmp_path))
    with app.test_request_context("/logdata/channel.log?offset=-5"):
        result = resource.get("channel.log")
    assert result["channel.log"] == "payload"
    assert result["offset"] == len("payload")
    assert result["size"] == len("payload")


def test_logfile_missing_file_returns_empty_string(app, tmp_path):
    resource = LogFile(str(tmp_path))
    with app.test_request_context("/logdata/does-not-exist.log?offset=0"):
        result = resource.get("does-not-exist.log")
    assert result == ""


def test_logfile_path_traversal_rejected(app, tmp_path):
    (tmp_path / "channel.log").write_text("safe")
    # Create a sibling directory that contains a file we should not be
    # able to escape into via the ``name`` arg.
    outside = tmp_path.parent / "outside.log"
    outside.write_text("unsafe")
    resource = LogFile(str(tmp_path))
    # ``..`` is collapsed to ``_`` by the sanitiser, so the resulting
    # path lookup misses inside the log dir and we return "".
    with app.test_request_context("/logdata/..%2Foutside.log"):
        result = resource.get("../outside.log")
    assert result == ""
