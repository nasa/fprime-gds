"""fprime_gds.common.communication.bridge.bridge: bidirectional data pump between two communication adapters

Runs two threads:

1. Downlink: reads bytes from the flight-side communication adapter (UART, TCP, etc.), deframes
   them with the configured framer/deframer plugin, optionally splits each result into individual
   packets (e.g. the Space Packets a TM frame deframer yields concatenated), and writes each packet
   to the ground-side adapter (one datagram per packet over `udp-fast`).
2. Uplink: reads packets from the ground-side adapter, frames each one with the configured
   framer/deframer plugin, and writes the result to the flight-side adapter.

With the no-op framer/deframer, data passes through unmodified in both directions.
"""

import logging
import struct
import threading
from typing import List, Tuple

from fprime_gds.common.communication.ccsds.space_data_link import (
    SpaceDataLinkFramerDeframer,
)
from fprime_gds.common.communication.ccsds.space_packet import (
    SpacePacketFramerDeframer,
)

LOGGER = logging.getLogger(__name__)

# CCSDS Space Packet primary header size and the idle packet APID (CCSDS 133.0-B-2)
SPACE_PACKET_HEADER_SIZE = SpaceDataLinkFramerDeframer.SPACE_PACKET_HEADER_SIZE
SPACE_PACKET_IDLE_APID = SpacePacketFramerDeframer.IDLE_APID

# Maximum size of a UDP payload; the ground side emits one packet per datagram
MAXIMUM_DATAGRAM_SIZE = 65507

# Cap on buffered unframed downlink data before it is discarded
MAXIMUM_PENDING_SIZE = 10 * MAXIMUM_DATAGRAM_SIZE

# Join timeout used when stopping the pump threads
STOP_JOIN_TIMEOUT = 5.0


def split_space_packets(data: bytes) -> Tuple[List[bytes], bytes]:
    """Split concatenated CCSDS Space Packets into individual packets, discarding idle packets

    Args:
        data: header-aligned concatenation of complete Space Packets
    Return:
        (packets, remainder) where remainder holds trailing bytes not forming a complete packet
    """
    packets = []
    offset = 0
    while len(data) - offset >= SPACE_PACKET_HEADER_SIZE:
        identification, _, length = struct.unpack_from(">HHH", data, offset)
        end = offset + SPACE_PACKET_HEADER_SIZE + length + 1
        if end > len(data):
            break
        if (identification & SPACE_PACKET_IDLE_APID) != SPACE_PACKET_IDLE_APID:
            packets.append(data[offset:end])
        offset = end
    return packets, data[offset:]


class PacketBridge:
    """Bidirectional bridge between a flight-side and a ground-side communication adapter"""

    def __init__(self, flight, framer, ground, splitter=None, failure_handler=None):
        """Initialize the bridge

        Args:
            flight: BaseAdapter instance for the F Prime endpoint side
            framer: FramerDeframer instance used for one stage of framing/deframing
            ground: BaseAdapter instance for the ground system side; each read returns one packet
            splitter: optional callable splitting a deframed unit into the packets to emit, returning
                (packets, remainder) with remainder being unsplittable trailing bytes that are discarded
            failure_handler: callable invoked when a pump thread exits abnormally
        """
        self.flight = flight
        self.framer = framer
        self.ground = ground
        self.splitter = splitter
        self.failure_handler = failure_handler
        self.running = True
        self.downlink_thread = threading.Thread(
            target=self.downlink_loop, name="DownlinkThread", daemon=True
        )
        self.uplink_thread = threading.Thread(
            target=self.uplink_loop, name="UplinkThread", daemon=True
        )

    def start(self):
        """Open both adapters and start the data pump threads"""
        self.ground.open()
        try:
            self.flight.open()
        except Exception:
            self.ground.close()
            raise
        self.downlink_thread.start()
        self.uplink_thread.start()
        LOGGER.info("Bridge up: downlink and uplink pumps running")

    def stop(self):
        """Stop the data pump threads and release both adapters"""
        self.running = False
        self.downlink_thread.join(timeout=STOP_JOIN_TIMEOUT)
        self.uplink_thread.join(timeout=STOP_JOIN_TIMEOUT)
        self.flight.close()
        self.ground.close()

    def report_failure(self, direction, error):
        """Report the abnormal exit of a pump thread"""
        LOGGER.error("%s loop failed: %s", direction, error)
        if self.failure_handler is not None:
            self.failure_handler()

    def downlink_loop(self):
        """Read from the flight adapter, deframe, and write packets to the ground adapter"""
        try:
            pending = b""
            discarded_total = 0
            while self.running:
                data = self.flight.read()
                if not data:
                    continue
                pending += data
                if len(pending) > MAXIMUM_PENDING_SIZE:
                    LOGGER.warning(
                        "Dropping %d bytes of stalled unframed data", len(pending)
                    )
                    pending = b""
                    continue
                packets, pending, discarded = self.framer.deframe_all(
                    pending, no_copy=True
                )
                if discarded:
                    if not discarded_total:
                        LOGGER.warning(
                            "Discarded %d bytes of unframed data", len(discarded)
                        )
                    discarded_total += len(discarded)
                if packets and discarded_total:
                    LOGGER.info(
                        "Resynchronised after discarding %d bytes of unframed data",
                        discarded_total,
                    )
                    discarded_total = 0
                for packet in packets:
                    for unit in self.split(packet):
                        self.ground.write(unit)
        except Exception as error:
            self.report_failure("Downlink", error)
        LOGGER.debug("Downlink loop exited")

    def split(self, packet) -> List[bytes]:
        """Split a deframed unit into the packets emitted to the ground side"""
        if self.splitter is None:
            return [packet]
        units, remainder = self.splitter(packet)
        if remainder:
            LOGGER.warning("Discarded %d trailing bytes not forming a whole packet", len(remainder))
        return units

    def uplink_loop(self):
        """Read packets from the ground adapter, frame, and write to the flight adapter"""
        try:
            while self.running:
                packet = self.ground.read()
                if not packet:
                    continue
                try:
                    framed = self.framer.frame(packet)
                except Exception as error:
                    LOGGER.warning(
                        "Dropping %d byte ground packet that cannot be framed: %s",
                        len(packet),
                        error,
                    )
                    continue
                if not self.flight.write(framed):
                    LOGGER.warning(
                        "Failed to write %d bytes to flight adapter", len(framed)
                    )
        except Exception as error:
            self.report_failure("Uplink", error)
        LOGGER.debug("Uplink loop exited")
