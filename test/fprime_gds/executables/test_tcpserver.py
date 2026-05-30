"""
Unit tests for fprime_gds.executables.tcpserver hardening.

Covers two fixes and the related UDP hardening:

  Fix #1 -- recv() must not busy-loop on a socket error. On any OSError the
            socket is broken; retrying recv() would spin the handler thread at
            100% CPU forever. recv() must return b"" after a bounded number of
            calls. socket.timeout, by contrast, must keep looping (intended).

  Fix #3 -- readData() must bound the client-declared payload length (a U32,
            up to ~4 GiB) so a malicious/garbled size cannot drive an unbounded
            read/allocation; must not raise struct.error on a short length
            prefix; and must drop (not silently truncate) a short payload. The
            recv() accumulator must also reassemble correctly across many
            partial chunks (the bytearray.extend path that replaced the O(n^2)
            "msg = msg + chunk").

  UDP     -- readHeader/readData/processNewPkt must tolerate runt datagrams and
            malformed headers without raising.

The handlers normally run inside socketserver, which connects and serves on
construction. To unit-test the parsing/recv methods in isolation we build a
bare instance with object.__new__(...) and inject a scripted fake request.

These tests follow the repo convention (unittest.TestCase, run under pytest)
and live at test/fprime_gds/executables/test_tcpserver.py.
"""

import errno
import socket
import struct
import threading
import unittest

from fprime_gds.executables.tcpserver import (
    ThreadedTCPRequestHandler,
    ThreadedUDPRequestHandler,
)


class FakeRequest:
    """A stand-in for the socket handed to a request handler.

    Scripted with a list of "actions", each of which is either:
      * a bytes object -> returned from the next recv() call, or
      * an Exception instance/class -> raised from the next recv() call.
    When the script is exhausted, recv() returns b"" (EOF), mirroring a
    closed socket. Every recv() call is counted so tests can assert that a
    broken socket is not polled repeatedly (the busy-loop regression guard)
    and that an oversized length is rejected without ever reading the payload.
    """

    def __init__(self, actions=None, max_calls=10_000):
        self._actions = list(actions or [])
        self.calls = 0
        self.recv_sizes = []
        self._max_calls = max_calls

    def recv(self, n):
        self.calls += 1
        self.recv_sizes.append(n)
        # Hard stop so a regression of the busy-loop fails fast instead of
        # hanging the whole test suite.
        if self.calls > self._max_calls:
            raise AssertionError(
                f"recv() called more than {self._max_calls} times -- "
                "likely an infinite busy-loop regression"
            )
        if not self._actions:
            return b""  # EOF
        action = self._actions.pop(0)
        if isinstance(action, BaseException) or (
            isinstance(action, type) and issubclass(action, BaseException)
        ):
            raise action
        return action


def make_tcp_handler(request):
    """Build a ThreadedTCPRequestHandler without running socketserver setup."""
    handler = object.__new__(ThreadedTCPRequestHandler)
    handler.request = request
    handler.name = b"TEST_CLIENT"
    return handler


def make_udp_handler():
    """Build a ThreadedUDPRequestHandler without running socketserver setup."""
    return object.__new__(ThreadedUDPRequestHandler)


