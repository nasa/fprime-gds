"""Tests for the tcp-fast-server and tcp-fast-client communication adapters

All tests use real loopback sockets on ephemeral ports. Timing assertions are deliberately loose (multiples of the
adapter's timeouts) so they hold on loaded CI hosts while still catching blocking or spinning regressions.
"""

import errno
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


class CloseOnFirstEnter:
    """Lock stand-in whose first acquisition runs adapter.close() first, landing it inside the guarded window"""

    def __init__(self, adapter):
        self.adapter, self.real, self.fired = adapter, adapter.lock, False

    def __enter__(self):
        if not self.fired:
            self.fired = True
            self.adapter.close()
        return self.real.__enter__()

    def __exit__(self, *exc):
        return self.real.__exit__(*exc)


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
    adapter = TcpFastServerAdapter(tcp_fast_address="127.0.0.1", tcp_fast_port=free_port())
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
        assert server.listener is not None
        assert server.listener.getsockname()[1] == server.port
        with socket.create_connection(("127.0.0.1", server.port), timeout=2.0):
            assert wait_for(lambda: server.read(TIMEOUT) == b"" and server.connection is not None)

    def test_listener_is_nonblocking_and_reusable(self, server):
        assert server.listener.getblocking() is False
        if sys.platform != "win32":
            assert server.listener.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) != 0

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

    @pytest.mark.parametrize("code", tcp_fast.ACCEPT_TRANSIENT)
    def test_transient_accept_error_keeps_listener(self, server, monkeypatch, caplog, code):
        caplog.set_level(logging.WARNING)
        listener = server.listener

        class Aborting:
            """Listener stand-in whose peer vanished between select and accept"""

            def fileno(self):
                return listener.fileno()

            def accept(self):
                raise OSError(code, "peer gone")

            def close(self):
                listener.close()

        server.listener = Aborting()
        monkeypatch.setattr(tcp_fast.select, "select", lambda *args: ([server.listener], [], []))
        assert server.connect(TIMEOUT) is None
        assert isinstance(server.listener, Aborting)  # not torn down
        assert server.next_attempt == 0.0 and not caplog.records

    def test_nothing_queued_accept_is_silent(self, server, monkeypatch, caplog):
        # A select that reports readiness with nothing queued makes the non-blocking accept raise EAGAIN
        caplog.set_level(logging.WARNING)
        listener = server.listener
        monkeypatch.setattr(tcp_fast.select, "select", lambda *args: ([listener], [], []))
        assert server.connect(TIMEOUT) is None
        assert server.listener is listener and server.next_attempt == 0.0 and not caplog.records

    def test_interrupted_accept_is_silent(self, server, monkeypatch, caplog):
        caplog.set_level(logging.WARNING)
        listener = server.listener

        class Interrupted:
            def fileno(self):
                return listener.fileno()

            def accept(self):
                raise InterruptedError()

            def close(self):
                listener.close()

        server.listener = Interrupted()
        monkeypatch.setattr(tcp_fast.select, "select", lambda *args: ([server.listener], [], []))
        assert server.connect(TIMEOUT) is None
        assert isinstance(server.listener, Interrupted) and server.next_attempt == 0.0 and not caplog.records

    @pytest.mark.parametrize("code", tcp_fast.ACCEPT_EXHAUSTED)
    def test_descriptor_exhaustion_paces_accepts(self, server, monkeypatch, caplog, code):
        # The peer stays queued, so the listener stays readable; retries must be paced, not a hot loop
        caplog.set_level(logging.WARNING)
        listener = server.listener

        class Starved:
            def fileno(self):
                return listener.fileno()

            def accept(self):
                raise OSError(code, "too many open files")

            def close(self):
                listener.close()

        server.listener = Starved()
        monkeypatch.setattr(tcp_fast.select, "select", lambda *args: ([server.listener], [], []))
        assert server.connect(TIMEOUT) is None
        assert isinstance(server.listener, Starved)  # not torn down
        assert server.next_attempt > time.monotonic()
        calls = 0
        end = time.monotonic() + TcpFastAdapter.RECONNECT_INTERVAL / 2
        while time.monotonic() < end:
            assert server.read(TIMEOUT) == b""
            calls += 1
        assert calls < TcpFastAdapter.RECONNECT_INTERVAL / TIMEOUT
        assert sum(1 for record in caplog.records if "accept failed" in record.getMessage()) == 1

    def test_fatal_accept_error_relistens(self, server, monkeypatch, caplog):
        caplog.set_level(logging.WARNING)
        listener = server.listener

        class Broken:
            def fileno(self):
                return listener.fileno()

            def accept(self):
                raise OSError(errno.EINVAL, "listener is not listening")

            def close(self):
                listener.close()

        server.listener = Broken()
        monkeypatch.setattr(tcp_fast.select, "select", lambda *args: ([server.listener], [], []))
        assert server.connect(TIMEOUT) is None
        assert server.listener is None and server.next_attempt > time.monotonic()
        assert any("accept failed" in record.getMessage() for record in caplog.records)

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

    def test_short_lived_connections_are_paced(self, listener, caplog):
        # A peer that accepts then immediately closes must not drive a connect/disconnect storm
        caplog.set_level(logging.INFO)
        adapter = TcpFastClientAdapter(tcp_fast_port=listener.getsockname()[1])
        adapter.open()
        listener.settimeout(0.0)
        try:
            end = time.monotonic() + TcpFastAdapter.RECONNECT_INTERVAL * 2.5
            while time.monotonic() < end:
                start = time.monotonic()
                adapter.read(TIMEOUT)
                assert time.monotonic() - start < READ_BOUND
                try:
                    listener.accept()[0].close()
                except (BlockingIOError, socket.timeout):
                    pass
            connects = sum(1 for record in caplog.records if "connected to" in record.getMessage())
            assert 1 <= connects <= 4  # about one per RECONNECT_INTERVAL
        finally:
            adapter.close()

    def test_long_lived_connection_reconnects_at_once(self, client, listener):
        accepted = accept_client(client, listener)
        client.next_attempt = 0.0  # as if the connection had outlived RECONNECT_INTERVAL
        accepted.close()
        assert wait_for(lambda: client.read(TIMEOUT) == b"" and client.connection is None)
        start = time.monotonic()
        accept_client(client, listener).close()
        assert time.monotonic() - start < TcpFastAdapter.RECONNECT_INTERVAL / 2

    def test_begin_socket_creation_failure_retries(self, monkeypatch, caplog):
        caplog.set_level(logging.WARNING)
        adapter = TcpFastClientAdapter(tcp_fast_port=free_port())
        adapter.open()

        def no_sockets(*args, **kwargs):
            raise OSError(errno.EMFILE, "too many open files")

        monkeypatch.setattr(tcp_fast.socket, "socket", no_sockets)
        assert adapter.begin() is None
        assert adapter.pending is None and adapter.next_attempt > time.monotonic()
        assert any("too many open files" in record.getMessage() for record in caplog.records)

    def test_begin_immediate_refusal_retries(self, monkeypatch, caplog):
        caplog.set_level(logging.WARNING)
        adapter = TcpFastClientAdapter(tcp_fast_port=free_port())
        adapter.open()
        created = []
        real_socket = socket.socket

        class Refused(real_socket):
            def connect_ex(self, address):
                created.append(self)
                return errno.ECONNREFUSED

        monkeypatch.setattr(tcp_fast.socket, "socket", Refused)
        assert adapter.begin() is None
        assert adapter.pending is None and adapter.next_attempt > time.monotonic()
        assert len(created) == 1 and created[0].fileno() == -1
        assert any("connection failed" in record.getMessage() for record in caplog.records)

    def test_connect_failure_reported_in_exceptional_set(self, monkeypatch, caplog):
        # Windows reports a failed non-blocking connect only in select's exceptional set, with the code in SO_ERROR
        caplog.set_level(logging.WARNING)
        adapter = TcpFastClientAdapter(tcp_fast_port=free_port())
        adapter.open()
        real_socket = socket.socket

        class WinSock(real_socket):
            def connect_ex(self, address):
                return tcp_fast.WSAEWOULDBLOCK

            def getsockopt(self, level, option, *args):
                return errno.ECONNREFUSED if option == socket.SO_ERROR else super().getsockopt(level, option, *args)

        monkeypatch.setattr(tcp_fast.socket, "socket", WinSock)
        try:
            pending = adapter.begin()
            assert pending is adapter.pending is not None  # WSAEWOULDBLOCK means in progress, not failure
            monkeypatch.setattr(tcp_fast.select, "select", lambda *args: ([], [], [pending]))
            assert adapter.connect(TIMEOUT) is None
            assert adapter.pending is None and pending.fileno() == -1
            assert adapter.next_attempt > time.monotonic()
            assert any("connection failed" in record.getMessage() for record in caplog.records)
        finally:
            adapter.close()

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

        def counted_begin():
            attempts.append(time.monotonic())
            return real_begin()

        monkeypatch.setattr(adapter, "begin", counted_begin)
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
            assert adapter.begin() is adapter.pending is not None
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
        assert time.monotonic() - start < TIMEOUT  # no select or sleep on the disconnected write path

    def test_write_after_peer_gone_drops_connection(self, server, peer):
        peer.close()
        time.sleep(0.05)
        results = [server.write(b"x" * 65536) for _ in range(5)]
        assert False in results
        assert wait_for(lambda: server.read(TIMEOUT) == b"" and server.connection is None)


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

    @pytest.mark.skipif(not hasattr(socket, "TCP_USER_TIMEOUT"), reason="TCP_USER_TIMEOUT not exposed on this platform")
    def test_unacknowledged_data_bounded_like_keepalive(self, server, peer):
        # Keepalive probes pause while data is in flight, so the user timeout must carry the same detection budget
        detection = TcpFastAdapter.KEEPALIVE_IDLE + TcpFastAdapter.KEEPALIVE_INTERVAL * TcpFastAdapter.KEEPALIVE_COUNT
        assert server.connection.getsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT) == detection * 1000

    def test_keepalive_tuning_failure_keeps_connection(self, server, monkeypatch, caplog):
        def reject(cls, connection):
            raise OSError("tuning unsupported")

        monkeypatch.setattr(TcpFastServerAdapter, "configure_keepalive", classmethod(reject))
        caplog.set_level(logging.WARNING)
        with socket.create_connection(("127.0.0.1", server.port), timeout=2.0) as sock:
            assert wait_for(lambda: server.read(TIMEOUT) == b"" and server.connection is not None)
            assert server.connection.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) != 0
            sock.sendall(b"still works")
            assert read_until(server, len(b"still works")) == b"still works"
        assert any("keepalive" in record.getMessage() for record in caplog.records)

    @staticmethod
    def platform_options(monkeypatch, present):
        """Make exactly `present` keepalive option names exist on the socket module, with a recording connection"""
        names = ("TCP_USER_TIMEOUT", "SIO_KEEPALIVE_VALS", "TCP_KEEPIDLE", "TCP_KEEPALIVE", "TCP_KEEPINTVL", "TCP_KEEPCNT")
        for name in names:
            if name in present:
                monkeypatch.setattr(tcp_fast.socket, name, name, raising=False)
            else:
                monkeypatch.delattr(tcp_fast.socket, name, raising=False)
        calls = []

        class Recording:
            def setsockopt(self, level, option, value):
                calls.append((option, value))

            def ioctl(self, control, option):
                calls.append((control, option))

        return Recording(), calls

    def test_keepalive_windows_branch(self, monkeypatch):
        connection, calls = self.platform_options(monkeypatch, {"SIO_KEEPALIVE_VALS"})
        TcpFastAdapter.configure_keepalive(connection)
        idle_ms, interval_ms = TcpFastAdapter.KEEPALIVE_IDLE * 1000, TcpFastAdapter.KEEPALIVE_INTERVAL * 1000
        assert calls == [("SIO_KEEPALIVE_VALS", (1, idle_ms, interval_ms))]

    def test_keepalive_macos_branch(self, monkeypatch):
        connection, calls = self.platform_options(monkeypatch, {"TCP_KEEPALIVE", "TCP_KEEPINTVL", "TCP_KEEPCNT"})
        TcpFastAdapter.configure_keepalive(connection)
        assert calls == [
            ("TCP_KEEPALIVE", TcpFastAdapter.KEEPALIVE_IDLE),
            ("TCP_KEEPINTVL", TcpFastAdapter.KEEPALIVE_INTERVAL),
            ("TCP_KEEPCNT", TcpFastAdapter.KEEPALIVE_COUNT),
        ]

    def test_keepalive_linux_branch(self, monkeypatch):
        connection, calls = self.platform_options(
            monkeypatch, {"TCP_USER_TIMEOUT", "TCP_KEEPIDLE", "TCP_KEEPINTVL", "TCP_KEEPCNT"}
        )
        TcpFastAdapter.configure_keepalive(connection)
        detection = TcpFastAdapter.KEEPALIVE_IDLE + TcpFastAdapter.KEEPALIVE_INTERVAL * TcpFastAdapter.KEEPALIVE_COUNT
        assert calls == [
            ("TCP_USER_TIMEOUT", detection * 1000),
            ("TCP_KEEPIDLE", TcpFastAdapter.KEEPALIVE_IDLE),
            ("TCP_KEEPINTVL", TcpFastAdapter.KEEPALIVE_INTERVAL),
            ("TCP_KEEPCNT", TcpFastAdapter.KEEPALIVE_COUNT),
        ]

    def test_option_failure_drops_instead_of_raising(self, server):
        with socket.create_connection(("127.0.0.1", server.port), timeout=2.0):
            assert wait_for(lambda: len(select_readable(server.listener)) == 1)
            connection, _ = server.listener.accept()
            connection.close()  # a dead socket makes setsockopt raise
            assert server.established(connection) is False
            assert server.connection is None

    @pytest.mark.parametrize("adapter_class", [TcpFastServerAdapter, TcpFastClientAdapter])
    def test_no_threads_started(self, adapter_class):
        # Baseline before construction, so threads started in __init__/open()/connect are caught too
        before = threading.active_count()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as remote:
            remote.bind(("127.0.0.1", 0))
            remote.listen(1)
            remote.settimeout(2.0)
            port = remote.getsockname()[1] if adapter_class is TcpFastClientAdapter else free_port()
            adapter = adapter_class(tcp_fast_address="127.0.0.1", tcp_fast_port=port)
            adapter.open()
            try:
                if adapter_class is TcpFastClientAdapter:
                    peer = accept_client(adapter, remote)
                else:
                    peer = socket.create_connection(("127.0.0.1", port), timeout=2.0)
                    assert wait_for(lambda: adapter.read(TIMEOUT) == b"" and adapter.connection is not None)
                with peer:
                    for _ in range(5):
                        adapter.read(TIMEOUT)
                        assert adapter.write(b"x") is True
                    assert threading.active_count() == before
            finally:
                adapter.close()
        assert threading.active_count() == before


