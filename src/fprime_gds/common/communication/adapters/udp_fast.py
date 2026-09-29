"""
udp_fast.py:

Lightweight UDP communication adapter for the F Prime comm-layer, provided as the `udp-fast` plugin. It exchanges
one datagram per call with a single peer: `write()` sends the frame as one datagram to the peer's address and port,
`read()` returns one received datagram. Datagram boundaries are preserved end to end, so a datagram is a packet.

The adapter owns no threads: the comm-layer's downlink thread calls `read()` and its uplink thread calls `write()`.
`read()` waits at most `timeout` (default 50ms) on the receive socket with `select`. Datagrams from sources other than
the peer address, loopback, and any configured extra sources are dropped, since a UDP port is unauthenticated. A
receive socket that cannot be bound (port busy) is retried from `read()`; only an explicit `close()` stops retrying.

Beyond `comm.py`, this adapter is the ground-system side of `fprime-comm-bridge` (YAMCS or OpenC3 COSMOS UDP links).

@author lestarch
"""

import logging
import select
import socket
import threading
import time

import fprime_gds.common.communication.adapters.base
from fprime_gds.plugin.definitions import gds_plugin_implementation

LOGGER = logging.getLogger("udp_fast_adapter")


class UdpFastAdapter(fprime_gds.common.communication.adapters.base.BaseAdapter):
    """UDP adapter: one datagram per read and per write, no threads, source-filtered receive"""

    MAXIMUM_DATA_SIZE = 65535
    READ_TIMEOUT = 0.050
    RECONNECT_INTERVAL = 1.0
    DEFAULT_ADDRESS = "127.0.0.1"
    DEFAULT_BIND_ADDRESS = "127.0.0.1"
    DEFAULT_SEND_PORT = 50000
    DEFAULT_RECV_PORT = 50001
    LOOPBACK_ADDRESS = "127.0.0.1"

    def __init__(
        self,
        udp_fast_address=DEFAULT_ADDRESS,
        udp_fast_send_port=DEFAULT_SEND_PORT,
        udp_fast_recv_port=DEFAULT_RECV_PORT,
        udp_fast_bind_address=DEFAULT_BIND_ADDRESS,
        udp_fast_allowed_sources=None,
    ):
        """Set up the adapter; no sockets are created and no names are resolved until `open()`

        :param udp_fast_address: peer address datagrams are sent to; also an accepted source
        :param udp_fast_send_port: peer port datagrams are sent to
        :param udp_fast_recv_port: local port bound to receive datagrams
        :param udp_fast_bind_address: local address bound to receive datagrams
        :param udp_fast_allowed_sources: extra source hosts accepted besides the peer address and loopback
        """
        self.address = udp_fast_address
        self.send_port = udp_fast_send_port
        self.recv_port = udp_fast_recv_port
        self.bind_address = udp_fast_bind_address
        self.extra_sources = list(udp_fast_allowed_sources or [])
        self.destination = (self.address, self.send_port)
        self.allowed_sources = set()
        self.warned_sources = set()
        self.send_socket = None
        self.recv_socket = None
        self.running = False
        self.warned = False
        self.next_attempt = 0.0
        self.lock = threading.Lock()

    def __repr__(self):
        """String representation for logging"""
        return f"{self.get_name()}[to {self.address}:{self.send_port}, on {self.bind_address}:{self.recv_port}]"

    def open(self):
        """Resolve the peer and accepted sources, create the send socket, and bind the receive socket

        Names are resolved here so the read and write paths never do a lookup. A receive port that cannot be bound
        is not an error: binding is retried from `read()` every RECONNECT_INTERVAL.

        :raises OSError: when the peer or an allowed source cannot be resolved
        """
        self.close()  # a reopen must not leak the previous sockets
        self.destination = (socket.gethostbyname(self.address), self.send_port)
        self.allowed_sources = {
            socket.gethostbyname(source)
            for source in {self.address, self.LOOPBACK_ADDRESS, *self.extra_sources}
        }
        self.warned_sources = set()
        with self.lock:
            self.running = True
            self.send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.bind()

    def close(self):
        """Stop the adapter and release both sockets; later reads sleep their timeout and return b"", writes return False"""
        with self.lock:  # same lock as the stores, so a socket cannot be stored after running goes False
            self.running = False
            send_socket, self.send_socket = self.send_socket, None
            recv_socket, self.recv_socket = self.recv_socket, None
        for closing in (send_socket, recv_socket):
            if closing is not None:
                closing.close()

    def read(self, timeout=READ_TIMEOUT) -> bytes:
        """Return one received datagram, waiting at most `timeout` for it or for the receive socket to bind

        :param timeout: maximum time to wait when no datagram is available
        :return: one datagram, or b"" when none arrived within the timeout, the sender is not an accepted source,
                 or the adapter is closed
        """
        recv_socket = self.recv_socket
        if recv_socket is None:
            if not self.running:
                time.sleep(timeout)  # honor the bound so a caller still looping after close() does not spin
                return b""
            if self.waiting_for_retry(timeout):
                return b""
            self.bind()
            return b""  # the bind step has spent the caller's budget; data is picked up by the next read
        try:
            readable, _, _ = select.select([recv_socket], [], [], timeout)
            if not readable:
                return b""
            datagram, source = recv_socket.recvfrom(self.MAXIMUM_DATA_SIZE)
        except ConnectionResetError:
            return b""  # Windows reports a peer's ICMP port-unreachable here; the socket itself is fine
        except (OSError, ValueError) as error:  # select raises ValueError on a socket closed concurrently (fd -1)
            self.drop(recv_socket, f"receive failed: {error}")
            return b""
        if source[0] not in self.allowed_sources:
            if source[0] not in self.warned_sources:
                self.warned_sources.add(source[0])
                LOGGER.warning("%s dropping datagrams from unexpected source %s", self, source[0])
            return b""
        return datagram

    def write(self, frame) -> bool:
        """Send the whole frame as one datagram to the peer

        True means the kernel accepted the datagram, not that the peer received it.

        :param frame: bytes to send
        :return: True when sent, False immediately when closed or on error (e.g. the frame exceeds the datagram size)
        """
        send_socket = self.send_socket
        if send_socket is None:
            return False
        try:
            send_socket.sendto(frame, self.destination)
        except (OSError, ValueError) as error:
            self.warn("%s send failed: %s", self, error)
            return False
        self.warned = False
        return True

    def bind(self):
        """Create the receive socket, scheduling a retry on failure; returns the socket or None"""
        try:
            recv_socket = self.receiving_socket(self.bind_address, self.recv_port)
        except OSError as error:
            self.retry_later(f"cannot bind {self.bind_address}:{self.recv_port}: {error}")
            return None
        with self.lock:
            if self.running:
                self.recv_socket = recv_socket
                self.warned = False
                LOGGER.info("%s receiving", self)
                return recv_socket
        recv_socket.close()  # close() won the race; do not leave the port bound
        return None

    def drop(self, recv_socket, reason):
        """Close the receive socket and forget it, unless it was already replaced; the next read rebinds"""
        with self.lock:
            current = self.recv_socket is recv_socket
            if current:
                self.recv_socket = None
        recv_socket.close()
        if current:
            self.retry_later(reason)

    def warn(self, message, *args):
        """Log a warning once per outage"""
        if not self.warned:
            LOGGER.warning(message, *args)
            self.warned = True

    def waiting_for_retry(self, timeout):
        """True while the next bind attempt is not yet due, sleeping at most `timeout` of the remaining wait"""
        remaining = self.next_attempt - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(timeout, remaining))
        return True

    def retry_later(self, reason):
        """Warn once and schedule the next bind attempt"""
        self.next_attempt = time.monotonic() + self.RECONNECT_INTERVAL
        self.warn("%s %s (retrying every %.1fs)", self, reason, self.RECONNECT_INTERVAL)

    @staticmethod
    def receiving_socket(address, port):
        """Create a bound, non-blocking UDP socket

        SO_REUSEADDR is deliberately not set: UDP has no TIME_WAIT to work around, and with it two adapters could bind
        the same port and silently split the datagrams between them.
        """
        recv_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            recv_socket.bind((address, port))
            recv_socket.setblocking(False)  # recvfrom must not block past the select that reported the datagram
        except OSError:
            recv_socket.close()
            raise
        return recv_socket

    @classmethod
    def get_arguments(cls):
        """Command line arguments for this plugin"""
        return {
            ("--udp-fast-address",): {
                "dest": "udp_fast_address",
                "type": str,
                "default": cls.DEFAULT_ADDRESS,
                "help": "Peer address datagrams are sent to (e.g. the flight software, or the ground system's "
                "telemetry intake). Datagrams from this address and from loopback are accepted.",
            },
            ("--udp-fast-send-port",): {
                "dest": "udp_fast_send_port",
                "type": int,
                "default": cls.DEFAULT_SEND_PORT,
                "help": "Peer port datagrams are sent to.",
            },
            ("--udp-fast-recv-port",): {
                "dest": "udp_fast_recv_port",
                "type": int,
                "default": cls.DEFAULT_RECV_PORT,
                "help": "Local port bound to receive datagrams.",
            },
            ("--udp-fast-bind-address",): {
                "dest": "udp_fast_bind_address",
                "type": str,
                "default": cls.DEFAULT_BIND_ADDRESS,
                "help": "Local address bound to receive datagrams. The default keeps the unauthenticated port off "
                "external interfaces; use 0.0.0.0 to receive on all interfaces.",
            },
            ("--udp-fast-allowed-source",): {
                "dest": "udp_fast_allowed_sources",
                "type": str,
                "nargs": "+",
                "default": None,
                "help": "Additional source addresses accepted on the receive port. The peer address and loopback are "
                "always accepted; datagrams from any other source are dropped.",
            },
        }

    @classmethod
    def check_arguments(
        cls,
        udp_fast_address=DEFAULT_ADDRESS,
        udp_fast_send_port=DEFAULT_SEND_PORT,
        udp_fast_recv_port=DEFAULT_RECV_PORT,
        udp_fast_bind_address=DEFAULT_BIND_ADDRESS,
        udp_fast_allowed_sources=None,
    ):
        """Validate the port ranges and that the receive address:port can be bound, raising ValueError on failure"""
        for port in (udp_fast_send_port, udp_fast_recv_port):
            if not 0 < port < 65536:
                raise ValueError(f"Port {port} is not in the range 1-65535")
        try:
            cls.receiving_socket(udp_fast_bind_address, udp_fast_recv_port).close()
        except OSError as error:
            raise ValueError(f"Cannot bind {udp_fast_bind_address}:{udp_fast_recv_port}: {error}")

    @classmethod
    def get_name(cls):
        """Plugin name"""
        return "udp-fast"

    @classmethod
    @gds_plugin_implementation
    def register_communication_plugin(cls):
        """Register this as a plugin"""
        return cls
