"""
@brief Class to log raw binary input and output as well as telemetry and events.

This logger batches text writes and binary writes through an internal byte
buffer per file and a background flusher thread. The previous implementation
called ``file.flush()`` on every single sample, which serialized the data
pipeline against the disk on high-rate downlinks (e.g. tens-of-MB/s streams
made up of small samples). With batching the per-sample cost is reduced to
an in-memory ``write`` and the flusher amortizes the disk syscalls.

The logger also supports a channel filter so that very high-rate channels
(for example, image- or frame-multiplex telemetry) can be excluded from the
on-disk channel log entirely.
"""

import fnmatch
import logging
import os
import threading

import fprime_gds.common.handlers
from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.data_types.cmd_data import CmdData
from fprime_gds.common.data_types.event_data import EventData
from fprime_gds.common.data_types.pkt_data import PktData


logger = logging.getLogger("fprime_gds.common.logger.data_logger")


DEFAULT_LOG_BATCH_MS = 100
"""Default upper bound on the time a buffered byte may sit before flushing."""

DEFAULT_LOG_BATCH_BYTES = 1 << 20  # 1 MiB
"""Default upper bound on the number of buffered bytes before flushing."""

DEFAULT_RETRY_MAX_BYTES = 16 << 20  # 16 MiB
"""Upper bound on the per-file retry buffer when disk writes are failing.

Once the buffered (still-unwritten) data exceeds this size we drop the
newest bytes and keep retrying the oldest chunk. Bounding the buffer
prevents an unbounded memory leak when the disk is permanently wedged."""


class _BufferedFile:
    """Per-file buffer used by :class:`DataLogger`.

    Writes are appended to an in-memory bytearray under the lock and flushed
    out either when the buffer crosses ``batch_bytes`` or when the
    :class:`DataLogger` flusher thread fires (every ``batch_ms``).
    """

    def __init__(self, path, mode, batch_bytes, retry_max_bytes=DEFAULT_RETRY_MAX_BYTES):
        self.path = path
        self._fh = open(path, mode)  # noqa: SIM115 - intentional, closed in close()
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._batch_bytes = batch_bytes
        self._retry_max_bytes = retry_max_bytes

    def write(self, data):
        """Append text or bytes to the buffer; flush if over threshold."""
        if isinstance(data, str):
            data = data.encode("utf-8", errors="replace")
        flush_now = False
        with self._lock:
            self._buf.extend(data)
            if len(self._buf) >= self._batch_bytes:
                flush_now = True
        if flush_now:
            self.flush()

    def flush(self):
        """Drain the in-memory buffer to the underlying file.

        The buffer is snapshotted under the lock, the I/O is performed
        without the lock held (so new ``write`` callers do not block on
        a slow disk), and on success the snapshotted bytes are removed
        from the front of the buffer. On failure the buffer is left
        intact so the flusher thread genuinely retries on its next
        tick. To bound memory under a permanently-wedged disk, the
        buffer is dropped once it exceeds ``_retry_max_bytes``; this is
        logged at WARNING level.
        """
        with self._lock:
            if not self._buf:
                return
            chunk_len = len(self._buf)
            chunk = bytes(self._buf)
        is_binary = "b" in self._fh.mode
        try:
            self._fh.write(chunk if is_binary else chunk.decode("utf-8", errors="replace"))
            self._fh.flush()
        except Exception:
            # Disk write failed; keep the data in the buffer so the
            # next flush tick (or call site) can try again. Don't take
            # down the data pipeline.
            logger.exception("DataLogger: deferred flush to %s", self.path)
            with self._lock:
                if len(self._buf) > self._retry_max_bytes:
                    dropped = len(self._buf) - chunk_len
                    # Drop everything that accumulated since the failed
                    # chunk (newer data is less useful than the older
                    # in-flight chunk we are still trying to write) and
                    # surface the loss.
                    self._buf = bytearray(chunk)
                    logger.warning(
                        "DataLogger: dropping %d bytes from %s (disk wedged; "
                        "retry buffer cap %d bytes reached)",
                        dropped, self.path, self._retry_max_bytes,
                    )
            return
        # Success -- discard the bytes we just wrote.
        with self._lock:
            del self._buf[:chunk_len]

    def close(self):
        try:
            self.flush()
        finally:
            try:
                self._fh.close()
            except Exception:
                pass


