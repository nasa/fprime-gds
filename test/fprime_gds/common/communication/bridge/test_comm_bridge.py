"""Tests for the fprime-comm-bridge

Unit tests cover the packaged no-op framer/deframer. Integration tests flow data through
the full bridge: a socat-provided PTY pair stands in for a UART endpoint on one side, and
UDP sockets stand in for the ground system intake/outlet on the other.
"""

import logging
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from argparse import Namespace
from pathlib import Path

import pytest

from fprime_gds.common.communication.framing import FpFramerDeframer
from fprime_gds.executables.cli import DictionaryParser
from fprime_gds.executables.comm_bridge import OptionalDictionaryParser
from fprime_gds.common.communication.bridge.bridge import MAXIMUM_PENDING_SIZE, UdpBridge
from fprime_gds.common.communication.bridge.framing import NoOpFramerDeframer
from fprime_gds.common.communication.bridge.udp import UdpLinks

SOCAT = shutil.which("socat")
TIMEOUT = 10.0


class TestNoOpFramerDeframer:
    """Unit tests for the no-op framer/deframer"""

    def test_frame_passthrough(self):
        framer = NoOpFramerDeframer()
        assert framer.frame(b"hello") == b"hello"
        assert framer.frame(b"") == b""

    def test_deframe_passthrough(self):
        framer = NoOpFramerDeframer()
        packet, leftover, discarded = framer.deframe(b"hello")
        assert packet == b"hello"
        assert leftover == b""
        assert discarded == b""

    def test_deframe_empty(self):
        framer = NoOpFramerDeframer()
        packet, leftover, discarded = framer.deframe(b"")
        assert packet is None
        assert leftover == b""
        assert discarded == b""

    def test_deframe_all(self):
        framer = NoOpFramerDeframer()
        packets, leftover, discarded = framer.deframe_all(b"hello", no_copy=False)
        assert packets == [b"hello"]
        assert leftover == b""
        assert discarded == b""


def wait_for_line(lines, needle, timeout=TIMEOUT):
    """Wait until a line containing `needle` appears in the growing `lines` list"""
    end = time.time() + timeout
    while time.time() < end:
        if any(needle in line for line in lines):
            return True
        time.sleep(0.05)
    return False


def read_available(fd, minimum=1, timeout=TIMEOUT):
    """Read at least `minimum` bytes from a non-blocking fd within timeout"""
    end = time.time() + timeout
    data = b""
    while time.time() < end and len(data) < minimum:
        try:
            data += os.read(fd, 4096)
        except BlockingIOError:
            time.sleep(0.05)
    return data


@pytest.fixture
def pty_pair(tmp_path):
    """Create a linked PTY pair using socat"""
    link_a = tmp_path / "ttyA"
    link_b = tmp_path / "ttyB"
    process = subprocess.Popen(
        [
            SOCAT,
            f"pty,raw,echo=0,link={link_a}",
            f"pty,raw,echo=0,link={link_b}",
        ]
    )
    end = time.time() + TIMEOUT
    while time.time() < end and not (link_a.exists() and link_b.exists()):
        time.sleep(0.05)
    assert link_a.exists() and link_b.exists(), "socat failed to create PTY pair"
    yield link_a, link_b
    process.send_signal(signal.SIGTERM)
    process.wait(timeout=TIMEOUT)


def start_bridge(uart_device: Path, tm_port: int, tc_port: int, framing: str):
    """Start the fprime-comm-bridge process"""
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "fprime_gds.executables.comm_bridge",
            "--communication-selection",
            "uart",
            "--uart-device",
            str(uart_device),
            "--uart-skip-port-check",
            "--framing-selection",
            framing,
            "--tm-port",
            str(tm_port),
            "--tc-port",
            str(tc_port),
        ],
        stderr=subprocess.PIPE,
        text=True,
    )


