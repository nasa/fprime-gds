"""Tests for the tcp-fast-server and tcp-fast-client communication adapters

All tests use real loopback sockets on ephemeral ports. Timing assertions are deliberately loose (multiples of the
adapter's timeouts) so they hold on loaded CI hosts while still catching blocking or spinning regressions.
"""

import logging
import select
import socket
import sys
import threading
import time

import pytest

from fprime_gds.common.communication.adapters import tcp_fast
from fprime_gds.common.communication.adapters.ip import IpAdapter
from fprime_gds.common.communication.adapters.tcp_fast import (
    TcpFastAdapter,
    TcpFastClientAdapter,
    TcpFastServerAdapter,
)
from fprime_gds.executables.cli import ParserBase, PluginArgumentParser
from fprime_gds.plugin.system import Plugins

TIMEOUT = 0.050
# Generous bound for any single read() call: the adapter's timeout plus scheduling slack
READ_BOUND = TIMEOUT * 6
# Generous bound for a client reconnect: backoff plus connect plus slack
RECONNECT_BOUND = TcpFastAdapter.RECONNECT_INTERVAL * 3


def free_port():
    """Reserve and release an ephemeral loopback port"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def read_until(adapter, expected, deadline=2.0):
    """Call read() until `expected` bytes have accumulated or the deadline passes"""
    data = b""
    end = time.monotonic() + deadline
    while len(data) < expected and time.monotonic() < end:
        data += adapter.read(TIMEOUT)
    return data


def wait_for(predicate, deadline=2.0):
    """Poll a predicate until true or the deadline passes"""
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def select_readable(sock, timeout=0.5):
    """Sockets readable within the timeout"""
    readable, _, _ = select.select([sock], [], [], timeout)
    return readable


def recv_exact(sock, count, deadline=2.0):
    """Receive exactly `count` bytes from a blocking socket"""
    sock.settimeout(deadline)
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            break
        data += chunk
    return data


@pytest.fixture
def server():
    """Opened tcp-fast-server on an ephemeral port"""
    adapter = TcpFastServerAdapter(tcp_fast_port=free_port())
    adapter.open()
    yield adapter
    adapter.close()


@pytest.fixture
def peer(server):
    """A loopback peer connected to the server fixture, with the server having accepted it"""
    sock = socket.create_connection(("127.0.0.1", server.port), timeout=2.0)
    assert wait_for(lambda: server.read(TIMEOUT) == b"" and server.connection is not None)
    yield sock
    sock.close()


@pytest.fixture
def listener():
    """A loopback listening socket acting as the remote TcpServer for client tests"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    sock.settimeout(2.0)
    yield sock
    sock.close()


@pytest.fixture
def client(listener):
    """Opened tcp-fast-client pointed at the listener fixture"""
    adapter = TcpFastClientAdapter(tcp_fast_port=listener.getsockname()[1])
    adapter.open()
    yield adapter
    adapter.close()


def accept_client(client, listener):
    """Drive the client until the listener has accepted its connection"""
    for _ in range(50):
        client.read(TIMEOUT)
        if client.connection is not None:
            break
    accepted, _ = listener.accept()
    assert wait_for(lambda: client.read(TIMEOUT) == b"" and client.connection is not None)
    return accepted


@pytest.fixture
def plugin_system():
    """Communication-only plugin system installed as the singleton for CLI binding tests"""
    previous = Plugins._singleton
    system = Plugins(["communication"])
    Plugins._singleton = system
    yield system
    Plugins._singleton = previous


