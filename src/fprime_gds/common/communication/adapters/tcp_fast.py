"""
tcp_fast.py:

Lightweight TCP-only communication adapters for the F Prime comm-layer, provided as two plugins:

- `tcp-fast-server`: listens for the flight software (`Drv.TcpClient`) and serves one peer at a time.
- `tcp-fast-client`: connects to the flight software (`Drv.TcpServer`) and reconnects with a backoff.

Both share `TcpFastAdapter`, which owns a single connected socket and no threads of its own: the comm-layer's downlink
thread calls `read()` and its uplink thread calls `write()`. `read()` returns as soon as any bytes are available and
otherwise waits at most `timeout` (default 50ms), so the downlink loop is never held by a long read. A remote disconnect
or socket error drops the connection and the next `read()` re-accepts/reconnects; only an explicit `close()` stops
reconnection.

Portability notes: `select.select` is used on a single socket (works for sockets on Linux, macOS, and Windows; on POSIX
it cannot handle descriptor numbers >= 1024, which the comm process never approaches). The non-blocking client connect
handles both the POSIX `EINPROGRESS` and Windows `WSAEWOULDBLOCK` in-progress codes and checks select's exceptional set,
where Windows reports a failed connect. `SO_REUSEADDR` is set on POSIX only, where it is needed to re-listen through
TIME_WAIT and has the expected semantics.

@author lestarch
"""
import abc
import errno
import logging
import os
import select
import socket
import threading
import time

import fprime_gds.common.communication.adapters.base
from fprime_gds.plugin.definitions import gds_plugin_implementation

LOGGER = logging.getLogger("tcp_fast_adapter")

CONNECT_IN_PROGRESS = (errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EAGAIN, getattr(errno, "WSAEWOULDBLOCK", 10035))


class TcpFastAdapter(fprime_gds.common.communication.adapters.base.BaseAdapter, abc.ABC):
    """Shared implementation of the tcp-fast plugins: one socket, direct reads and writes, inline reconnection

    Subclasses provide `DEFAULT_ADDRESS`, `get_name`, and `connect()`, which performs one bounded step towards a
    connection (accept for the server, connect for the client) and returns the connected socket or None.
    """

    MAXIMUM_DATA_SIZE = 65536
    READ_TIMEOUT = 0.050
    RECONNECT_INTERVAL = 1.0
    DEFAULT_PORT = 50000
    DEFAULT_ADDRESS = None

    def __init__(self, tcp_fast_address=None, tcp_fast_port=DEFAULT_PORT):
        """Set up the adapter; no sockets are created until `open()`

        :param tcp_fast_address: bind (server) or connect (client) address; None selects the subclass default
        :param tcp_fast_port: TCP port
        """
        self.address = tcp_fast_address if tcp_fast_address is not None else self.DEFAULT_ADDRESS
        self.port = tcp_fast_port
        self.connection = None
        self.running = False
        self.warned = False
        self.lock = threading.Lock()

    def __repr__(self):
        """String representation for logging"""
        return f"{self.get_name()}[{self.address}:{self.port}]"

    def open(self):
        """Start the adapter; subsequent reads establish the connection"""
        self.running = True

    def close(self):
        """Stop the adapter and release the connection. Reads and writes afterwards do nothing."""
        self.running = False
        self.drop(None)

    def read(self, timeout=READ_TIMEOUT) -> bytes:
        """Return whatever bytes are available, waiting at most `timeout` for data or for a connection

        :param timeout: maximum time to wait when no data is available
        :return: received bytes, or b"" when nothing arrived within the timeout or the adapter is disconnected
        """
        connection = self.connection
        if connection is None:
            if not self.running:
                return b""
            connection = self.connect(timeout)
            if connection is None:
                return b""
            self.established(connection)
        try:
            readable, _, _ = select.select([connection], [], [], timeout)
            if not readable:
                return b""
            data = connection.recv(self.MAXIMUM_DATA_SIZE)
        except (OSError, ValueError) as error:
            self.drop(connection, f"socket error: {error}")
            return b""
        if not data:
            self.drop(connection, "peer closed the connection")
        return data

    def write(self, frame) -> bool:
        """Send the whole frame to the peer

        :param frame: bytes to send
        :return: True when fully sent, False immediately when disconnected or on error
        """
        connection = self.connection
        if connection is None:
            return False
        try:
            connection.sendall(frame)
            return True
        except (OSError, ValueError) as error:
            self.drop(connection, f"write failed: {error}")
            return False

    def established(self, connection):
        """Record a newly connected socket and apply the connection options"""
        connection.setblocking(True)
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        with self.lock:
            self.connection = connection
        self.warned = False
        try:
            peer = "%s:%d" % connection.getpeername()[:2]
        except OSError:
            peer = "unknown peer"
        LOGGER.info("%s connected to %s", self, peer)

    def drop(self, connection, reason=None):
        """Close `connection` and forget it, unless a newer connection has replaced it. `None` drops whatever is held."""
        with self.lock:
            if connection is None:
                connection = self.connection
            current = self.connection is connection
            if current:
                self.connection = None
        if connection is None:
            return
        try:
            connection.close()
        except OSError:
            pass
        if current and reason is not None:
            self.warn("%s disconnected: %s", self, reason)

    def warn(self, message, *args):
        """Log a warning once per outage"""
        if not self.warned:
            LOGGER.warning(message, *args)
            self.warned = True

    @abc.abstractmethod
    def connect(self, timeout):
        """Take one step towards a connection, waiting at most `timeout`; return the connected socket or None"""

    @classmethod
    def get_arguments(cls):
        """Command line arguments shared by both plugins (identical specs, since the CLI merges duplicated flags)"""
        return {
            ("--tcp-fast-address",): {
                "dest": "tcp_fast_address",
                "type": str,
                "default": None,
                "help": "Address to bind (tcp-fast-server, default 0.0.0.0) or connect to (tcp-fast-client, "
                "default 127.0.0.1).",
            },
            ("--tcp-fast-port",): {
                "dest": "tcp_fast_port",
                "type": int,
                "default": TcpFastAdapter.DEFAULT_PORT,
                "help": f"TCP port to listen on or connect to. Default: {TcpFastAdapter.DEFAULT_PORT}",
            },
        }

    @classmethod
    def check_arguments(cls, tcp_fast_address=None, tcp_fast_port=DEFAULT_PORT):
        """Validate the command line arguments, raising ValueError on failure"""
        if not 0 < tcp_fast_port < 65536:
            raise ValueError(f"Port {tcp_fast_port} is not in the range 1-65535")