class DataLogger(fprime_gds.common.handlers.DataHandler):
    """Persist FSW data streams to on-disk log files with batched writes.

    Args:
        logdir: directory to write log files into.
        verbose: forwarded to ``get_str(verbose=...)`` on data items.
        csv: forwarded to ``get_str(csv=...)`` on data items.
        prefix: filename prefix (kept for backwards compatibility).
        batch_ms: maximum time (ms) a buffered byte may sit before being
            flushed to disk. ``0`` disables the flusher thread (writes still
            flush when ``batch_bytes`` is exceeded).
        batch_bytes: maximum number of bytes that may accumulate in any one
            file's buffer before that file is flushed immediately.
        disable_channel_patterns: iterable of glob patterns matched against
            the fully-qualified channel name. Matching channels are dropped
            entirely (not written to ``channel.log``).
    """

    def __init__(
        self,
        logdir,
        verbose=False,
        csv=False,
        prefix="",
        batch_ms=DEFAULT_LOG_BATCH_MS,
        batch_bytes=DEFAULT_LOG_BATCH_BYTES,
        disable_channel_patterns=None,
    ):

        self.logdir = logdir

        self.recv_file = f"{prefix}recv.bin"
        self.send_file = f"{prefix}sent.bin"
        self.telem_file = f"{prefix}channel.log"
        self.event_file = f"{prefix}event.log"
        self.command_file = f"{prefix}command.log"

        self.verbose = verbose
        self.csv = csv

        self._files = [
            _BufferedFile(os.path.join(logdir, self.recv_file), "ab", batch_bytes),
            _BufferedFile(os.path.join(logdir, self.send_file), "ab", batch_bytes),
            _BufferedFile(os.path.join(logdir, self.telem_file), "a", batch_bytes),
            _BufferedFile(os.path.join(logdir, self.event_file), "a", batch_bytes),
            _BufferedFile(os.path.join(logdir, self.command_file), "a", batch_bytes),
        ]
        self.f_r, self.f_s, self.f_telem, self.f_event, self.f_command = self._files

        self._disable_patterns = tuple(disable_channel_patterns or ())
        # Cache results per channel id to keep the hot path branch-free.
        self._channel_enabled_cache = {}

        self._stop_event = threading.Event()
        self._flusher = None
        if batch_ms > 0:
            self._flusher = threading.Thread(
                target=self._flush_loop,
                args=(batch_ms / 1000.0,),
                name="fprime-gds-data-logger-flusher",
                daemon=True,
            )
            self._flusher.start()

    # ------------------------------------------------------------------
    # Flusher thread
    # ------------------------------------------------------------------
    def _flush_loop(self, interval_s):
        while not self._stop_event.wait(interval_s):
            for f in self._files:
                f.flush()

    def close(self):
        """Stop the flusher thread and drain all files."""
        self._stop_event.set()
        if self._flusher is not None:
            self._flusher.join(timeout=2.0)
            self._flusher = None
        for f in self._files:
            f.close()

    def __del__(self):
        # Best-effort: avoid crashing in interpreter shutdown.
        try:
            self.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Channel filtering
    # ------------------------------------------------------------------
    def _channel_enabled(self, ch_data):
        """Return ``True`` if the channel should be persisted to disk."""
        if not self._disable_patterns:
            return True
        ch_id = getattr(ch_data, "id", None)
        cached = self._channel_enabled_cache.get(ch_id)
        if cached is not None:
            return cached
        template = getattr(ch_data, "template", None)
        name = template.get_full_name() if template is not None else None
        enabled = True
        if name is not None:
            for pattern in self._disable_patterns:
                if fnmatch.fnmatchcase(name, pattern):
                    enabled = False
                    break
        if ch_id is not None:
            self._channel_enabled_cache[ch_id] = enabled
        return enabled

    # ------------------------------------------------------------------
    # DataHandler API
    # ------------------------------------------------------------------
    def data_callback(self, data, sender=None):
        if isinstance(data, ChData):
            if not self._channel_enabled(data):
                return
            self.f_telem.write(data.get_str(verbose=self.verbose, csv=self.csv) + "\n")
            return

        if isinstance(data, PktData):
            self.f_telem.write(data.get_str(verbose=self.verbose, csv=self.csv) + "\n")
            return

        if isinstance(data, EventData):
            self.f_event.write(data.get_str(verbose=self.verbose, csv=self.csv) + "\n")
            return

        if isinstance(data, CmdData):
            self.f_command.write(data.get_str(verbose=self.verbose, csv=self.csv) + "\n")
            return

        if isinstance(data, (bytes, bytearray)):
            self.on_recv(data)

    def send(self, data, dest):
        """Send callback for the encoder.

        Args:
            data: binary data packet
            dest: destination identifier (unused; kept for API compatibility)
        """
        self.f_s.write(data)

    def on_recv(self, data):
        """Data was received on the socket server.

        Args:
            data: binary data that was received
        """
        self.f_r.write(data)