class TestServer:
    """REQ-TCPF-001: listen, accept one peer at a time, re-accept after disconnect"""

    def test_defaults(self):
        adapter = TcpFastServerAdapter()
        assert (adapter.address, adapter.port) == ("0.0.0.0", 50000)

    def test_open_listens(self, server):
        with socket.create_connection(("127.0.0.1", server.port), timeout=2.0):
            pass

    def test_read_before_peer_returns_empty_within_timeout(self, server):
        start = time.monotonic()
        assert server.read(TIMEOUT) == b""
        assert time.monotonic() - start < READ_BOUND

    def test_accept_and_read(self, server, peer):
        peer.sendall(b"hello")
        assert read_until(server, 5) == b"hello"

    def test_reaccepts_after_peer_disconnect(self, server, peer, caplog):
        caplog.set_level(logging.INFO)
        peer.close()
        assert wait_for(lambda: server.read(TIMEOUT) == b"" and server.connection is None)
        with socket.create_connection(("127.0.0.1", server.port), timeout=2.0) as second:
            second.sendall(b"again")
            assert read_until(server, 5) == b"again"
        assert sum(1 for record in caplog.records if record.levelno == logging.WARNING) == 1
        assert sum(1 for record in caplog.records if "connected to" in record.getMessage()) == 1

    def test_one_peer_at_a_time(self, server, peer):
        # A second connector waits in the backlog; the server keeps reading the first peer
        with socket.create_connection(("127.0.0.1", server.port), timeout=2.0) as second:
            second.sendall(b"ignored")
            peer.sendall(b"first")
            assert read_until(server, 5) == b"first"
            assert server.read(TIMEOUT) == b""
            peer.close()
            assert wait_for(lambda: server.read(TIMEOUT) == b"ignored")

    def test_open_with_busy_port_retries_listening(self, caplog):
        caplog.set_level(logging.WARNING)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen(1)
            port = busy.getsockname()[1]
            adapter = TcpFastServerAdapter(tcp_fast_address="127.0.0.1", tcp_fast_port=port)
            adapter.open()
            assert adapter.listener is None
            assert any("listen" in record.getMessage() for record in caplog.records)
        try:
            end = time.monotonic() + RECONNECT_BOUND
            while time.monotonic() < end and adapter.listener is None:
                start = time.monotonic()
                adapter.read(TIMEOUT)
                assert time.monotonic() - start < READ_BOUND
            with socket.create_connection(("127.0.0.1", port), timeout=2.0) as late:
                late.sendall(b"late")
                assert read_until(adapter, 4) == b"late"
        finally:
            adapter.close()

    def test_listener_failure_relistens_without_spinning(self, server):
        dead = server.listener
        dead.close()  # select/accept now fail on the dead listener
        calls = 0
        start = time.monotonic()
        while server.listener is None or server.listener is dead:
            assert server.read(TIMEOUT) == b""
            calls += 1
            assert time.monotonic() - start < RECONNECT_BOUND
        # Backoff, not a hot loop: a spin would produce thousands of reads per RECONNECT_INTERVAL
        assert calls < TcpFastAdapter.RECONNECT_INTERVAL / TIMEOUT * 3
        with socket.create_connection(("127.0.0.1", server.port), timeout=2.0) as again:
            again.sendall(b"again")
            assert read_until(server, 5) == b"again"