class TestRecvBusyLoop(unittest.TestCase):
    """Fix #1: recv() must terminate on a socket error, not spin."""

    def test_econnreset_returns_empty_after_single_call(self):
        req = FakeRequest([OSError(errno.ECONNRESET, "reset")])
        handler = make_tcp_handler(req)
        result = handler.recv(13)
        self.assertEqual(result, b"")
        # The decisive assertion: the broken socket was polled exactly once.
        self.assertEqual(req.calls, 1)

    def test_other_oserror_returns_empty_after_single_call(self):
        for err in (errno.EPIPE, errno.EBADF, errno.ECONNABORTED):
            with self.subTest(errno=err):
                req = FakeRequest([OSError(err, "broken")])
                handler = make_tcp_handler(req)
                self.assertEqual(handler.recv(13), b"")
                self.assertEqual(req.calls, 1)

    def test_empty_read_eof_returns_empty(self):
        # A zero-byte read means the peer closed the connection cleanly.
        req = FakeRequest([b""])
        handler = make_tcp_handler(req)
        self.assertEqual(handler.recv(8), b"")

    def test_timeout_keeps_looping_then_succeeds(self):
        # socket.timeout must NOT be treated as a disconnect: recv() should
        # retry and ultimately return the full payload.
        req = FakeRequest([socket.timeout(), b"AB", socket.timeout(), b"CDE"])
        handler = make_tcp_handler(req)
        self.assertEqual(handler.recv(5), b"ABCDE")

    def test_recv_terminates_within_timeout_on_persistent_error(self):
        # Belt-and-suspenders: even if the call-count guard were removed, the
        # call must not hang. Run it on a worker thread and require completion.
        # A persistent OSError every call would be an infinite loop pre-fix.
        req = FakeRequest(
            [OSError(errno.ECONNRESET, "reset")] * 50_000, max_calls=10_000
        )
        handler = make_tcp_handler(req)
        done = threading.Event()
        out = {}

        def run():
            out["result"] = handler.recv(13)
            done.set()

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self.assertTrue(done.wait(timeout=5), "recv() did not return within 5s")
        self.assertEqual(out["result"], b"")


class TestRecvAccumulation(unittest.TestCase):
    """Fix #3 (accumulator): recv() reassembles correctly across chunks."""

    def test_reassembles_partial_chunks_in_order(self):
        req = FakeRequest([b"AB", b"CDE", b"FGHIJKLM"])
        handler = make_tcp_handler(req)
        self.assertEqual(handler.recv(13), b"ABCDEFGHIJKLM")

    def test_reassembles_many_small_chunks(self):
        # Exercises the bytearray.extend path with many appends; asserts exact
        # byte-for-byte reassembly (the correctness guarantee behind the O(n^2)
        # -> O(n) accumulator change).
        expected = bytes(range(256)) * 8  # 2048 bytes
        chunks = [expected[i : i + 3] for i in range(0, len(expected), 3)]
        req = FakeRequest(chunks)
        handler = make_tcp_handler(req)
        self.assertEqual(handler.recv(len(expected)), expected)

    def test_returns_bytes_type(self):
        req = FakeRequest([b"XYZ"])
        handler = make_tcp_handler(req)
        self.assertIsInstance(handler.recv(3), bytes)


class TestReadPayloadSize(unittest.TestCase):
    """Fix #3 (bound): the U32 length prefix is validated."""

    def test_accepts_size_at_limit(self):
        size = ThreadedTCPRequestHandler.MAX_PAYLOAD_SIZE
        req = FakeRequest([struct.pack(">I", size)])
        handler = make_tcp_handler(req)
        got_size, raw = handler._read_payload_size()
        self.assertEqual(got_size, size)
        self.assertEqual(raw, struct.pack(">I", size))

    def test_rejects_size_above_limit(self):
        size = ThreadedTCPRequestHandler.MAX_PAYLOAD_SIZE + 1
        req = FakeRequest([struct.pack(">I", size)])
        handler = make_tcp_handler(req)
        got_size, _ = handler._read_payload_size()
        self.assertIsNone(got_size)

    def test_rejects_max_u32(self):
        req = FakeRequest([struct.pack(">I", 0xFFFFFFFF)])
        handler = make_tcp_handler(req)
        got_size, _ = handler._read_payload_size()
        self.assertIsNone(got_size)

    def test_short_prefix_returns_none_without_struct_error(self):
        # Fewer than 4 bytes then EOF: must not raise struct.error.
        req = FakeRequest([b"\x00\x00"])
        handler = make_tcp_handler(req)
        try:
            got_size, _ = handler._read_payload_size()
        except struct.error:
            self.fail("_read_payload_size raised struct.error on short prefix")
        self.assertIsNone(got_size)