class TcpFastServerAdapter(TcpFastAdapter):
    """TCP server adapter: listens for one flight-software peer at a time"""

    DEFAULT_ADDRESS = "0.0.0.0"

    def __init__(self, tcp_fast_address=None, tcp_fast_port=TcpFastAdapter.DEFAULT_PORT):
        super().__init__(tcp_fast_address, tcp_fast_port)
        self.listener = None

    def open(self):
        """Bind and listen"""
        self.listener = self.listening_socket(self.address, self.port)
        super().open()

    def close(self):
        """Release the connection and the listening socket"""
        super().close()
        listener, self.listener = self.listener, None
        if listener is not None:
            listener.close()

    def connect(self, timeout):
        """Accept a pending peer if one arrives within `timeout`"""
        listener = self.listener
        if listener is None:
            return None
        try:
            readable, _, _ = select.select([listener], [], [], timeout)
            if not readable:
                return None
            connection, _ = listener.accept()
            return connection
        except (OSError, ValueError) as error:
            self.warn("%s accept failed: %s", self, error)
            return None

    @staticmethod
    def listening_socket(address, port):
        """Create a bound, listening socket"""
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name != "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((address, port))
            listener.listen(1)
        except OSError:
            listener.close()
            raise
        return listener

    @classmethod
    def check_arguments(cls, tcp_fast_address=None, tcp_fast_port=TcpFastAdapter.DEFAULT_PORT):
        """Validate the port range and that the address:port can be bound"""
        super().check_arguments(tcp_fast_address, tcp_fast_port)
        address = tcp_fast_address if tcp_fast_address is not None else cls.DEFAULT_ADDRESS
        try:
            cls.listening_socket(address, tcp_fast_port).close()
        except OSError as error:
            raise ValueError(f"Cannot listen on {address}:{tcp_fast_port}: {error}")

    @classmethod
    def get_name(cls):
        """Plugin name"""
        return "tcp-fast-server"

    @classmethod
    @gds_plugin_implementation
    def register_communication_plugin(cls):
        """Register this as a plugin"""
        return cls


class TcpFastClientAdapter(TcpFastAdapter):
    """TCP client adapter: connects to a flight-software TcpServer, reconnecting with a backoff"""

    DEFAULT_ADDRESS = "127.0.0.1"
    CONNECT_TIMEOUT = 5.0

    def __init__(self, tcp_fast_address=None, tcp_fast_port=TcpFastAdapter.DEFAULT_PORT):
        super().__init__(tcp_fast_address, tcp_fast_port)
        self.pending = None
        self.pending_deadline = 0.0
        self.next_attempt = 0.0

    def close(self):
        """Release the connection and any in-progress connect"""
        super().close()
        self.abandon()

    def connect(self, timeout):
        """Advance a non-blocking connect by at most `timeout`; return the socket once connected"""
        now = time.monotonic()
        if self.pending is None:
            if now < self.next_attempt:
                time.sleep(min(timeout, self.next_attempt - now))
                return None
            if not self.begin():
                return None
        try:
            _, writable, failed = select.select([], [self.pending], [self.pending], timeout)
            if not writable and not failed:
                if time.monotonic() > self.pending_deadline:
                    self.fail("connect timed out")
                return None
            error = self.pending.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        except (OSError, ValueError) as exception:
            self.fail(str(exception))
            return None
        if error != 0:
            self.fail(os.strerror(error))
            return None
        connection, self.pending = self.pending, None
        return connection

    def begin(self):
        """Start a non-blocking connect"""
        pending = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        pending.setblocking(False)
        try:
            code = pending.connect_ex((self.address, self.port))
        except OSError as error:
            pending.close()
            self.fail(str(error))
            return False
        if code != 0 and code not in CONNECT_IN_PROGRESS:
            pending.close()
            self.fail(os.strerror(code))
            return False
        self.pending = pending
        self.pending_deadline = time.monotonic() + self.CONNECT_TIMEOUT
        return True

    def fail(self, reason):
        """Give up on the in-progress connect and schedule the next attempt"""
        self.abandon()
        self.next_attempt = time.monotonic() + self.RECONNECT_INTERVAL
        self.warn("%s connection failed: %s (retrying every %.1fs)", self, reason, self.RECONNECT_INTERVAL)

    def abandon(self):
        """Close any in-progress connect"""
        pending, self.pending = self.pending, None
        if pending is not None:
            pending.close()

    @classmethod
    def get_name(cls):
        """Plugin name"""
        return "tcp-fast-client"

    @classmethod
    @gds_plugin_implementation
    def register_communication_plugin(cls):
        """Register this as a plugin"""
        return cls