class TestClient:
    """REQ-TCPF-002: connect, reconnect with backoff after disconnect or failure"""

    def test_defaults(self):
        adapter = TcpFastClientAdapter()
        assert (adapter.address, adapter.port) == ("127.0.0.1", 50000)

    def test_connect_read_write(self, client, listener):
        accepted = accept_client(client, listener)
        accepted.sendall(b"telemetry")
        assert read_until(client, 9) == b"telemetry"
        assert client.write(b"command") is True
        assert recv_exact(accepted, 7) == b"command"
        accepted.close()

    def test_reconnects_after_remote_close(self, client, listener):
        accepted = accept_client(client, listener)
        accepted.close()
        assert wait_for(lambda: client.read(TIMEOUT) == b"" and client.connection is None)
        start = time.monotonic()
        accepted = accept_client(client, listener)
        assert time.monotonic() - start < RECONNECT_BOUND
        accepted.sendall(b"back")
        assert read_until(client, 4) == b"back"
        accepted.close()

    def test_connection_refused_then_success(self, caplog):
        caplog.set_level(logging.WARNING)
        port = free_port()
        adapter = TcpFastClientAdapter(tcp_fast_port=port)
        adapter.open()
        try:
            start = time.monotonic()
            assert adapter.read(TIMEOUT) == b""
            assert time.monotonic() - start < READ_BOUND
            assert adapter.connection is None
            # A refused connect is warned once, not once per retry (several retries happen in this window)
            end = time.monotonic() + TcpFastAdapter.RECONNECT_INTERVAL * 2.5
            while time.monotonic() < end:
                adapter.read(TIMEOUT)
            assert sum(1 for record in caplog.records if record.levelno == logging.WARNING) == 1
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as late:
                late.bind(("127.0.0.1", port))
                late.listen(1)
                late.settimeout(RECONNECT_BOUND)
                start = time.monotonic()
                accepted = accept_client(adapter, late)
                assert time.monotonic() - start < RECONNECT_BOUND
                accepted.close()
        finally:
            adapter.close()

    def test_refused_connect_backs_off(self, monkeypatch):
        adapter = TcpFastClientAdapter(tcp_fast_port=free_port())
        attempts = []
        real_begin = adapter.begin
        monkeypatch.setattr(adapter, "begin", lambda: attempts.append(time.monotonic()) or real_begin())
        adapter.open()
        try:
            assert adapter.read(TIMEOUT) == b""
            delay = adapter.next_attempt - time.monotonic()
            assert TcpFastAdapter.RECONNECT_INTERVAL * 0.5 < delay <= TcpFastAdapter.RECONNECT_INTERVAL
            end = time.monotonic() + TcpFastAdapter.RECONNECT_INTERVAL * 2.5
            while time.monotonic() < end:
                adapter.read(TIMEOUT)
            # About one attempt per RECONNECT_INTERVAL, not one per read
            assert 2 <= len(attempts) <= 4
        finally:
            adapter.close()

    def test_expired_connect_deadline_fails_and_retries(self, listener, monkeypatch, caplog):
        # Platform-independent variant of the backlog test: a connect still in progress past its deadline
        caplog.set_level(logging.WARNING)
        adapter = TcpFastClientAdapter(tcp_fast_port=listener.getsockname()[1])
        adapter.open()
        try:
            assert adapter.begin() is True
            monkeypatch.setattr(tcp_fast.select, "select", lambda *args: ([], [], []))
            adapter.pending_deadline = 0.0
            assert adapter.connect(TIMEOUT) is None
            assert adapter.pending is None and adapter.running
            assert 0 < adapter.next_attempt - time.monotonic() <= TcpFastAdapter.RECONNECT_INTERVAL
            assert any("timed out" in record.getMessage() for record in caplog.records)
        finally:
            adapter.close()

    @pytest.mark.skipif(sys.platform != "linux", reason="Relies on Linux dropping SYNs to a full backlog")
    def test_connect_timeout_gives_up_and_retries(self, monkeypatch, caplog):
        caplog.set_level(logging.WARNING)
        monkeypatch.setattr(TcpFastClientAdapter, "CONNECT_TIMEOUT", 0.2)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stalled:
            stalled.bind(("127.0.0.1", 0))
            stalled.listen(0)
            # Fill the backlog so further SYNs are silently dropped and a connect stays in progress
            fillers = []
            for _ in range(3):
                filler = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                filler.setblocking(False)
                filler.connect_ex(stalled.getsockname())
                fillers.append(filler)
            adapter = TcpFastClientAdapter(tcp_fast_port=stalled.getsockname()[1])
            adapter.open()
            try:
                end = time.monotonic() + 1.0
                while time.monotonic() < end and not caplog.records:
                    start = time.monotonic()
                    adapter.read(TIMEOUT)
                    assert time.monotonic() - start < READ_BOUND
                assert adapter.pending is None
                assert any("timed out" in record.getMessage() for record in caplog.records)
                assert adapter.running
                assert 0 < adapter.next_attempt - time.monotonic() <= TcpFastAdapter.RECONNECT_INTERVAL
            finally:
                adapter.close()
                for filler in fillers:
                    filler.close()

    def test_read_while_refused_never_exceeds_timeout(self):
        adapter = TcpFastClientAdapter(tcp_fast_port=free_port())
        adapter.open()
        try:
            end = time.monotonic() + RECONNECT_BOUND
            while time.monotonic() < end:
                start = time.monotonic()
                adapter.read(TIMEOUT)
                assert time.monotonic() - start < READ_BOUND
        finally:
            adapter.close()


