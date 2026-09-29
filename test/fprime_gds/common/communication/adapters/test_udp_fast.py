"""Tests for the udp-fast communication adapter

All tests use real loopback sockets on ephemeral ports. Timing assertions are deliberately loose (multiples of the
adapter's timeouts) so they hold on loaded CI hosts while still catching blocking or spinning regressions.
"""

import inspect
import logging
import select
import socket
import threading
import time

import pytest

from fprime_gds.common.communication.adapters.udp_fast import UdpFastAdapter
from fprime_gds.plugin.system import Plugins

TIMEOUT = 0.050
# Generous bound for any single read() call: the adapter's timeout plus scheduling slack
READ_BOUND = TIMEOUT * 6
# Generous bound for a bind retry: backoff plus slack
REBIND_BOUND = UdpFastAdapter.RECONNECT_INTERVAL * 3
LOGGER_NAME = "udp_fast_adapter"


def loopback_alias_or_skip(address="127.0.0.2"):
    """A second loopback address to send from (Linux binds the whole 127/8 range; skip where it cannot be bound)"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind((address, 0))
    except OSError:
        pytest.skip(f"{address} cannot be bound on this host")
    return address


def udp_socket(address="127.0.0.1"):
    """A UDP socket bound to an ephemeral port on `address`, with a short receive timeout"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((address, 0))
    sock.settimeout(2.0)
    return sock


def read_until(adapter, deadline=2.0):
    """Call read() until a datagram is returned or the deadline passes"""
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        datagram = adapter.read(TIMEOUT)
        if datagram:
            return datagram
    return b""


def make_adapter(peer, **overrides):
    """An adapter sending to `peer` and receiving on an ephemeral loopback port"""
    arguments = {
        "udp_fast_address": "127.0.0.1",
        "udp_fast_send_port": peer.getsockname()[1],
        "udp_fast_recv_port": 0,
        "udp_fast_bind_address": "127.0.0.1",
    }
    arguments.update(overrides)
    return UdpFastAdapter(**arguments)


def recv_port(adapter):
    """The port the adapter's receive socket is bound to"""
    return adapter.recv_socket.getsockname()[1]


@pytest.fixture
def peer():
    """Ground/flight peer socket: the adapter sends to it and it sends to the adapter"""
    sock = udp_socket()
    yield sock
    sock.close()


@pytest.fixture
def adapter(peer):
    """An opened adapter paired with `peer`"""
    opened = make_adapter(peer)
    opened.open()
    assert opened.recv_socket is not None
    yield opened
    opened.close()


class TestPlugin:
    def test_registered_as_built_in(self):
        names = [plugin.plugin_class.get_name() for plugin in Plugins(["communication"]).get_plugins("communication")]
        assert "udp-fast" in names
        assert "udp" in names  # the existing adapter is untouched and still available

    def test_defaults(self):
        adapter = UdpFastAdapter()
        assert adapter.get_name() == "udp-fast"
        assert adapter.destination == ("127.0.0.1", 50000)
        assert (adapter.bind_address, adapter.recv_port) == ("127.0.0.1", 50001)
        assert adapter.extra_sources == []
        assert "udp-fast" in repr(adapter)

    def test_arguments_match_constructor(self):
        """Every CLI option maps onto a constructor parameter with the same default, and vice versa"""
        specifications = {spec["dest"]: spec for spec in UdpFastAdapter.get_arguments().values()}
        parameters = inspect.signature(UdpFastAdapter.__init__).parameters
        assert set(specifications) == set(parameters) - {"self"}
        for name, parameter in parameters.items():
            if name != "self":
                assert specifications[name]["default"] == parameter.default
        assert set(inspect.signature(UdpFastAdapter.check_arguments).parameters) == set(specifications)

    @pytest.mark.parametrize("arguments", [{"udp_fast_send_port": 0}, {"udp_fast_recv_port": 70000}])
    def test_check_arguments_rejects_bad_ports(self, arguments):
        with pytest.raises(ValueError, match="not in the range 1-65535"):
            UdpFastAdapter.check_arguments(**arguments)

    def test_check_arguments_rejects_busy_port(self, peer):
        with pytest.raises(ValueError, match="Cannot bind"):
            UdpFastAdapter.check_arguments(udp_fast_recv_port=peer.getsockname()[1])

    def test_check_arguments_accepts_free_port(self):
        with udp_socket() as reservation:
            port = reservation.getsockname()[1]
        UdpFastAdapter.check_arguments(udp_fast_recv_port=port)


