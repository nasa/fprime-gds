"""
udp.py:

Module containing a comm-layer adapter for UDP communication. This provides a pure UDP adapter
supporting both uplink (sending data to FSW) and downlink (receiving data from FSW) over UDP
datagrams. This pairs with the F prime UDP socket components.

@author devin
"""

import logging
import queue
import socket
import threading
import time

import fprime_gds.common.communication.adapters.base

from fprime_gds.plugin.definitions import gds_plugin_implementation

LOGGER = logging.getLogger("udp_adapter")


class UdpAdapter(fprime_gds.common.communication.adapters.base.BaseAdapter):
    """Adapter for pure UDP communication supporting both uplink and downlink.

    This adapter uses UDP datagrams for both directions of communication:
    - Uplink: sends framed data to FSW at the configured send address/port
    - Downlink: binds locally and receives datagrams from FSW on the configured receive port

    Two separate sockets are used to allow independent send and receive port configuration,
    which is typical for F prime deployments using UDP.
    """

    MAXIMUM_DATA_SIZE = 65535
    ERROR_RETRY_INTERVAL = 1

    def __init__(self, udp_address, udp_send_port, udp_recv_port):
        """Initialize the UDP adapter.

        Args:
            udp_address: remote address of FSW for sending uplink data
            udp_send_port: remote port to send uplink data to
            udp_recv_port: local port to bind for receiving downlink data
        """
        self.address = udp_address
        self.send_port = udp_send_port
        self.recv_port = udp_recv_port
        self.send_socket = None
        self.recv_socket = None
        self.running = False
        self.recv_thread = None
        self.data_queue = queue.Queue()

    def __repr__(self):
        """String representation for logging"""
        return f"UDP@{self.address} send:{self.send_port} recv:{self.recv_port}"

    def open(self):
        """Open both send and receive UDP sockets.

        The send socket is an unbound UDP socket used to send datagrams to FSW.
        The receive socket is bound to the configured receive port to accept incoming data.
        """
        self.running = True
        # Send socket: standard UDP socket for transmitting to FSW
        self.send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Receive socket: bound to local port for incoming FSW data
        self.recv_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.recv_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.recv_socket.bind(("0.0.0.0", self.recv_port))
        self.recv_socket.settimeout(0.5)

        # Start background thread to read from receive socket
        self.recv_thread = threading.Thread(
            target=self._recv_loop, name="UdpRecvThread", daemon=True
        )
        self.recv_thread.start()
        LOGGER.info(
            "UDP adapter opened: sending to %s:%d, receiving on port %d",
            self.address,
            self.send_port,
            self.recv_port,
        )

    def close(self):
        """Close both UDP sockets and stop the receive thread."""
        self.running = False
        if self.recv_thread is not None:
            self.recv_thread.join(timeout=2.0)
            self.recv_thread = None
        if self.send_socket is not None:
            self.send_socket.close()
            self.send_socket = None
        if self.recv_socket is not None:
            self.recv_socket.close()
            self.recv_socket = None

    def write(self, frame):
        """Send a framed packet to FSW via UDP.

        Args:
            frame: framed data packet to send

        Returns:
            True on successful send, False on error
        """
        if self.send_socket is None:
            return False
        try:
            self.send_socket.sendto(frame, (self.address, self.send_port))
            return True
        except OSError as exc:
            LOGGER.warning("UDP send failed: %s: %s", type(exc).__name__, str(exc))
            return False

    def read(self, timeout=0.500):
        """Read available data received from FSW via UDP.

        Blocks up to timeout seconds waiting for at least one datagram, then drains
        any additional queued data before returning.

        Args:
            timeout: maximum time to block waiting for data

        Returns:
            bytes of data received, or b"" if nothing available within timeout
        """
        data = b""
        try:
            data += self.data_queue.get(timeout=timeout)
            while not self.data_queue.empty():
                data += self.data_queue.get_nowait()
        except queue.Empty:
            pass
        return data

    def _recv_loop(self):
        """Background thread loop that reads from the receive socket into the queue."""
        while self.running:
            try:
                datagram, _ = self.recv_socket.recvfrom(UdpAdapter.MAXIMUM_DATA_SIZE)
                if datagram:
                    self.data_queue.put(datagram)
            except socket.timeout:
                continue
            except OSError:
                if self.running:
                    LOGGER.warning("UDP receive error, retrying")
                    time.sleep(UdpAdapter.ERROR_RETRY_INTERVAL)

    @classmethod
    def get_name(cls):
        """Get the name of this adapter"""
        return "udp"

    @classmethod
    def get_arguments(cls):
        """Returns a dictionary of flag to argparse-argument dictionaries.

        Returns:
            dictionary of flag to argparse arguments for use with argparse
        """
        return {
            ("--udp-address",): {
                "dest": "udp_address",
                "type": str,
                "default": "127.0.0.1",
                "help": "Address of FSW to send uplink data to.",
            },
            ("--udp-send-port",): {
                "dest": "udp_send_port",
                "type": int,
                "default": 50000,
                "help": "Port on FSW to send uplink data to.",
            },
            ("--udp-recv-port",): {
                "dest": "udp_recv_port",
                "type": int,
                "default": 50001,
                "help": "Local port to bind for receiving downlink data from FSW.",
            },
        }

    @classmethod
    @gds_plugin_implementation
    def register_communication_plugin(cls):
        """Register this as a communication plugin"""
        return cls

    @classmethod
    def check_arguments(cls, udp_address, udp_send_port, udp_recv_port):
        """Validate adapter arguments.

        Args:
            udp_address: remote FSW address
            udp_send_port: port to send to
            udp_recv_port: port to receive on

        Raises:
            ValueError: if any argument is invalid
        """
        if not (0 < udp_send_port <= 65535):
            raise ValueError(
                f"UDP send port '{udp_send_port}' out of range. Must be 1-65535."
            )
        if not (0 < udp_recv_port <= 65535):
            raise ValueError(
                f"UDP receive port '{udp_recv_port}' out of range. Must be 1-65535."
            )
        try:
            socket.getaddrinfo(udp_address, None)
        except socket.gaierror as exc:
            raise ValueError(f"Cannot resolve UDP address '{udp_address}': {exc}")