class TestRead:
    """REQ-TCPF-003: return as soon as any bytes arrive; bounded idle wait"""

    def test_returns_immediately_on_data(self, server, peer):
        peer.sendall(b"x" * 1024)
        start = time.monotonic()
        # A long timeout: the only way to meet the bound is to return on data, not on expiry
        data = server.read(timeout=2.0)
        assert data
        assert time.monotonic() - start < READ_BOUND
        assert data + read_until(server, 1024 - len(data)) == b"x" * 1024

    def test_idle_read_bounded(self, server, peer):
        start = time.monotonic()
        assert server.read(TIMEOUT) == b""
        elapsed = time.monotonic() - start
        assert TIMEOUT * 0.5 <= elapsed < READ_BOUND

    def test_default_timeout_is_short(self, server, peer):
        assert TcpFastAdapter.READ_TIMEOUT == pytest.approx(0.050)
        start = time.monotonic()
        assert server.read() == b""
        elapsed = time.monotonic() - start
        assert TcpFastAdapter.READ_TIMEOUT * 0.5 <= elapsed < READ_BOUND

    def test_socket_error_drops_connection(self, server, peer, caplog):
        caplog.set_level(logging.WARNING)
        server.connection.close()  # a dead descriptor makes select/recv raise
        assert server.read(TIMEOUT) == b""
        assert server.connection is None
        assert any("socket error" in record.getMessage() for record in caplog.records)

    def test_fragmented_stream_preserved(self, server, peer):
        for chunk in (b"ab", b"cde", b"f"):
            peer.sendall(chunk)
            time.sleep(0.01)
        assert read_until(server, 6) == b"abcdef"

    def test_large_burst(self, server, peer):
        payload = bytes(range(256)) * 1024  # 256 KiB, larger than one recv
        peer.sendall(payload)
        assert read_until(server, len(payload)) == payload

    def test_connecting_read_stays_within_timeout(self, server):
        # The read() that accepts a peer must not spend a second full timeout waiting for data
        with socket.create_connection(("127.0.0.1", server.port), timeout=2.0):
            time.sleep(0.02)
            start = time.monotonic()
            assert server.read(TIMEOUT) == b""
            assert time.monotonic() - start < TIMEOUT * 1.5
            assert server.connection is not None

    def test_read_does_not_alter_write_blocking(self, server, peer):
        # A socket timeout used for reads would also apply to sendall; select must be used instead
        server.read(TIMEOUT)
        assert server.connection.gettimeout() is None


class TestWrite:
    """REQ-TCPF-005: sendall on success, immediate False otherwise"""

    def test_write_to_peer(self, server, peer):
        assert server.write(b"uplink") is True
        assert recv_exact(peer, 6) == b"uplink"

    def test_write_without_peer_is_false_and_fast(self, server):
        start = time.monotonic()
        assert server.write(b"nobody") is False
        assert time.monotonic() - start < 0.010

    def test_write_after_peer_gone_drops_connection(self, server, peer):
        peer.close()
        time.sleep(0.05)
        results = [server.write(b"x" * 65536) for _ in range(5)]
        assert False in results
        assert wait_for(lambda: server.connection is None or server.read(TIMEOUT) == b"" and server.connection is None)