class TestWrite:
    def test_write_is_one_datagram(self, adapter, peer):
        assert adapter.write(b"hello") is True
        assert adapter.write(b"world") is True
        assert peer.recvfrom(65535)[0] == b"hello"
        assert peer.recvfrom(65535)[0] == b"world"

    def test_write_before_open_is_false(self, peer):
        assert make_adapter(peer).write(b"x") is False

    def test_write_after_close_is_false(self, adapter):
        adapter.close()
        assert adapter.write(b"x") is False

    def test_oversized_write_is_false_and_warns_once(self, adapter, peer, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            assert adapter.write(b"x" * 70000) is False
            assert adapter.write(b"x" * 70000) is False
            assert adapter.write(b"ok") is True
            assert adapter.write(b"x" * 70000) is False
        warnings = [record for record in caplog.records if "send failed" in record.getMessage()]
        assert len(warnings) == 2  # one per outage: a successful write ends an outage
        assert peer.recvfrom(65535)[0] == b"ok"

    def test_maximum_payload(self, adapter, peer):
        payload = bytes(range(256)) * 255 + b"\0" * (65507 - 65280)
        assert len(payload) == 65507
        assert adapter.write(payload) is True
        assert peer.recvfrom(65535)[0] == payload


class TestRead:
    def test_one_datagram_per_read(self, adapter, peer):
        """Queued datagrams come back one at a time, never concatenated"""
        peer.sendto(b"first", ("127.0.0.1", recv_port(adapter)))
        peer.sendto(b"second", ("127.0.0.1", recv_port(adapter)))
        assert read_until(adapter) == b"first"
        assert read_until(adapter) == b"second"
        assert adapter.read(TIMEOUT) == b""

    def test_maximum_payload(self, adapter, peer):
        payload = b"\xaa" * 65507
        peer.sendto(payload, ("127.0.0.1", recv_port(adapter)))
        assert read_until(adapter) == payload

    def test_idle_read_bounded(self, adapter):
        start = time.monotonic()
        assert adapter.read(TIMEOUT) == b""
        assert TIMEOUT * 0.5 <= time.monotonic() - start < READ_BOUND

    def test_default_timeout_is_short(self, adapter):
        start = time.monotonic()
        assert adapter.read() == b""
        assert time.monotonic() - start < READ_BOUND

    def test_data_returns_at_once(self, adapter, peer):
        peer.sendto(b"now", ("127.0.0.1", recv_port(adapter)))
        start = time.monotonic()
        assert read_until(adapter) == b"now"
        assert time.monotonic() - start < READ_BOUND

    def test_no_threads_created(self, peer):
        before = threading.active_count()
        adapter = make_adapter(peer)
        adapter.open()
        adapter.write(b"x")
        adapter.read(TIMEOUT)
        assert threading.active_count() == before
        adapter.close()

    def test_read_after_close_sleeps_and_returns_empty(self, adapter):
        adapter.close()
        start = time.monotonic()
        assert adapter.read(TIMEOUT) == b""
        assert TIMEOUT * 0.5 <= time.monotonic() - start < READ_BOUND

    def test_receive_error_rebinds(self, peer, caplog):
        """A receive socket failing underneath the adapter is dropped, warned once, and rebound on the same port"""
        with udp_socket() as reservation:
            port = reservation.getsockname()[1]
        adapter = make_adapter(peer, udp_fast_recv_port=port)
        adapter.open()
        assert recv_port(adapter) == port
        adapter.recv_socket.close()  # select() now raises on the dead descriptor
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            assert adapter.read(TIMEOUT) == b""
            assert adapter.recv_socket is None
            end = time.monotonic() + REBIND_BOUND
            while adapter.recv_socket is None and time.monotonic() < end:
                adapter.read(TIMEOUT)
        assert adapter.recv_socket is not None
        assert len([record for record in caplog.records if "receive failed" in record.getMessage()]) == 1
        assert recv_port(adapter) == port
        peer.sendto(b"back", ("127.0.0.1", port))
        assert read_until(adapter) == b"back"
        adapter.close()


class TestSources:
    def test_peer_and_loopback_accepted_by_default(self, peer):
        adapter = make_adapter(peer, udp_fast_address="localhost")
        adapter.open()
        try:
            assert adapter.allowed_sources == {"127.0.0.1"}
            assert adapter.destination == ("127.0.0.1", peer.getsockname()[1])
        finally:
            adapter.close()

    def test_unexpected_source_dropped_and_warned_once(self, adapter, caplog):
        with udp_socket(loopback_alias_or_skip()) as rogue, caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            rogue.sendto(b"rogue-1", ("127.0.0.1", recv_port(adapter)))
            rogue.sendto(b"rogue-2", ("127.0.0.1", recv_port(adapter)))
            assert read_until(adapter, deadline=READ_BOUND * 2) == b""
        warnings = [record for record in caplog.records if "unexpected source 127.0.0.2" in record.getMessage()]
        assert len(warnings) == 1

    def test_extra_source_accepted(self, peer):
        adapter = make_adapter(peer, udp_fast_allowed_sources=["127.0.0.2"])
        adapter.open()
        try:
            with udp_socket(loopback_alias_or_skip()) as extra:
                extra.sendto(b"extra-source-command", ("127.0.0.1", recv_port(adapter)))
            assert read_until(adapter) == b"extra-source-command"
        finally:
            adapter.close()

    def test_hostnames_resolved_at_open_not_in_hot_path(self, peer, monkeypatch):
        adapter = make_adapter(peer, udp_fast_address="localhost", udp_fast_allowed_sources=["localhost"])
        adapter.open()
        try:
            assert adapter.allowed_sources == {"127.0.0.1"}

            def no_lookup(_):
                raise AssertionError("name lookup on the read/write path")

            monkeypatch.setattr(socket, "gethostbyname", no_lookup)
            assert adapter.write(b"ping") is True
            assert peer.recvfrom(65535)[0] == b"ping"
            peer.sendto(b"pong", ("127.0.0.1", recv_port(adapter)))
            assert read_until(adapter) == b"pong"
        finally:
            adapter.close()

    def test_unresolvable_peer_raises_at_open(self, peer, monkeypatch):
        def fail_resolution(_):
            raise socket.gaierror("resolution failed")

        # Patched to avoid live DNS egress from the test suite
        monkeypatch.setattr(socket, "gethostbyname", fail_resolution)
        adapter = make_adapter(peer, udp_fast_address="no-such-host.invalid")
        with pytest.raises(OSError):
            adapter.open()
        assert adapter.send_socket is None and adapter.recv_socket is None


class TestBind:
    def test_busy_port_retries_from_read(self, peer, caplog):
        """open() succeeds with the port busy; read() stays bounded, warns once, and binds once the port frees up"""
        holder = udp_socket()
        adapter = make_adapter(peer, udp_fast_recv_port=holder.getsockname()[1])
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            adapter.open()
            assert adapter.recv_socket is None
            for _ in range(5):
                start = time.monotonic()
                assert adapter.read(TIMEOUT) == b""
                assert time.monotonic() - start < READ_BOUND
            holder.close()
            end = time.monotonic() + REBIND_BOUND
            while adapter.recv_socket is None and time.monotonic() < end:
                adapter.read(TIMEOUT)
        try:
            assert adapter.recv_socket is not None
            assert len([record for record in caplog.records if "cannot bind" in record.getMessage()]) == 1
            peer.sendto(b"late", ("127.0.0.1", recv_port(adapter)))
            assert read_until(adapter) == b"late"
        finally:
            adapter.close()

    def test_busy_port_warns_once_while_writing(self, peer, caplog):
        """Successful writes must not reset the receive-side warning: one 'cannot bind' per outage"""
        holder = udp_socket()
        adapter = make_adapter(peer, udp_fast_recv_port=holder.getsockname()[1])
        adapter.RECONNECT_INTERVAL = 0.05
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            adapter.open()
            end = time.monotonic() + 0.5
            while time.monotonic() < end:
                assert adapter.write(b"telemetry")
                adapter.read(TIMEOUT)
        try:
            assert adapter.recv_socket is None
            assert len([record for record in caplog.records if "cannot bind" in record.getMessage()]) == 1
        finally:
            adapter.close()
            holder.close()

    def test_spurious_readiness_keeps_socket(self, adapter, peer, caplog, monkeypatch):
        """select reporting readiness with nothing to receive is transient: no warning, no rebind"""
        recv_socket = adapter.recv_socket
        monkeypatch.setattr(select, "select", lambda *_: ([recv_socket], [], []))
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            assert adapter.read(TIMEOUT) == b""
        monkeypatch.undo()
        assert adapter.recv_socket is recv_socket
        assert not caplog.records
        peer.sendto(b"after", ("127.0.0.1", recv_port(adapter)))
        assert read_until(adapter) == b"after"

    def test_no_reuseaddr(self, adapter):
        """A second adapter must not be able to share the receive port"""
        with pytest.raises(OSError):
            UdpFastAdapter.receiving_socket("127.0.0.1", recv_port(adapter))

    def test_close_releases_port(self, adapter):
        port = recv_port(adapter)
        adapter.close()
        UdpFastAdapter.receiving_socket("127.0.0.1", port).close()

    def test_reopen_releases_previous_sockets(self, peer):
        """Opening an already-open adapter closes the earlier sockets rather than leaking them"""
        with udp_socket() as reservation:
            port = reservation.getsockname()[1]
        adapter = make_adapter(peer, udp_fast_recv_port=port)
        adapter.open()
        first_send, first_recv = adapter.send_socket, adapter.recv_socket
        adapter.open()
        assert first_send.fileno() == -1 and first_recv.fileno() == -1
        assert adapter.recv_socket is not None and recv_port(adapter) == port
        adapter.close()

    def test_close_is_idempotent(self, adapter):
        adapter.close()
        adapter.close()
