"""Tests for the fprime-comm-bridge

Unit tests cover the packaged no-op framer/deframer. Integration tests flow data through
the full bridge: a socat-provided PTY pair stands in for a UART endpoint on one side, and
UDP sockets stand in for the ground system intake/outlet on the other.
"""

import contextlib
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

import pytest

from fprime_gds.common.communication.framing import FpFramerDeframer
from fprime_gds.executables.cli import DictionaryParser
from fprime_gds.executables.comm_bridge import GROUND_ADAPTER, OptionalDictionaryParser, ground_adapter_arguments
from fprime_gds.common.communication.adapters.udp_fast import UdpFastAdapter
from fprime_gds.common.communication.bridge.bridge import (
    MAXIMUM_PENDING_SIZE,
    SPACE_PACKET_IDLE_APID,
    PacketBridge,
    split_space_packets,
)
from fprime_gds.common.communication.bridge.framing import NoOpFramerDeframer
from fprime_gds.common.communication.ccsds.space_data_link import SpaceDataLinkFramerDeframer

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


def loopback_alias_or_skip(address="127.0.0.2"):
    """A second loopback address to send from (Linux binds the whole 127/8 range; skip where it cannot be bound)"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind((address, 0))
    except OSError:
        pytest.skip(f"{address} cannot be bound on this host")
    return address


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


@pytest.fixture(params=["no-op", "fprime"])
def bridge_setup(request, pty_pair):
    """Run the bridge against one PTY end, exposing the peer PTY and UDP sockets"""
    link_a, link_b = pty_pair
    tm_port, tc_port = unused_udp_port(), unused_udp_port()

    tm_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tm_socket.bind(("127.0.0.1", tm_port))
    tm_socket.settimeout(TIMEOUT)
    tc_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    with run_bridge(
        "--communication-selection", "uart", "--uart-device", str(link_a), "--uart-skip-port-check",
        "--framing-selection", request.param, "--udp-fast-send-port", str(tm_port), "--udp-fast-recv-port", str(tc_port),
    ) as stderr_lines:
        peer_fd = os.open(link_b, os.O_RDWR | os.O_NONBLOCK)
        yield request.param, peer_fd, tm_socket, tc_socket, tc_port, stderr_lines
        os.close(peer_fd)
    tm_socket.close()
    tc_socket.close()


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
        rogue.bind((loopback_alias_or_skip(), 0))
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
TM_VCID = 1  # raw-space-data-link --vcid default


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


def unused_udp_port():
    """Reserve a UDP port number"""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        return reservation.getsockname()[1]


@contextlib.contextmanager
def run_bridge(*arguments):
    """Run `fprime-comm-bridge` with `arguments` until the block exits, yielding its stderr lines once it is up"""
    bridge = subprocess.Popen(
        [sys.executable, "-m", "fprime_gds.executables.comm_bridge", *arguments],
        stderr=subprocess.PIPE,
        text=True,
    )
    stderr_lines = []
    reader = threading.Thread(
        target=lambda: stderr_lines.extend(iter(bridge.stderr.readline, "")),
        daemon=True,
    )
    reader.start()
    try:
        assert wait_for_line(stderr_lines, "Bridge up"), "Bridge failed to start"
        assert bridge.poll() is None, "Bridge process exited prematurely"
        yield stderr_lines
    finally:
        if bridge.poll() is None:
            bridge.send_signal(signal.SIGINT)
        bridge.wait(timeout=TIMEOUT)
        reader.join(timeout=TIMEOUT)


def tcp_bridge(framing_arguments):
    """Run the bridge with the default tcp-fast-server adapter and TCP peer, TM/TC UDP sockets and `framing_arguments`"""
    tm_port, tc_port = unused_udp_port(), unused_udp_port()
    tcp_port = unused_tcp_port()
    tm_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tm_socket.bind(("127.0.0.1", tm_port))
    tm_socket.settimeout(TIMEOUT)
    tc_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    with run_bridge(
        "--tcp-fast-port", str(tcp_port), "--frame-size", str(TM_FRAME_SIZE), "--scid", str(TM_SCID),
        "--udp-fast-send-port", str(tm_port), "--udp-fast-recv-port", str(tc_port), *framing_arguments,
    ) as stderr_lines:
        peer = socket.create_connection(("127.0.0.1", tcp_port), timeout=TIMEOUT)
        peer.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        yield peer, tm_socket, tc_socket, tc_port, stderr_lines
        peer.close()
    tm_socket.close()
    tc_socket.close()


@pytest.fixture
def tcp_bridge_setup():
    """Run the bridge with its default adapter/framing (tcp-fast-server, tm-frame-aggregator)"""
    yield from tcp_bridge([])


@pytest.fixture
def raw_bridge_setup():
    """Run the bridge with tcp-fast-server and raw-space-data-link framing (Space Packets on the UDP side)"""
    yield from tcp_bridge(["--framing-selection", "raw-space-data-link"])


def make_tm_frame_with_field(field, mc_count=0):
    """Build a CRC-valid TM frame on the raw-space-data-link default VCID, its data field starting a Space Packet (FHP = 0)"""
    assert len(field) == TM_FRAME_SIZE - 6 - 2
    global_vcid = ((TM_SCID & 0x3FF) << 4) | ((TM_VCID & 0x7) << 1)
    data_field_status = 0x3 << 11
    body = struct.pack(">HBBH", global_vcid, mc_count, mc_count, data_field_status) + field
    return body + struct.pack(">H", SpaceDataLinkFramerDeframer.CCITT_CRC_FUNCTION(body))


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


class TestRawSpacePacketBridgeFlow:
    """Integration tests for the opt-in raw-space-data-link topology: TM frames in, one Space Packet per datagram out"""

    def test_raw_framing_selected(self, raw_bridge_setup):
        _, _, _, _, stderr_lines = raw_bridge_setup
        assert any("tcp-fast-server" in line and "raw-space-data-link" in line for line in stderr_lines)

    def test_one_datagram_per_space_packet_idle_dropped(self, raw_bridge_setup):
        """Complete Space Packets in one TM frame must each arrive as one datagram; idle fill must not"""
        peer, tm_socket, _, _, _ = raw_bridge_setup
        first, second = space_packet(1, b"one"), space_packet(2, b"two")
        field_size = TM_FRAME_SIZE - 6 - 2
        idle = space_packet(SPACE_PACKET_IDLE_APID, b"\x00" * (field_size - len(first) - len(second) - 6))
        peer.sendall(make_tm_frame_with_field(first + second + idle))
        assert [tm_socket.recvfrom(65507)[0] for _ in range(2)] == [first, second]
        TestBridgeFlow.assert_no_more_datagrams(tm_socket)

    def test_space_packet_uplinked_in_tc_frame(self, raw_bridge_setup):
        """A Space Packet datagram must reach the TCP endpoint wrapped in a TC transfer frame"""
        peer, _, tc_socket, tc_port, _ = raw_bridge_setup
        packet = space_packet(0, b"\x00\x00\x01\x00\x00\x00")
        tc_socket.sendto(packet, ("127.0.0.1", tc_port))
        expected_size = SpaceDataLinkFramerDeframer.TC_HEADER_SIZE + len(packet) + 2
        received = b""
        while len(received) < expected_size:
            chunk = peer.recv(4096)
            assert chunk, "TCP endpoint closed before the command arrived"
            received += chunk
        assert len(received) == expected_size
        assert received[SpaceDataLinkFramerDeframer.TC_HEADER_SIZE:-2] == packet

    def test_oversized_space_packet_dropped_bridge_survives(self, raw_bridge_setup):
        """A ground datagram too large for a TC frame is dropped with a warning; later commands still flow"""
        peer, _, tc_socket, tc_port, stderr_lines = raw_bridge_setup
        tc_socket.sendto(space_packet(0, b"\x00" * 2000), ("127.0.0.1", tc_port))
        assert wait_for_line(stderr_lines, "Dropping 2006 byte ground packet")
        packet = space_packet(0, b"ok")
        tc_socket.sendto(packet, ("127.0.0.1", tc_port))
        received = b""
        while packet not in received:
            chunk = peer.recv(4096)
            assert chunk, "TCP endpoint closed before the command arrived"
            received += chunk


class TestGroundAdapter:
    """Unit tests for the ground-side adapter selection and its argument extraction"""

    def test_ground_adapter_is_udp_fast(self):
        assert GROUND_ADAPTER is UdpFastAdapter

    def test_arguments_extracted_from_plugin_options(self):
        """Every plugin option is forwarded to the constructor under its destination name"""
        args = Namespace(
            udp_fast_address="10.0.0.5",
            udp_fast_send_port=61000,
            udp_fast_recv_port=61001,
            udp_fast_bind_address="0.0.0.0",
            udp_fast_allowed_sources=["10.0.0.6"],
            unrelated="ignored",
        )
        extracted = ground_adapter_arguments(args)
        assert extracted == {
            "udp_fast_address": "10.0.0.5",
            "udp_fast_send_port": 61000,
            "udp_fast_recv_port": 61001,
            "udp_fast_bind_address": "0.0.0.0",
            "udp_fast_allowed_sources": ["10.0.0.6"],
        }
        adapter = UdpFastAdapter(**extracted)
        assert adapter.destination == ("10.0.0.5", 61000)
        assert adapter.extra_sources == ["10.0.0.6"]


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


class WithholdingFramer(NoOpFramerDeframer):
    """Framer stub that never yields packets, leaving all input pending"""

    def deframe(self, data, no_copy=False):
        return None, data, b""


class RejectingFramer(NoOpFramerDeframer):
    """Framer stub that, like the CCSDS framers, raises on a packet it cannot frame"""

    LIMIT = 4

    def frame(self, data):
        if len(data) > self.LIMIT:
            raise AssertionError("Length too-large for the frame")
        return data


class FailingOpenAdapter(StubAdapter):
    """Adapter stub whose open() fails"""

    def open(self):
        raise OSError("cannot open")


class ClosableStubAdapter(StubAdapter):
    """Adapter stub recording whether close() was called"""

    def __init__(self):
        super().__init__()
        self.closed = False

    def close(self):
        self.closed = True


class DiscardingFramer(NoOpFramerDeframer):
    """Framer stub that discards everything it is given"""

    def deframe(self, data, no_copy=False):
        return None, b"", data


class TestBridgeRobustness:
    """Unit tests for the bridge failure and overflow handling"""

    def test_discard_warning_once_per_outage(self, caplog):
        """Continuous discarding warns once, not once per read"""
        adapter = StubAdapter(reads=[b"junk"] * 5)
        bridge = PacketBridge(adapter, DiscardingFramer(), StubAdapter())
        with caplog.at_level(logging.WARNING, logger="fprime_gds.common.communication.bridge.bridge"):
            bridge.start()
            end = time.time() + TIMEOUT
            while time.time() < end and adapter.reads:
                time.sleep(0.05)
            bridge.stop()
        assert not adapter.reads
        assert len([record for record in caplog.records if "Discarded" in record.getMessage()]) == 1

    @pytest.mark.parametrize("flight_fails,ground_fails", [(True, False), (False, True)])
    def test_failure_handler_fires_on_loop_exception(self, flight_fails, ground_fails):
        """An abnormal exit of either pump thread must invoke the failure handler"""
        failed = threading.Event()
        bridge = PacketBridge(
            StubAdapter(fail=flight_fails),
            NoOpFramerDeframer(),
            StubAdapter(fail=ground_fails),
            failure_handler=failed.set,
        )
        bridge.start()
        assert failed.wait(timeout=TIMEOUT)
        bridge.stop()

    def test_unframeable_ground_packet_dropped(self, caplog):
        """A ground packet the framer rejects is dropped with a warning; the pump keeps running"""
        failed = threading.Event()
        flight = StubAdapter()
        ground = StubAdapter(reads=[b"too-large", b"ok"])
        bridge = PacketBridge(flight, RejectingFramer(), ground, failure_handler=failed.set)
        with caplog.at_level(logging.WARNING, logger="fprime_gds.common.communication.bridge.bridge"):
            bridge.start()
            end = time.time() + TIMEOUT
            while time.time() < end and not flight.written:
                time.sleep(0.05)
            bridge.stop()
        assert flight.written == [b"ok"]
        assert not failed.is_set()
        assert any("cannot be framed" in record.getMessage() for record in caplog.records)

    def test_ground_closed_when_flight_open_fails(self):
        """start() must release the ground adapter when the flight adapter cannot be opened"""
        ground = ClosableStubAdapter()
        bridge = PacketBridge(FailingOpenAdapter(), NoOpFramerDeframer(), ground)
        with pytest.raises(OSError):
            bridge.start()
        assert ground.closed

    def test_pending_overflow_dropped(self, caplog):
        """Undeframable pending data must be dropped once it exceeds the cap"""
        chunk = b"x" * (MAXIMUM_PENDING_SIZE // 2)
        adapter = StubAdapter(reads=[chunk, chunk, chunk, b"final"])
        ground = StubAdapter()
        bridge = PacketBridge(adapter, WithholdingFramer(), ground)
        with caplog.at_level(logging.WARNING, logger="fprime_gds.common.communication.bridge.bridge"):
            bridge.start()
            end = time.time() + TIMEOUT
            while time.time() < end and adapter.reads:
                time.sleep(0.05)
            bridge.stop()
        assert not adapter.reads, "Bridge stalled instead of dropping pending data"
        assert ground.written == []
        assert "Dropping" in caplog.text

    def test_packets_flow_both_ways_through_stubs(self):
        """Deframed packets reach the ground adapter; ground packets are framed and written to the flight adapter"""
        flight = StubAdapter(reads=[b"down-1", b"down-2"])
        ground = StubAdapter(reads=[b"up-1"])
        bridge = PacketBridge(flight, NoOpFramerDeframer(), ground)
        bridge.start()
        end = time.time() + TIMEOUT
        while time.time() < end and (len(ground.written) < 2 or len(flight.written) < 1):
            time.sleep(0.05)
        bridge.stop()
        assert ground.written == [b"down-1", b"down-2"]
        assert flight.written == [b"up-1"]


def space_packet(apid, payload):
    """Build a CCSDS Space Packet with the given APID and payload"""
    return struct.pack(">HHH", apid & 0x7FF, 0xC000, len(payload) - 1) + payload


class TestSpacePacketSplitting:
    """Unit tests for splitting concatenated Space Packets before emission"""

    def test_concatenated_packets_split(self):
        """Concatenated packets are emitted individually, idle packets are dropped"""
        telemetry = space_packet(1, b"tlm" * 20)
        event = space_packet(2, b"e")
        idle = space_packet(0x7FF, b"\x00" * 50)
        assert split_space_packets(telemetry + idle + event) == ([telemetry, event], b"")

    def test_partial_trailing_packet_is_remainder(self):
        """A trailing incomplete packet is returned as the remainder, not emitted"""
        whole = space_packet(1, b"abc")
        partial = space_packet(2, b"defgh")[:-2]
        assert split_space_packets(whole + partial) == ([whole], partial)
        assert split_space_packets(b"\x08\x01\xc0") == ([], b"\x08\x01\xc0")

    def test_empty(self):
        """No data yields no packets"""
        assert split_space_packets(b"") == ([], b"")

    def test_bridge_emits_one_packet_per_write(self, caplog):
        """The bridge writes each split packet separately and warns about unsplittable trailing bytes"""
        first, second = space_packet(1, b"one"), space_packet(2, b"two")
        flight = StubAdapter(reads=[first + space_packet(0x7FF, b"pad") + second + b"\x00\x01"])
        ground = StubAdapter()
        bridge = PacketBridge(flight, NoOpFramerDeframer(), ground, splitter=split_space_packets)
        with caplog.at_level(logging.WARNING, logger="fprime_gds.common.communication.bridge.bridge"):
            bridge.start()
            end = time.time() + TIMEOUT
            while time.time() < end and len(ground.written) < 2:
                time.sleep(0.05)
            bridge.stop()
        assert ground.written == [first, second]
        assert "trailing bytes" in caplog.text


class TestCliValidation:
    """Tests for CLI argument validation failure paths"""

    @pytest.mark.parametrize("flag,value", [("--udp-fast-send-port", "0"), ("--udp-fast-recv-port", "70000")])
    def test_invalid_port_rejected(self, flag, value):
        result = subprocess.run(
            [
                sys.executable, "-m", "fprime_gds.executables.comm_bridge", "--tcp-fast-port", str(unused_tcp_port()),
                "--frame-size", str(TM_FRAME_SIZE), "--scid", str(TM_SCID), flag, value,
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT * 3,
        )
        assert result.returncode != 0
        assert "Invalid 'udp-fast' ground adapter options" in result.stderr
        assert "not in the range 1-65535" in result.stderr

    def test_ground_adapter_as_flight_selection_rejected(self):
        """udp-fast is reserved for the ground side; selecting it for the F Prime side is an error"""
        result = subprocess.run(
            [
                sys.executable, "-m", "fprime_gds.executables.comm_bridge", "--communication-selection", "udp-fast",
                "--udp-fast-recv-port", str(unused_udp_port()), "--frame-size", str(TM_FRAME_SIZE), "--scid", str(TM_SCID),
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT * 3,
        )
        assert result.returncode != 0
        assert "cannot also be selected for the F Prime side" in result.stderr

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
