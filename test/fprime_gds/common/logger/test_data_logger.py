"""Tests for fprime_gds.common.logger.data_logger.

Covers:
* Batched writes (no per-sample fsync).
* Per-channel glob filtering of channel.log.
* _BufferedFile failure semantics:
    - I/O failure keeps the snapshotted bytes in the buffer (no data loss).
    - Subsequent successful flush drains everything.
    - Retry cap drops the *newest* bytes (keeping the oldest in-flight chunk)
      when the disk is wedged and the buffer would grow without bound.
"""

import os
import tempfile
import time
from unittest.mock import MagicMock

import pytest

from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.logger.data_logger import (
    DataLogger,
    DEFAULT_RETRY_MAX_BYTES,
    _BufferedFile,
)


def _make_ch(name, ch_id, val):
    tmpl = MagicMock()
    tmpl.get_full_name.return_value = name
    tmpl.get_id.return_value = ch_id
    return ChData(MagicMock(val=val), MagicMock(seconds=0, useconds=0), tmpl)


def test_channel_glob_filter_drops_matching_channel(tmp_path):
    dl = DataLogger(
        str(tmp_path),
        batch_ms=50,
        batch_bytes=1024,
        disable_channel_patterns=["*.RateGroup*"],
    )
    dl.data_callback(_make_ch("stub.RateGroup1Foo", 100, 1))
    dl.data_callback(_make_ch("app.Something", 101, 2))
    time.sleep(0.2)
    dl.close()
    content = (tmp_path / "channel.log").read_text()
    assert "RateGroup" not in content
    assert "app.Something" in content


def test_buffered_file_write_failure_preserves_buffer(tmp_path):
    bf = _BufferedFile(str(tmp_path / "t.log"), "a", batch_bytes=1024)
    bf.write("hello ")
    bf.write("world\n")
    expected = b"hello world\n"

    # Force the next disk write to raise.
    orig_write = bf._fh.write
    bf._fh.write = MagicMock(side_effect=IOError("wedged"))

    bf.flush()  # should not raise, should keep the data in the buffer
    assert bytes(bf._buf) == expected, "buffer must retain failed-write data"

    # Now let the disk recover; the next flush should drain everything.
    bf._fh.write = orig_write
    bf.flush()
    assert len(bf._buf) == 0
    assert (tmp_path / "t.log").read_text() == "hello world\n"


def test_buffered_file_retry_cap_drops_newest_bytes(tmp_path):
    cap = 64
    bf = _BufferedFile(
        str(tmp_path / "t.log"), "a", batch_bytes=10_000, retry_max_bytes=cap,
    )

    def writer_then_fail(_payload):
        # Simulate new writes arriving while the disk is mid-flush; the
        # buffer must grow past the retry cap so the cap path executes.
        if len(bf._buf) < 200:
            bf._buf.extend(b"X" * 100)
        raise IOError("wedged")

    bf._fh.write = writer_then_fail
    bf.write("A" * 50)
    bf.flush()
    # The original snapshotted chunk (50 bytes) is kept; the newer 100 bytes
    # added during the failed write are dropped.
    assert len(bf._buf) == 50


def test_default_retry_max_bytes_constant_is_sane():
    assert DEFAULT_RETRY_MAX_BYTES > 0
    # Should be substantially larger than a single batch threshold so a
    # transient wedged disk doesn't drop data immediately.
    assert DEFAULT_RETRY_MAX_BYTES >= (1 << 20)


def test_concurrent_flush_does_not_double_write_or_lose_data(tmp_path):
    """Two threads calling flush() simultaneously must not double-write
    overlapping buffer ranges nor drop data due to double-delete.

    Regression test for the race where flush() snapshots under _lock,
    releases _lock for I/O, and another flush() can snapshot the same
    bytes before the first one deletes them.
    """
    import threading
    bf = _BufferedFile(str(tmp_path / "race.log"), "a", batch_bytes=10_000_000)

    # Slow the I/O down so the second flusher reliably overlaps with
    # the first one. We deliberately use a sleep here -- the bug only
    # appears when the I/O is slow enough that another thread's flush
    # call interleaves between the snapshot and the delete.
    real_write = bf._fh.write
    def slow_write(payload):
        time.sleep(0.05)
        real_write(payload)
    bf._fh.write = slow_write

    # Fill the buffer with deterministic content we can audit.
    payload = "".join(f"line-{i:04d}\n" for i in range(200))
    bf.write(payload)
    expected_bytes = payload.encode()

    # Launch many concurrent flushes; without the flush lock the file
    # will contain duplicated ranges and the buffer will be missing data.
    errors = []
    def flusher():
        try:
            bf.flush()
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(exc)
    threads = [threading.Thread(target=flusher) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    bf._fh.flush = lambda: None  # already drained above; avoid re-flush
    bf.close()

    assert errors == [], f"flush raised: {errors}"
    # The file should contain *exactly* the payload, once -- no
    # duplicated lines and no missing lines.
    on_disk = (tmp_path / "race.log").read_bytes()
    assert on_disk == expected_bytes, (
        f"file content corrupted: len(on_disk)={len(on_disk)}, "
        f"len(expected)={len(expected_bytes)}"
    )


def test_close_drains_buffer_even_when_flusher_is_active(tmp_path):
    """Calling close() must always result in a fully drained buffer,
    even if the background flusher thread happens to be running.
    """
    dl = DataLogger(
        str(tmp_path),
        batch_ms=1,   # very aggressive flusher
        batch_bytes=10_000_000,
    )
    # Inject some data into the channel.log file
    dl.f_telem.write("close-drain-test\n")
    # close() should drain everything no matter what the flusher is doing
    dl.close()
    content = (tmp_path / "channel.log").read_text()
    assert "close-drain-test" in content


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
