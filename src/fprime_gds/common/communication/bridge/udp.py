"""fprime_gds.common.communication.bridge.udp: UDP links for exchanging packets with a ground system

Implements the ground-system side of the fprime-comm-bridge. Telemetry (downlink) packets are
pushed as UDP datagrams to the ground system's telemetry intake (e.g. a YAMCS UdpTmFrameLink or
an OpenC3 UDP interface), and command (uplink) packets are received as UDP datagrams from the
ground system's command outlet.
"""

import logging
import socket

LOGGER = logging.getLogger(__name__)

# Maximum size of a received UDP datagram
MAXIMUM_DATAGRAM_SIZE = 65507


class UdpLinks:
    """UDP links used to exchange packets with a ground system

    Maintains two UDP sockets: a send socket used to push telemetry datagrams to the ground
    system's intake, and a receive socket bound locally to accept command datagrams from the
    ground system's outlet.
    """

    def __init__(self, tm_host, tm_port, tc_host, tc_port, tc_sources=None, timeout=0.500):
        """Initialize with the TM destination and local TC bind address

        Args:
            tm_host: hostname/address of the ground system's UDP telemetry intake
            tm_port: port of the ground system's UDP telemetry intake
            tc_host: local address to bind for receiving command datagrams
            tc_port: local port to bind for receiving command datagrams
            tc_sources: iterable of additional source hosts allowed to send
                command datagrams; the TM host and loopback are always allowed.
                Hostnames are resolved to IPv4 addresses at construction time.
            timeout: receive timeout in seconds allowing periodic shutdown checks
        """
        self.tm_destination = (tm_host, tm_port)
        self.tc_bind = (tc_host, tc_port)
        self.allowed_sources = {
            socket.gethostbyname(source)
            for source in {tm_host, "127.0.0.1"} | set(tc_sources or [])
        }
        self.timeout = timeout
        self.tm_socket = None
        self.tc_socket = None

    def open(self):
        """Open the send and receive sockets"""
        self.tm_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.tc_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.tc_socket.bind(self.tc_bind)
        self.tc_socket.settimeout(self.timeout)
        LOGGER.info(
            "Sending TM to udp://%s:%d, receiving TC on udp://%s:%d",
            self.tm_destination[0],
            self.tm_destination[1],
            self.tc_bind[0],
            self.tc_bind[1],
        )

    def close(self):
        """Close both sockets"""
        for closing_socket in (self.tm_socket, self.tc_socket):
            if closing_socket is not None:
                try:
                    closing_socket.close()
                except OSError as error:
                    LOGGER.warning("Failed to close socket: %s", error)
        self.tm_socket = None
        self.tc_socket = None

    def send(self, packet):
        """Send one packet as a single datagram to the telemetry intake

        Args:
            packet: bytes of the packet to send
        Returns:
            True when the datagram was sent, False otherwise
        """
        try:
            self.tm_socket.sendto(packet, self.tm_destination)
            return True
        except OSError as error:
            LOGGER.warning("Failed to send TM datagram: %s", error)
            return False

    def receive(self):
        """Receive one command datagram from the command outlet

        Blocks up to the configured timeout waiting for a datagram. Datagrams from
        sources other than the allowed set are dropped.

        Returns:
            datagram bytes, or None when no datagram arrived within the timeout
        """
        try:
            datagram, source = self.tc_socket.recvfrom(MAXIMUM_DATAGRAM_SIZE)
            if source[0] not in self.allowed_sources:
                LOGGER.warning(
                    "Dropping TC datagram from unexpected source %s", source[0]
                )
                return None
            return datagram
        except socket.timeout:
            return None
        except OSError as error:
            LOGGER.warning("Failed to receive TC datagram: %s", error)
            return None