class TestConnectionOptions:
    """REQ-TCPF-006: single socket, keepalive and nodelay on the connection, no threads"""

    def test_socket_options(self, server, peer):
        conn = server.connection
        assert conn.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) != 0
        assert conn.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) != 0

    def test_client_socket_options(self, client, listener):
        accepted = accept_client(client, listener)
        conn = client.connection
        assert conn.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) != 0
        assert conn.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) != 0
        accepted.close()

    @pytest.mark.skipif(not hasattr(socket, "TCP_KEEPINTVL"), reason="Keepalive timers not exposed on this platform")
    def test_keepalive_timers_are_short(self, server, peer):
        conn = server.connection
        idle_option = socket.TCP_KEEPIDLE if hasattr(socket, "TCP_KEEPIDLE") else socket.TCP_KEEPALIVE
        assert conn.getsockopt(socket.IPPROTO_TCP, idle_option) == TcpFastAdapter.KEEPALIVE_IDLE
        assert conn.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL) == TcpFastAdapter.KEEPALIVE_INTERVAL
        assert conn.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT) == TcpFastAdapter.KEEPALIVE_COUNT
        # Detection of a silent peer must take well under a minute, not the 2 h OS default
        detection = TcpFastAdapter.KEEPALIVE_IDLE + TcpFastAdapter.KEEPALIVE_INTERVAL * TcpFastAdapter.KEEPALIVE_COUNT
        assert detection <= 30

    def test_option_failure_drops_instead_of_raising(self, server):
        with socket.create_connection(("127.0.0.1", server.port), timeout=2.0):
            assert wait_for(lambda: len(select_readable(server.listener)) == 1)
            connection, _ = server.listener.accept()
            connection.close()  # a dead socket makes setsockopt raise
            assert server.established(connection) is False
            assert server.connection is None

    def test_no_threads_started(self, server, peer):
        before = threading.active_count()
        for _ in range(5):
            server.read(TIMEOUT)
            server.write(b"x")
        assert threading.active_count() == before


class TestClose:
    """REQ-TCPF-007: explicit close releases sockets and stops reconnection"""

    def test_close_releases_port(self):
        port = free_port()
        adapter = TcpFastServerAdapter(tcp_fast_port=port)
        adapter.open()
        adapter.close()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))

    def test_close_disconnects_peer(self, server, peer):
        server.close()
        assert recv_exact(peer, 1) == b""

    def test_after_close_no_reconnect(self, server, peer):
        server.close()
        assert server.read(TIMEOUT) == b""
        assert server.write(b"x") is False
        assert server.connection is None
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", server.port), timeout=0.5)

    def test_client_close_stops_retrying(self):
        port = free_port()
        adapter = TcpFastClientAdapter(tcp_fast_port=port)
        adapter.open()
        assert adapter.read(TIMEOUT) == b""  # refused, retry scheduled
        assert adapter.next_attempt > time.monotonic()
        adapter.close()
        assert adapter.pending is None and not adapter.running
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as late:
            late.bind(("127.0.0.1", port))
            late.listen(1)
            late.settimeout(0.3)
            end = time.monotonic() + RECONNECT_BOUND
            while time.monotonic() < end:
                assert adapter.read(TIMEOUT) == b""
            with pytest.raises(socket.timeout):
                late.accept()

    def test_client_close_mid_connect_releases_pending_socket(self, listener):
        adapter = TcpFastClientAdapter(tcp_fast_port=listener.getsockname()[1])
        adapter.open()
        assert adapter.begin() is True
        pending = adapter.pending
        adapter.close()
        assert adapter.pending is None
        assert pending.fileno() == -1

    def test_close_idempotent(self, server):
        server.close()
        server.close()

    def test_close_racing_established_closes_socket(self, server):
        # close() between connect() returning and established() storing must not leave a live socket
        with socket.create_connection(("127.0.0.1", server.port), timeout=2.0) as late:
            assert wait_for(lambda: len(select_readable(server.listener)) == 1)
            connection, _ = server.listener.accept()
            server.close()
            assert server.established(connection) is False
            assert server.connection is None
            assert recv_exact(late, 1) == b""

    def test_drop_unblocks_writer_stuck_in_sendall(self, server, peer):
        # The peer never reads, so a large write fills the window and blocks; drop() must release it
        results = []

        def writer():
            results.append(server.write(b"x" * (16 * 1024 * 1024)))

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        time.sleep(0.2)
        assert thread.is_alive()
        server.drop(server.connection, "test")
        thread.join(2.0)
        assert not thread.is_alive()
        assert results == [False]