@pytest.fixture(params=["no-op", "fprime"])
def bridge_setup(request, pty_pair, unused_udp_ports):
    """Run the bridge against one PTY end, exposing the peer PTY and UDP sockets"""
    link_a, link_b = pty_pair
    tm_port, tc_port = unused_udp_ports

    tm_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tm_socket.bind(("127.0.0.1", tm_port))
    tm_socket.settimeout(TIMEOUT)
    tc_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    bridge = start_bridge(link_a, tm_port, tc_port, request.param)
    stderr_lines = []
    reader = threading.Thread(
        target=lambda: stderr_lines.extend(iter(bridge.stderr.readline, "")),
        daemon=True,
    )
    reader.start()
    peer_fd = os.open(link_b, os.O_RDWR | os.O_NONBLOCK)
    # Wait for the bridge to report that both data pumps are running
    assert wait_for_line(stderr_lines, "Bridge up"), "Bridge failed to start"
    assert bridge.poll() is None, "Bridge process exited prematurely"
    yield request.param, peer_fd, tm_socket, tc_socket, tc_port, stderr_lines
    bridge.send_signal(signal.SIGINT)
    bridge.wait(timeout=TIMEOUT)
    reader.join(timeout=TIMEOUT)
    os.close(peer_fd)
    tm_socket.close()
    tc_socket.close()


@pytest.fixture
def unused_udp_ports():
    """Reserve two distinct UDP port numbers"""
    sockets = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(2)]
    for reservation in sockets:
        reservation.bind(("127.0.0.1", 0))
    ports = [reservation.getsockname()[1] for reservation in sockets]
    for reservation in sockets:
        reservation.close()
    return ports


@pytest.mark.skipif(SOCAT is None, reason="socat is not available")
class TestBridgeFlow:
    """Integration tests flowing data through the bridge in both directions"""

    @staticmethod
    def assert_no_more_datagrams(tm_socket):
        """Assert no further datagram arrives within a short window"""
        tm_socket.settimeout(0.5)
        try:
            with pytest.raises(socket.timeout):
                tm_socket.recvfrom(65507)
        finally:
            tm_socket.settimeout(TIMEOUT)

    def test_boundary_warning(self, bridge_setup):
        """The stream-adapter boundary warning must fire for no-op framing only"""
        framing, _, _, _, _, stderr_lines = bridge_setup
        # main() emits the boundary warning before the "Bridge up" line the fixture
        # waits on, so the absence check below is race-free
        warned = any("cannot preserve" in line for line in stderr_lines)
        assert warned == (framing == "no-op")

    def test_uart_to_udp(self, bridge_setup):
        """Endpoint -> bridge -> UDP intake"""
        framing, peer_fd, tm_socket, _, _, _ = bridge_setup
        payload = b"telemetry-packet-payload"
        wire_data = (
            payload if framing == "no-op" else FpFramerDeframer().frame(payload)
        )
        os.write(peer_fd, wire_data)
        datagram, _ = tm_socket.recvfrom(65507)
        assert datagram == payload
        self.assert_no_more_datagrams(tm_socket)

    def test_uart_to_udp_split_frame(self, bridge_setup):
        """A frame split across adapter reads must be reassembled into one packet"""
        framing, peer_fd, tm_socket, _, _, _ = bridge_setup
        if framing != "fprime":
            pytest.skip("reassembly across reads requires a boundary-recovering framer")
        payload = b"telemetry-packet-payload"
        wire_data = FpFramerDeframer().frame(payload)
        split = len(wire_data) // 2
        os.write(peer_fd, wire_data[:split])
        time.sleep(0.7)
        os.write(peer_fd, wire_data[split:])
        datagram, _ = tm_socket.recvfrom(65507)
        assert datagram == payload
        self.assert_no_more_datagrams(tm_socket)

    def test_uart_garbage_discarded(self, bridge_setup):
        """Unframed garbage must not reach the TM intake"""
        framing, peer_fd, tm_socket, _, _, _ = bridge_setup
        if framing != "fprime":
            pytest.skip("garbage rejection applies to fprime framing only")
        os.write(peer_fd, b"\x00\x01garbage-without-start-word")
        time.sleep(0.7)
        payload = b"good-packet"
        os.write(peer_fd, FpFramerDeframer().frame(payload))
        datagram, _ = tm_socket.recvfrom(65507)
        assert datagram == payload
        self.assert_no_more_datagrams(tm_socket)

    def test_udp_to_uart(self, bridge_setup):
        """UDP outlet -> bridge -> endpoint"""
        framing, peer_fd, _, tc_socket, tc_port, _ = bridge_setup
        payload = b"command-packet-payload"
        tc_socket.sendto(payload, ("127.0.0.1", tc_port))
        expected = (
            payload if framing == "no-op" else FpFramerDeframer().frame(payload)
        )
        received = read_available(peer_fd, minimum=len(expected))
        assert received == expected
        # No trailing or duplicated bytes may follow the expected frame
        assert read_available(peer_fd, minimum=1, timeout=0.5) == b""

    def test_udp_to_uart_unexpected_source_dropped(self, bridge_setup):
        """TC datagrams from sources outside the allowed set must not reach the endpoint"""
        framing, peer_fd, _, tc_socket, tc_port, _ = bridge_setup
        rogue = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rogue.bind(("127.0.0.2", 0))
        rogue.sendto(b"rogue-command", ("127.0.0.1", tc_port))
        rogue.close()
        assert read_available(peer_fd, minimum=1, timeout=1.0) == b""
        # Positive control: an allowed-source datagram must still flow, proving the
        # uplink pump is alive and only the rogue datagram was filtered
        payload = b"allowed-command"
        tc_socket.sendto(payload, ("127.0.0.1", tc_port))
        expected = (
            payload if framing == "no-op" else FpFramerDeframer().frame(payload)
        )
        assert read_available(peer_fd, minimum=len(expected)) == expected