class TestReadDataTCP(unittest.TestCase):
    """Fix #3 (readData): bound, robustness, and the no-allocation property."""

    def test_gui_valid_payload(self):
        req = FakeRequest([struct.pack(">I", 4), b"PING"])
        handler = make_tcp_handler(req)
        self.assertEqual(handler.readData(b"A5A5 GUI "), struct.pack(">I", 4) + b"PING")

    def test_fsw_valid_payload(self):
        req = FakeRequest([b"DESC", struct.pack(">I", 3), b"CMD"])
        handler = make_tcp_handler(req)
        self.assertEqual(
            handler.readData(b"A5A5 FSW "), b"DESC" + struct.pack(">I", 3) + b"CMD"
        )

    def test_gui_oversized_size_is_rejected_without_reading_payload(self):
        # The key security property: reject on the length field alone; never
        # attempt the giant recv(size) that would allocate ~4 GiB.
        req = FakeRequest([struct.pack(">I", 0xFFFFFFFF)])
        handler = make_tcp_handler(req)
        self.assertEqual(handler.readData(b"A5A5 GUI "), b"")
        # Only the 4-byte length prefix was read; no payload recv attempted.
        self.assertEqual(req.calls, 1)
        self.assertNotIn(0xFFFFFFFF, req.recv_sizes)

    def test_gui_truncated_payload_is_dropped(self):
        # Declares 8 bytes, delivers 2 then EOF -> drop, do not return a runt.
        req = FakeRequest([struct.pack(">I", 8), b"AB"])
        handler = make_tcp_handler(req)
        self.assertEqual(handler.readData(b"A5A5 GUI "), b"")

    def test_fsw_truncated_descriptor_is_dropped(self):
        req = FakeRequest([b"DE"])  # short descriptor then EOF
        handler = make_tcp_handler(req)
        self.assertEqual(handler.readData(b"A5A5 FSW "), b"")

    def test_missing_destination_returns_empty(self):
        req = FakeRequest([])
        handler = make_tcp_handler(req)
        self.assertEqual(handler.readData(b"A5A5"), b"")

    def test_list_and_quit_headers_return_empty(self):
        for header in (b"List", b"Quit"):
            with self.subTest(header=header):
                handler = make_tcp_handler(FakeRequest([]))
                self.assertEqual(handler.readData(header), b"")

    def test_unknown_destination_raises_runtimeerror(self):
        # Preserves existing behavior for a genuinely unrecognized client.
        handler = make_tcp_handler(FakeRequest([]))
        with self.assertRaises(RuntimeError):
            handler.readData(b"A5A5 XXX ")


class TestUDPHardening(unittest.TestCase):
    """UDP datagram parsing must tolerate runt/malformed input."""

    def test_readheader_short_datagram(self):
        handler = make_udp_handler()
        self.assertEqual(handler.readHeader(b"A5A5"), (b"", b""))

    def test_readheader_full(self):
        handler = make_udp_handler()
        packet = b"A5A5 GUI " + struct.pack(">I", 3) + b"XYZ"
        header, rest = handler.readHeader(packet)
        self.assertEqual(header, b"A5A5 GUI ")
        self.assertEqual(rest, struct.pack(">I", 3) + b"XYZ")

    def test_readdata_runt_length_prefix(self):
        # Fewer than 4 bytes: must not raise struct.error.
        handler = make_udp_handler()
        try:
            self.assertEqual(handler.readData(b"A5A5 GUI ", b"\x00\x00"), b"")
        except struct.error:
            self.fail("UDP readData raised struct.error on runt datagram")

    def test_readdata_declared_size_exceeds_datagram(self):
        handler = make_udp_handler()
        packet = struct.pack(">I", 1000) + b"XYZ"  # claims 1000, has 3
        self.assertEqual(handler.readData(b"A5A5 GUI ", packet), b"")

    def test_readdata_valid(self):
        handler = make_udp_handler()
        packet = struct.pack(">I", 3) + b"XYZ"
        self.assertEqual(handler.readData(b"A5A5 GUI ", packet), struct.pack(">I", 3) + b"XYZ")

    def test_processnewpkt_malformed_header_does_not_raise(self):
        # A header with no space split into two parts must not raise ValueError
        # (which would kill the handler thread).
        handler = make_udp_handler()
        try:
            handler.processNewPkt(b"GARBAGE", b"")
        except ValueError:
            self.fail("processNewPkt raised ValueError on malformed header")


if __name__ == "__main__":
    unittest.main()
