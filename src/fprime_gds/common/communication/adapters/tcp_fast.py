"""
tcp_fast.py:

Lightweight TCP-only communication adapters for the F Prime comm-layer, provided as two plugins:

- `tcp-fast-server`: listens for the flight software (`Drv.TcpClient`) and serves one peer at a time.
- `tcp-fast-client`: connects to the flight software (`Drv.TcpServer`) and retries at a fixed interval.

Both share `TcpFastAdapter`, which owns a single connected socket and no threads of its own: the comm-layer's downlink
thread calls `read()` and its uplink thread calls `write()`. `read()` returns as soon as any bytes are available and
otherwise waits at most `timeout` (default 50ms), so the downlink loop is never held by a long read. A remote disconnect
or socket error drops the connection and the next `read()` re-accepts/reconnects; a failed listen is retried the same
way. Only an explicit `close()` stops reconnection. Silent peer loss (power cycle, cable pull) on an idle connection is
detected by TCP keepalive probes configured for a few seconds rather than the OS default of about two hours. Keepalive
probes are suppressed while data is in flight, so on Linux `TCP_USER_TIMEOUT` bounds unacknowledged sends (and a peer
that stops reading) to the same budget; elsewhere a blocked `sendall` lasts until the OS retransmit limit.

Portability notes: `select.select` is used on a single socket (works for sockets on Linux, macOS, and Windows; on POSIX
it cannot handle descriptor numbers >= 1024, which the comm process never approaches). The non-blocking client connect
handles both the POSIX `EINPROGRESS` and Windows `WSAEWOULDBLOCK` in-progress codes and checks select's exceptional set,
where Windows reports a failed connect. `SO_REUSEADDR` is set on POSIX only, where it is needed to re-listen through
TIME_WAIT and has the expected semantics. Keepalive timers use `TCP_KEEPIDLE`/`TCP_KEEPALIVE`, `TCP_KEEPINTVL`, and
`TCP_KEEPCNT` where exposed and `SIO_KEEPALIVE_VALS` on Windows (whose probe count is fixed at 10).

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

# WinSock reports a non-blocking connect in progress as WSAEWOULDBLOCK, which errno only defines on Windows
WSAEWOULDBLOCK = 10035
CONNECT_IN_PROGRESS = (errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EAGAIN, WSAEWOULDBLOCK)
# accept(2) errors that concern the one peer (or descriptor exhaustion), not the listening socket
ACCEPT_TRANSIENT = (
    errno.ECONNABORTED,
    errno.EPROTO,
    errno.EHOSTUNREACH,
    errno.ENETUNREACH,
    errno.EMFILE,
    errno.ENFILE,
)


class TcpFastAdapter(fprime_gds.common.communication.adapters.base.BaseAdapter, abc.ABC):
    """Shared implementation of the tcp-fast plugins: one socket, direct reads and writes, inline reconnection

    Subclasses provide `DEFAULT_ADDRESS`, `get_name`, and `connect()`, which performs one bounded step towards a
    connection (accept for the server, connect for the client) and returns the connected socket or None.
    """

    MAXIMUM_DATA_SIZE = 65536
    READ_TIMEOUT = 0.050
    RECONNECT_INTERVAL = 1.0
    # Keepalive probes start after KEEPALIVE_IDLE seconds of silence; a silent peer is dropped after
    # KEEPALIVE_IDLE + KEEPALIVE_INTERVAL * KEEPALIVE_COUNT seconds (8 s with these values, 15 s on Windows)
    KEEPALIVE_IDLE = 5
    KEEPALIVE_INTERVAL = 1
    KEEPALIVE_COUNT = 3
    DEFAULT_PORT = 50000
    DEFAULT_ADDRESS = None

    def __init__(self, tcp_fast_address=None, tcp_fast_port=DEFAULT_PORT):
        """Set up the adapter; no sockets are created until `open()`

        :param tcp_fast_address: bind (server) or connect (client) address; None selects the subclass default
        :param tcp_fast_port: TCP port
        """
        self.address = self.default_address(tcp_fast_address)
        self.port = tcp_fast_port
        self.connection = None
        self.running = False
        self.warned = False
        self.next_attempt = 0.0
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
        self.drop(self.connection)

    def read(self, timeout=READ_TIMEOUT) -> bytes:
        """Return whatever bytes are available, waiting at most `timeout` for data or for a connection

        :param timeout: maximum time to wait when no data is available
        :return: received bytes, or b"" when nothing arrived within the timeout or the adapter is disconnected
        """
        connection = self.connection
        if connection is None:
            if not self.running:
                time.sleep(timeout)  # honor the bound so a caller still looping after close() does not spin
                return b""
            connection = self.connect(timeout)
            if connection is not None:
                self.established(connection)
            # The connect step has spent the caller's budget; data is picked up by the next read
            return b""
        try:
            readable, _, _ = select.select([connection], [], [], timeout)
            if not readable:
                return b""
            data = connection.recv(self.MAXIMUM_DATA_SIZE)
        except (OSError, ValueError) as error:  # select raises ValueError on a socket closed concurrently (fd -1)
            self.drop(connection, f"socket error: {error}")
            return b""
        if not data:
            self.drop(connection, "peer closed the connection")
        return data

    def write(self, frame) -> bool:
        """Send the whole frame to the peer

        True means the kernel accepted the frame, not that the peer received it. A peer that stops draining blocks
        `sendall` until the send buffer frees or the kernel abandons the connection (`TCP_USER_TIMEOUT` on Linux,
        the retransmit limit elsewhere), after which the error drops the connection and read() reconnects.

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
        """Configure and record a newly connected socket; returns False (socket closed) on failure or after close()"""
        try:
            connection.setblocking(True)
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            host, port = connection.getpeername()[:2]
            peer = f"{host}:{port}"
        except OSError as error:
            self.close_socket(connection)
            self.warn("%s disconnected: failed to configure socket: %s", self, error)
            return False
        try:
            self.configure_keepalive(connection)
        except OSError as error:
            # Tuning is best-effort: the link works with the OS default schedule, only silent-peer detection is slower
            LOGGER.warning("%s using OS default keepalive timers: %s", self, error)
        with self.lock:
            if not self.running:
                self.close_socket(connection)
                return False
            self.connection = connection
        self.warned = False
        LOGGER.info("%s connected to %s", self, peer)
        return True

    @classmethod
    def configure_keepalive(cls, connection):
        """Shorten the keepalive probe schedule so a silent peer is detected in seconds"""
        detection_ms = (cls.KEEPALIVE_IDLE + cls.KEEPALIVE_INTERVAL * cls.KEEPALIVE_COUNT) * 1000
        # Probes only run on an idle socket; on Linux bound unacknowledged sends and zero-window stalls the same way
        if hasattr(socket, "TCP_USER_TIMEOUT"):
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, detection_ms)
        if hasattr(socket, "SIO_KEEPALIVE_VALS"):
            connection.ioctl(
                socket.SIO_KEEPALIVE_VALS, (1, cls.KEEPALIVE_IDLE * 1000, cls.KEEPALIVE_INTERVAL * 1000)
            )
            return
        # Linux names the idle option TCP_KEEPIDLE; macOS names it TCP_KEEPALIVE
        if hasattr(socket, "TCP_KEEPIDLE"):
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, cls.KEEPALIVE_IDLE)
        elif hasattr(socket, "TCP_KEEPALIVE"):
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, cls.KEEPALIVE_IDLE)
        if hasattr(socket, "TCP_KEEPINTVL"):
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, cls.KEEPALIVE_INTERVAL)
        if hasattr(socket, "TCP_KEEPCNT"):
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, cls.KEEPALIVE_COUNT)

    @staticmethod
    def close_socket(connection):
        """Shut down then close a socket, so a thread blocked in sendall/recv on it is released"""
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            connection.close()
        except OSError:
            pass

    def drop(self, connection, reason=None):
        """Close `connection` and forget it, unless a newer connection has replaced it; warn when `reason` is given"""
        if connection is None:
            return
        with self.lock:
            current = self.connection is connection
            if current:
                self.connection = None
        self.close_socket(connection)
        if current and reason is not None:
            self.warn("%s disconnected: %s", self, reason)

    def warn(self, message, *args):
        """Log a warning once per outage"""
        if not self.warned:
            LOGGER.warning(message, *args)
            self.warned = True

    def waiting_for_retry(self, timeout):
        """True while the next connection attempt is not yet due, sleeping at most `timeout` of the remaining wait"""
        remaining = self.next_attempt - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(timeout, remaining))
        return True

    def retry_later(self, reason):
        """Warn once and schedule the next connection attempt"""
        self.next_attempt = time.monotonic() + self.RECONNECT_INTERVAL
        self.warn("%s %s (retrying every %.1fs)", self, reason, self.RECONNECT_INTERVAL)

    @abc.abstractmethod
    def connect(self, timeout):
        """Take one step towards a connection, waiting at most `timeout`; return the connected socket or None"""

    @classmethod
    def default_address(cls, tcp_fast_address):
        """The configured address, or the subclass default when the shared flag was not given"""
        return tcp_fast_address if tcp_fast_address is not None else cls.DEFAULT_ADDRESS

    @classmethod
    def get_arguments(cls):
        """Command line arguments shared by both plugins (identical specs; the CLI keeps the first registration of a flag)"""
        return {
            ("--tcp-fast-address",): {
                "dest": "tcp_fast_address",
                "type": str,
                "default": None,
                "help": "Address to bind (tcp-fast-server) or connect to (tcp-fast-client). Shared by both tcp-fast "
                "plugins; when unset the server binds 0.0.0.0 (all interfaces, unauthenticated; prefer 127.0.0.1 "
                "when the deployment runs locally) and the client connects to 127.0.0.1.",
            },
            ("--tcp-fast-port",): {
                "dest": "tcp_fast_port",
                "type": int,
                "default": TcpFastAdapter.DEFAULT_PORT,
                "help": "TCP port to listen on (tcp-fast-server) or connect to (tcp-fast-client). Shared by both "
                "tcp-fast plugins.",
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
        """Start listening; a failed listen is retried from read()"""
        super().open()
        self.listen()

    def close(self):
        """Release the connection and the listening socket"""
        super().close()
        listener, self.listener = self.listener, None
        if listener is not None:
            listener.close()

    def listen(self):
        """Create the listening socket, scheduling a retry on failure; returns the listener or None"""
        try:
            listener = self.listening_socket(self.address, self.port)
        except OSError as error:
            self.retry_later(f"cannot listen: {error}")
            return None
        with self.lock:
            if self.running:
                self.listener = listener
                return listener
        listener.close()  # close() won the race; do not leave the port bound
        return None

    def connect(self, timeout):
        """Accept a pending peer if one arrives within `timeout`, re-listening first if the listener was lost"""
        listener = self.listener
        if listener is None:
            if self.waiting_for_retry(timeout):
                return None
            listener = self.listen()
            if listener is None:
                return None
        try:
            readable, _, _ = select.select([listener], [], [], timeout)
            if not readable:
                return None
            connection, _ = listener.accept()
            return connection
        except (BlockingIOError, InterruptedError):
            return None  # peer aborted between select and accept
        except (OSError, ValueError) as error:
            if isinstance(error, OSError) and error.errno in ACCEPT_TRANSIENT:
                return None  # this peer is gone or descriptors are short; the listener is fine
            # A listener released by a concurrent close() fails the same way; that is not an outage
            if self.listener is listener:
                self.listener = None
                listener.close()
                self.retry_later(f"accept failed: {error}")
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
            listener.setblocking(False)  # accept() must not block past the select that reported the peer
        except OSError:
            listener.close()
            raise
        return listener

    @classmethod
    def check_arguments(cls, tcp_fast_address=None, tcp_fast_port=TcpFastAdapter.DEFAULT_PORT):
        """Validate the port range and that the address:port can be bound"""
        super().check_arguments(tcp_fast_address, tcp_fast_port)
        address = cls.default_address(tcp_fast_address)
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
    """TCP client adapter: connects to a flight-software TcpServer, retrying every RECONNECT_INTERVAL"""

    DEFAULT_ADDRESS = "127.0.0.1"
    CONNECT_TIMEOUT = 5.0

    def __init__(self, tcp_fast_address=None, tcp_fast_port=TcpFastAdapter.DEFAULT_PORT):
        super().__init__(tcp_fast_address, tcp_fast_port)
        self.pending = None
        self.pending_deadline = 0.0
        self.target = (self.address, self.port)

    def open(self):
        """Resolve the target up front so successful connects never do a name lookup on the read thread"""
        super().open()
        self.resolve()

    def resolve(self):
        """Look up the configured address; on failure connect_ex resolves it itself on the next attempt"""
        try:
            self.target = socket.getaddrinfo(self.address, self.port, socket.AF_INET, socket.SOCK_STREAM)[0][4]
        except (OSError, IndexError):
            self.target = (self.address, self.port)

    def close(self):
        """Release the connection and any in-progress connect"""
        super().close()
        self.abandon()

    def connect(self, timeout):
        """Advance a non-blocking connect by at most `timeout`; return the socket once connected"""
        if self.pending is None:
            if self.waiting_for_retry(timeout):
                return None
            if not self.begin():
                return None
        pending = self.pending  # local snapshot: a concurrent close() may clear self.pending
        try:
            _, writable, failed = select.select([], [pending], [pending], timeout)
            if not writable and not failed:
                if time.monotonic() > self.pending_deadline:
                    self.fail("connect timed out")
                return None
            error = pending.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        except (OSError, ValueError) as exception:
            if self.pending is pending:  # not abandoned by close()
                self.fail(str(exception))
            return None
        if error != 0:
            self.fail(os.strerror(error))
            return None
        if self.pending is not pending:
            return None  # abandoned by close() while connecting
        self.pending = None
        return pending

    def begin(self):
        """Start a non-blocking connect"""
        pending = None
        try:
            pending = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            pending.setblocking(False)
            code = pending.connect_ex(self.target)
        except OSError as error:
            if pending is not None:
                pending.close()
            self.fail(str(error))
            return False
        if code != 0 and code not in CONNECT_IN_PROGRESS:
            pending.close()
            self.fail(os.strerror(code))
            return False
        with self.lock:
            if self.running:
                self.pending = pending
                self.pending_deadline = time.monotonic() + self.CONNECT_TIMEOUT
                return True
        pending.close()  # close() won the race
        return False

    def fail(self, reason):
        """Give up on the in-progress connect and schedule the next attempt"""
        self.abandon()
        self.retry_later(f"connection failed: {reason}")
        if not self.literal_address():
            self.resolve()  # a hostname may have moved (e.g. new DHCP lease); attempts are >= RECONNECT_INTERVAL apart

    def literal_address(self):
        """True when the configured address is a dotted IPv4 literal and needs no lookup"""
        try:
            socket.inet_aton(self.address)
            return True
        except OSError:
            return False

    def abandon(self):
        """Close any in-progress connect"""
        pending, self.pending = self.pending, None
        if pending is not None:
            pending.close()

    @classmethod
    def check_arguments(cls, tcp_fast_address=None, tcp_fast_port=TcpFastAdapter.DEFAULT_PORT):
        """Validate the port range and that the address resolves, so a bad name fails at startup, not on the read thread"""
        super().check_arguments(tcp_fast_address, tcp_fast_port)
        address = cls.default_address(tcp_fast_address)
        try:
            socket.getaddrinfo(address, tcp_fast_port, socket.AF_INET, socket.SOCK_STREAM)
        except OSError as error:
            raise ValueError(f"Cannot resolve {address}: {error}")

    @classmethod
    def get_name(cls):
        """Plugin name"""
        return "tcp-fast-client"

    @classmethod
    @gds_plugin_implementation
    def register_communication_plugin(cls):
        """Register this as a plugin"""
        return cls
