"""fprime_gds.common.communication.bridge.bridge: bidirectional data pump between two communication adapters

Runs two threads:

1. Downlink: reads bytes from the flight-side communication adapter (UART, TCP, etc.), deframes
   them with the configured framer/deframer plugin, and writes each resulting packet to the
   ground-side adapter (one datagram per packet over `udp-fast`).
2. Uplink: reads packets from the ground-side adapter, frames each one with the configured
   framer/deframer plugin, and writes the result to the flight-side adapter.

With the no-op framer/deframer, data passes through unmodified in both directions.
"""

import logging
import threading

LOGGER = logging.getLogger(__name__)

# Maximum size of a UDP payload; the ground side emits one packet per datagram
MAXIMUM_DATAGRAM_SIZE = 65507

# Cap on buffered unframed downlink data before it is discarded
MAXIMUM_PENDING_SIZE = 10 * MAXIMUM_DATAGRAM_SIZE

# Join timeout used when stopping the pump threads
STOP_JOIN_TIMEOUT = 5.0


class PacketBridge:
    """Bidirectional bridge between a flight-side and a ground-side communication adapter"""

    def __init__(self, flight, framer, ground, failure_handler=None):
        """Initialize the bridge

        Args:
            flight: BaseAdapter instance for the F Prime endpoint side
            framer: FramerDeframer instance used for one stage of framing/deframing
            ground: BaseAdapter instance for the ground system side; each read returns one packet
            failure_handler: callable invoked when a pump thread exits abnormally
        """
        self.flight = flight
        self.framer = framer
        self.ground = ground
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
        self.flight.open()
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
                    LOGGER.warning(
                        "Discarded %d bytes of unframed data", len(discarded)
                    )
                for packet in packets:
                    self.ground.write(packet)
        except Exception as error:
            self.report_failure("Downlink", error)
        LOGGER.debug("Downlink loop exited")

    def uplink_loop(self):
        """Read packets from the ground adapter, frame, and write to the flight adapter"""
        try:
            while self.running:
                packet = self.ground.read()
                if not packet:
                    continue
                framed = self.framer.frame(packet)
                if not self.flight.write(framed):
                    LOGGER.warning(
                        "Failed to write %d bytes to flight adapter", len(framed)
                    )
        except Exception as error:
            self.report_failure("Uplink", error)
        LOGGER.debug("Uplink loop exited")