TM_FRAME_SIZE = 64
TM_SCID = 0x44


def make_tm_frame(mc_count=0, fill=0xAB):
    """Build a fixed-size CCSDS TM frame as Svc::Ccsds::TmFramer emits it (trailer arbitrary)"""
    global_vcid = (TM_SCID & 0x3FF) << 4
    data_field_status = 0x3 << 11
    header = struct.pack(">HBBH", global_vcid, mc_count, mc_count, data_field_status)
    return header + bytes([fill]) * (TM_FRAME_SIZE - len(header) - 2) + b"\xCC\xCC"


def unused_tcp_port():
    """Reserve a TCP port number"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        return reservation.getsockname()[1]


@pytest.fixture
def tcp_bridge_setup(unused_udp_ports):
    """Run the bridge with its default adapter/framing (tcp-fast-server, tm-frame-aggregator)"""
    tm_port, tc_port = unused_udp_ports
    tcp_port = unused_tcp_port()
    tm_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tm_socket.bind(("127.0.0.1", tm_port))
    tm_socket.settimeout(TIMEOUT)
    tc_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    bridge = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "fprime_gds.executables.comm_bridge",
            "--tcp-fast-port",
            str(tcp_port),
            "--frame-size",
            str(TM_FRAME_SIZE),
            "--scid",
            str(TM_SCID),
            "--tm-port",
            str(tm_port),
            "--tc-port",
            str(tc_port),
        ],
        stderr=subprocess.PIPE,
        text=True,
    )
    stderr_lines = []
    reader = threading.Thread(
        target=lambda: stderr_lines.extend(iter(bridge.stderr.readline, "")),
        daemon=True,
    )
    reader.start()
    assert wait_for_line(stderr_lines, "Bridge up"), "Bridge failed to start"
    assert bridge.poll() is None, "Bridge process exited prematurely"
    peer = socket.create_connection(("127.0.0.1", tcp_port), timeout=TIMEOUT)
    peer.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    yield peer, tm_socket, tc_socket, tc_port, stderr_lines
    bridge.send_signal(signal.SIGINT)
    bridge.wait(timeout=TIMEOUT)
    reader.join(timeout=TIMEOUT)
    peer.close()
    tm_socket.close()
    tc_socket.close()


class TestDefaultTcpBridgeFlow:
    """Integration tests for the default topology: TCP endpoint -> TM frame aggregator -> UDP"""

    def test_defaults_selected(self, tcp_bridge_setup):
        """The bridge must report the tcp-fast-server and tm-frame-aggregator defaults, without the no-op warning"""
        _, _, _, _, stderr_lines = tcp_bridge_setup
        assert any("tcp-fast-server" in line and "tm-frame-aggregator" in line for line in stderr_lines)
        assert not any("cannot preserve" in line for line in stderr_lines)

    def test_frames_reassembled_from_stream(self, tcp_bridge_setup):
        """Frames split and merged across TCP writes must each arrive as one UDP datagram"""
        peer, tm_socket, _, _, _ = tcp_bridge_setup
        frames = [make_tm_frame(mc_count=count, fill=0xA0 + count) for count in range(3)]
        stream = b"".join(frames)
        # Split at points unrelated to frame boundaries, pausing so reads see the partial data
        for start, end in ((0, 10), (10, 70), (70, 150), (150, len(stream))):
            peer.sendall(stream[start:end])
            time.sleep(0.1)
        received = [tm_socket.recvfrom(65507)[0] for _ in frames]
        assert received == frames

    def test_leading_garbage_discarded(self, tcp_bridge_setup):
        """Bytes preceding a frame header must be discarded, not forwarded"""
        peer, tm_socket, _, _, stderr_lines = tcp_bridge_setup
        frame = make_tm_frame()
        peer.sendall(b"\xFF\xFE\xFD" + frame)
        assert tm_socket.recvfrom(65507)[0] == frame
        assert wait_for_line(stderr_lines, "Discarded 3 bytes")

    def test_udp_to_tcp_passthrough(self, tcp_bridge_setup):
        """TC datagrams must reach the TCP endpoint unchanged"""
        peer, _, tc_socket, tc_port, _ = tcp_bridge_setup
        command = bytes(range(48))
        tc_socket.sendto(command, ("127.0.0.1", tc_port))
        received = b""
        while len(received) < len(command):
            chunk = peer.recv(4096)
            assert chunk, "TCP endpoint closed before the command arrived"
            received += chunk
        assert received == command


class TestUdpLinksSources:
    """Unit tests for TC source resolution and filtering"""

    def test_hostnames_resolved(self):
        """Configured hostnames must resolve to numeric addresses"""
        udp = UdpLinks("localhost", 50000, "127.0.0.1", 50001, ["localhost"])
        assert "127.0.0.1" in udp.allowed_sources
        assert all("localhost" != source for source in udp.allowed_sources)

    def test_extra_source_accepted(self):
        """A datagram from a --tc-allowed-source address must be accepted"""
        udp = UdpLinks("127.0.0.1", 50000, "127.0.0.1", 0, ["127.0.0.2"])
        udp.open()
        try:
            tc_port = udp.tc_socket.getsockname()[1]
            sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sender.bind(("127.0.0.2", 0))
            sender.sendto(b"extra-source-command", ("127.0.0.1", tc_port))
            sender.close()
            assert udp.receive() == b"extra-source-command"
        finally:
            udp.close()


class StubAdapter:
    """Minimal communication adapter stub for unit-testing the bridge loops"""

    def __init__(self, reads=None, fail=False):
        self.reads = list(reads or [])
        self.fail = fail
        self.written = []

    def open(self):
        pass

    def close(self):
        pass

    def read(self):
        if self.fail:
            raise RuntimeError("adapter read failure")
        return self.reads.pop(0) if self.reads else b""

    def write(self, data):
        self.written.append(data)
        return True


class StubUdp:
    """Minimal UdpLinks stub for unit-testing the bridge loops"""

    def __init__(self):
        self.sent = []

    def open(self):
        pass

    def close(self):
        pass

    def send(self, packet):
        self.sent.append(packet)
        return True

    def receive(self):
        return None


class WithholdingFramer(NoOpFramerDeframer):
    """Framer stub that never yields packets, leaving all input pending"""

    def deframe(self, data, no_copy=False):
        return None, data, b""


class TestBridgeRobustness:
    """Unit tests for the bridge failure and overflow handling"""

    def test_failure_handler_fires_on_loop_exception(self):
        """An abnormal pump-thread exit must invoke the failure handler"""
        failed = threading.Event()
        bridge = UdpBridge(
            StubAdapter(fail=True),
            NoOpFramerDeframer(),
            StubUdp(),
            failure_handler=failed.set,
        )
        bridge.start()
        assert failed.wait(timeout=TIMEOUT)
        bridge.stop()

    def test_pending_overflow_dropped(self, caplog):
        """Undeframable pending data must be dropped once it exceeds the cap"""
        chunk = b"x" * (MAXIMUM_PENDING_SIZE // 2)
        adapter = StubAdapter(reads=[chunk, chunk, chunk, b"final"])
        udp = StubUdp()
        bridge = UdpBridge(adapter, WithholdingFramer(), udp)
        with caplog.at_level(logging.WARNING, logger="fprime_gds.common.communication.bridge.bridge"):
            bridge.start()
            end = time.time() + TIMEOUT
            while time.time() < end and adapter.reads:
                time.sleep(0.05)
            bridge.stop()
        assert not adapter.reads, "Bridge stalled instead of dropping pending data"
        assert udp.sent == []
        assert "Dropping" in caplog.text


class TestCliValidation:
    """Tests for CLI argument validation failure paths"""

    @pytest.mark.parametrize("flag,value", [("--tm-port", "0"), ("--tc-port", "70000")])
    def test_invalid_port_rejected(self, flag, value):
        result = subprocess.run(
            [sys.executable, "-m", "fprime_gds.executables.comm_bridge", "--tcp-fast-port", str(unused_tcp_port()), flag, value],
            capture_output=True,
            text=True,
            timeout=TIMEOUT * 3,
        )
        assert result.returncode != 0
        assert "Invalid UDP port" in result.stderr

    def test_missing_dictionary_rejected(self, tmp_path):
        result = subprocess.run(
            [
                sys.executable, "-m", "fprime_gds.executables.comm_bridge",
                "--tcp-fast-port", str(unused_tcp_port()), "--dictionary", str(tmp_path / "missing.json"),
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT * 3,
        )
        assert result.returncode != 0
        assert "does not exist" in result.stderr

    def test_unknown_frame_size_rejected(self):
        """Without a dictionary or --frame-size the default aggregator cannot be configured"""
        result = subprocess.run(
            [sys.executable, "-m", "fprime_gds.executables.comm_bridge", "--tcp-fast-port", str(unused_tcp_port())],
            capture_output=True,
            text=True,
            timeout=TIMEOUT * 3,
        )
        assert result.returncode != 0
        assert "Failed to configure 'tm-frame-aggregator' framing" in result.stderr

    @pytest.mark.parametrize(
        "supplied,loads",
        [({}, False), ({"dictionary": "dict.json"}, True), ({"deployment": "build"}, True)],
    )
    def test_dictionary_loaded_only_when_supplied(self, monkeypatch, supplied, loads):
        """The GDS dictionary parser runs only when --dictionary or --deployment is given"""
        calls = []
        monkeypatch.setattr(DictionaryParser, "handle_arguments", lambda self, args, **kw: calls.append(args) or args)
        args = Namespace(**{"dictionary": None, "deployment": None, **supplied})
        assert OptionalDictionaryParser().handle_arguments(args) is args
        assert bool(calls) == loads

    def test_unresolvable_host_rejected(self, monkeypatch):
        """Host resolution failures must surface as OSError (main exits 1 on it)"""

        def fail_resolution(_):
            raise socket.gaierror("resolution failed")

        # Patched to avoid live DNS egress from the test suite
        monkeypatch.setattr(socket, "gethostbyname", fail_resolution)
        with pytest.raises(OSError):
            UdpLinks("no-such-host.invalid", 50000, "127.0.0.1", 50001)