class TestClose:
    """REQ-TCPF-007: explicit close releases sockets and stops reconnection"""

    def test_close_releases_port(self):
        port = free_port()
        adapter = TcpFastServerAdapter(tcp_fast_address="127.0.0.1", tcp_fast_port=port)
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
        # After close, read() still honors its bound rather than spinning
        start = time.monotonic()
        assert adapter.read(TIMEOUT) == b""
        assert TIMEOUT * 0.8 <= time.monotonic() - start < READ_BOUND
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
        pending = adapter.begin()
        assert pending is adapter.pending is not None
        adapter.close()
        assert adapter.pending is None
        assert pending.fileno() == -1

    def test_close_during_connect_select_is_silent(self, listener, monkeypatch, caplog):
        # close() from another thread while connect() waits in select must not warn or schedule a retry
        adapter = TcpFastClientAdapter(tcp_fast_port=listener.getsockname()[1])
        adapter.open()
        pending = adapter.begin()
        assert pending is adapter.pending is not None
        caplog.set_level(logging.WARNING)
        real_select = select.select

        def close_then_select(*args):
            adapter.close()  # the pending descriptor is now closed, so the real select raises
            return real_select(*args)

        monkeypatch.setattr(tcp_fast.select, "select", close_then_select)
        scheduled = adapter.next_attempt
        assert adapter.connect(TIMEOUT) is None
        assert adapter.next_attempt == scheduled  # no failure was recorded
        assert not [record for record in caplog.records if "connection failed" in record.getMessage()]
        assert pending.fileno() == -1

    def test_close_racing_listen_does_not_rebind(self, monkeypatch):
        # close() between the running check and listen() storing the socket must not leave the port bound
        port = free_port()
        adapter = TcpFastServerAdapter(tcp_fast_address="127.0.0.1", tcp_fast_port=port)
        adapter.open()
        adapter.listener.close()
        adapter.listener = None

        def close_then_proceed(timeout):
            adapter.close()
            return False

        monkeypatch.setattr(adapter, "waiting_for_retry", close_then_proceed)
        assert adapter.read(TIMEOUT) == b""
        assert adapter.listener is None
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))

    def test_close_racing_begin_does_not_keep_pending(self, listener, monkeypatch):
        adapter = TcpFastClientAdapter(tcp_fast_port=listener.getsockname()[1])
        adapter.open()
        created = []
        real_socket = socket.socket

        class Recording(real_socket):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created.append(self)

        monkeypatch.setattr(tcp_fast.socket, "socket", Recording)

        def close_then_proceed(timeout):
            adapter.close()
            return False

        monkeypatch.setattr(adapter, "waiting_for_retry", close_then_proceed)
        assert adapter.read(TIMEOUT) == b""
        assert adapter.pending is None and adapter.connection is None
        assert [sock.fileno() for sock in created] == [-1]  # the raced socket was closed, not leaked

    def test_stale_drop_keeps_newer_connection(self, server, peer, caplog):
        # A writer holding a snapshot of a dropped socket must not kill the connection read() re-established since
        caplog.set_level(logging.WARNING)
        stale = server.connection
        peer.close()
        assert wait_for(lambda: server.read(TIMEOUT) == b"" and server.connection is None)
        with socket.create_connection(("127.0.0.1", server.port), timeout=2.0) as second:
            assert wait_for(lambda: server.read(TIMEOUT) == b"" and server.connection is not None)
            current = server.connection
            server.drop(stale, "write failed: late")
            assert server.connection is current
            second.sendall(b"alive")
            assert read_until(server, 5) == b"alive"
        assert sum(1 for record in caplog.records if record.levelno == logging.WARNING) == 1

    def test_close_right_after_begin_is_silent(self, listener, monkeypatch, caplog):
        # close() between begin() publishing the socket and connect() using it must not raise or warn
        caplog.set_level(logging.WARNING)
        adapter = TcpFastClientAdapter(tcp_fast_port=listener.getsockname()[1])
        adapter.open()
        real_begin = adapter.begin

        scheduled = []

        def begin_then_close():
            pending = real_begin()
            scheduled.append(adapter.next_attempt)
            adapter.close()
            return pending

        monkeypatch.setattr(adapter, "begin", begin_then_close)
        assert adapter.read(TIMEOUT) == b""
        assert adapter.pending is None and adapter.next_attempt == scheduled[0]  # no failure was recorded
        assert not caplog.records

    def test_close_racing_fatal_accept_is_silent(self, server, monkeypatch, caplog):
        # close() landing as the fatal-accept branch takes the lock must not log an outage or schedule a retry
        caplog.set_level(logging.WARNING)
        listener = server.listener

        class Broken:
            def fileno(self):
                return listener.fileno()

            def accept(self):
                raise OSError(errno.EINVAL, "listener is not listening")

            def close(self):
                listener.close()

        server.listener = Broken()
        monkeypatch.setattr(tcp_fast.select, "select", lambda *args: ([server.listener], [], []))
        server.lock = CloseOnFirstEnter(server)
        assert server.connect(TIMEOUT) is None
        assert server.listener is None and server.next_attempt == 0.0 and not caplog.records

    def test_close_racing_connect_success_is_silent(self, listener, caplog):
        # close() landing as connect() claims the connected socket must hand the socket to close(), not read()
        caplog.set_level(logging.WARNING)
        adapter = TcpFastClientAdapter(tcp_fast_port=listener.getsockname()[1])
        adapter.open()
        pending = adapter.begin()
        assert wait_for(lambda: bool(select.select([], [pending], [], 0)[1]))
        adapter.lock = CloseOnFirstEnter(adapter)
        assert adapter.connect(TIMEOUT) is None
        assert adapter.pending is None and pending.fileno() == -1 and not caplog.records

    def test_close_idempotent(self, server):
        server.close()
        server.close()
        assert server.listener is None and server.connection is None and not server.running
        assert server.write(b"x") is False

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

    @pytest.mark.parametrize("adapter_class", [TcpFastServerAdapter, TcpFastClientAdapter])
    @pytest.mark.parametrize("port", [0, -1, 65536])
    def test_check_arguments_rejects_bad_port(self, adapter_class, port):
        with pytest.raises(ValueError, match="1-65535"):
            adapter_class.check_arguments(tcp_fast_address="127.0.0.1", tcp_fast_port=port)

    def test_check_arguments_accepts_client_any_port(self):
        TcpFastClientAdapter.check_arguments(tcp_fast_address="127.0.0.1", tcp_fast_port=1)

    def test_client_check_rejects_unresolvable_name(self, monkeypatch):
        def unresolvable(*_args, **_kwargs):
            raise socket.gaierror("Name or service not known")

        monkeypatch.setattr(tcp_fast.socket, "getaddrinfo", unresolvable)
        with pytest.raises(ValueError, match="Cannot resolve no-such-host"):
            TcpFastClientAdapter.check_arguments(tcp_fast_address="no-such-host", tcp_fast_port=50000)

    def test_client_re_resolves_hostname_after_failure(self, listener, monkeypatch):
        # A hostname is looked up again once an attempt fails, so a peer that changed address is found
        port = listener.getsockname()[1]
        dead_port = free_port()
        real_getaddrinfo = socket.getaddrinfo
        answers = [dead_port, port]

        def moving(host, *args, **kwargs):
            assert host == "fsw-board"
            answer = answers.pop(0) if len(answers) > 1 else answers[0]  # settle on the live port
            return real_getaddrinfo("127.0.0.1", answer, *args[1:], **kwargs)

        monkeypatch.setattr(tcp_fast.socket, "getaddrinfo", moving)
        adapter = TcpFastClientAdapter(tcp_fast_address="fsw-board", tcp_fast_port=port)
        adapter.open()
        try:
            assert adapter.target == ("127.0.0.1", dead_port)
            assert adapter.read(TIMEOUT) == b""  # refused at the stale address; re-resolved
            assert adapter.target == ("127.0.0.1", port)
            adapter.next_attempt = 0.0
            accept_client(adapter, listener).close()
        finally:
            adapter.close()

    def test_client_literal_address_is_not_re_resolved(self, monkeypatch):
        calls = []
        real_getaddrinfo = socket.getaddrinfo

        def counting(*args, **kwargs):
            calls.append(args)
            return real_getaddrinfo(*args, **kwargs)

        monkeypatch.setattr(tcp_fast.socket, "getaddrinfo", counting)
        adapter = TcpFastClientAdapter(tcp_fast_port=free_port())
        adapter.open()
        try:
            assert adapter.read(TIMEOUT) == b""  # refused
            assert len(calls) == 1
        finally:
            adapter.close()

    def test_client_open_tolerates_resolution_failure(self, listener, monkeypatch):
        # A lookup that fails at open() (e.g. DNS outage) falls back to the configured address, retried per attempt
        port = listener.getsockname()[1]

        def unavailable(*_args, **_kwargs):
            raise socket.gaierror("Temporary failure in name resolution")

        monkeypatch.setattr(tcp_fast.socket, "getaddrinfo", unavailable)
        adapter = TcpFastClientAdapter(tcp_fast_address="127.0.0.1", tcp_fast_port=port)
        adapter.open()
        monkeypatch.undo()
        try:
            assert adapter.target == ("127.0.0.1", port)
            accept_client(adapter, listener).close()
            assert adapter.connection is not None
        finally:
            adapter.close()

    def test_server_check_rejects_busy_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen(1)
            port = busy.getsockname()[1]
            with pytest.raises(ValueError, match=f"Cannot listen on 127.0.0.1:{port}"):
                TcpFastServerAdapter.check_arguments(tcp_fast_address="127.0.0.1", tcp_fast_port=port)

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

    def test_cli_rejects_busy_server_port(self, plugin_system, capsys):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen(1)
            with pytest.raises(SystemExit) as exit_info:
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
            assert exit_info.value.code != 0
            assert f"[ERROR] Failed to parse arguments: Cannot listen on 127.0.0.1:{busy.getsockname()[1]}" in capsys.readouterr().err