class TestLogging:
    """REQ-TCPF-010: INFO on connect, one WARNING per outage"""

    def test_connect_logged(self, server, caplog):
        caplog.set_level(logging.INFO)
        with socket.create_connection(("127.0.0.1", server.port), timeout=2.0):
            assert wait_for(lambda: server.read(TIMEOUT) == b"" and server.connection is not None)
        assert any(record.levelno == logging.INFO and "connect" in record.getMessage().lower() for record in caplog.records)

    def warnings(self, caplog):
        return sum(1 for record in caplog.records if record.levelno == logging.WARNING)

    def test_disconnect_warned_once_per_outage(self, server, peer, caplog):
        caplog.set_level(logging.WARNING)
        peer.close()
        for _ in range(10):
            server.read(TIMEOUT)
            server.write(b"x")
        assert self.warnings(caplog) == 1
        # A new outage after a successful reconnect is warned again
        with socket.create_connection(("127.0.0.1", server.port), timeout=2.0):
            assert wait_for(lambda: server.read(TIMEOUT) == b"" and server.connection is not None)
        for _ in range(10):
            server.read(TIMEOUT)
        assert self.warnings(caplog) == 2


class TestPlugin:
    """REQ-TCPF-008: registration, shared flags, argument validation"""

    def test_names(self):
        assert TcpFastServerAdapter.get_name() == "tcp-fast-server"
        assert TcpFastClientAdapter.get_name() == "tcp-fast-client"

    def test_registered_builtin(self, plugin_system):
        classes = [plugin.plugin_class for plugin in plugin_system.get_plugins("communication")]
        assert TcpFastServerAdapter in classes
        assert TcpFastClientAdapter in classes
        assert TcpFastAdapter not in classes

    def test_dests_do_not_collide_with_ip(self):
        def dests(cls):
            return {spec["dest"] for spec in cls.get_arguments().values()}

        assert dests(TcpFastServerAdapter) == {"tcp_fast_address", "tcp_fast_port"}
        assert dests(TcpFastServerAdapter).isdisjoint(dests(IpAdapter))

    def test_shared_flags_identical(self):
        # The plugin CLI keeps the first spec for a duplicated flag, so both must declare the same spec
        assert TcpFastServerAdapter.get_arguments() == TcpFastClientAdapter.get_arguments()
        flags = {flag for flags in TcpFastServerAdapter.get_arguments() for flag in flags}
        assert flags == {"--tcp-fast-address", "--tcp-fast-port"}

    @pytest.mark.parametrize("port", [0, -1, 65536])
    def test_check_arguments_rejects_bad_port(self, port):
        with pytest.raises(ValueError):
            TcpFastClientAdapter.check_arguments(tcp_fast_address=None, tcp_fast_port=port)

    def test_check_arguments_accepts_client_any_port(self):
        TcpFastClientAdapter.check_arguments(tcp_fast_address="127.0.0.1", tcp_fast_port=1)

    def test_server_check_rejects_busy_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen(1)
            with pytest.raises(ValueError):
                TcpFastServerAdapter.check_arguments(tcp_fast_address="127.0.0.1", tcp_fast_port=busy.getsockname()[1])

    def test_server_check_accepts_free_port(self):
        TcpFastServerAdapter.check_arguments(tcp_fast_address="127.0.0.1", tcp_fast_port=free_port())

    def test_cli_binding_server(self, plugin_system):
        port = free_port()
        ParserBase.parse_args(
            [PluginArgumentParser(plugin_system)],
            arguments=["--communication-selection", "tcp-fast-server", "--tcp-fast-address", "127.0.0.1", "--tcp-fast-port", str(port)],
        )
        instance = plugin_system.get_selected_class("communication")()
        assert isinstance(instance, TcpFastServerAdapter)
        assert (instance.address, instance.port) == ("127.0.0.1", port)

    def test_cli_binding_client_default_address(self, plugin_system):
        ParserBase.parse_args(
            [PluginArgumentParser(plugin_system)],
            arguments=["--communication-selection", "tcp-fast-client", "--tcp-fast-port", "50001"],
        )
        instance = plugin_system.get_selected_class("communication")()
        assert isinstance(instance, TcpFastClientAdapter)
        assert (instance.address, instance.port) == ("127.0.0.1", 50001)

    def test_cli_rejects_busy_server_port(self, plugin_system):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen(1)
            with pytest.raises(SystemExit):
                ParserBase.parse_args(
                    [PluginArgumentParser(plugin_system)],
                    arguments=[
                        "--communication-selection",
                        "tcp-fast-server",
                        "--tcp-fast-address",
                        "127.0.0.1",
                        "--tcp-fast-port",
                        str(busy.getsockname()[1]),
                    ],
                )
