"""fprime_gds.common.communication.bridge.bridge: bidirectional data pump between an endpoint and UDP links

Runs two threads:

1. Downlink: reads bytes from the F Prime communication adapter (UART, IP, etc.), deframes
   them with the configured framer/deframer plugin, and pushes each resulting packet as a
   UDP datagram to the ground system's telemetry intake.
2. Uplink: receives UDP datagrams from the ground system's command outlet, frames each
   datagram with the configured framer/deframer plugin, and writes the result to the
   communication adapter.

With the no-op framer/deframer, data passes through unmodified in both directions.
"""

import logging
import threading

from fprime_gds.common.communication.bridge.udp import MAXIMUM_DATAGRAM_SIZE

LOGGER = logging.getLogger(__name__)

# Cap on buffered unframed downlink data before it is discarded
MAXIMUM_PENDING_SIZE = 10 * MAXIMUM_DATAGRAM_SIZE

# Join timeout used when stopping the pump threads
STOP_JOIN_TIMEOUT = 5.0


class UdpBridge:
    """Bidirectional bridge between a communication adapter and ground system UDP links"""

    def __init__(self, adapter, framer, udp, failure_handler=None):
        """Initialize the bridge

        Args:
            adapter: BaseAdapter instance for the F Prime endpoint side
            framer: FramerDeframer instance used for one stage of framing/deframing
            udp: UdpLinks instance for the ground system side
            failure_handler: callable invoked when a pump thread exits abnormally
        """
        self.adapter = adapter
        self.framer = framer
        self.udp = udp
        self.failure_handler = failure_handler
        self.running = True
        self.downlink_thread = threading.Thread(
            target=self.downlink_loop, name="DownlinkThread", daemon=True
        )
        self.uplink_thread = threading.Thread(
            target=self.uplink_loop, name="UplinkThread", daemon=True
        )

    def start(self):
        """Open resources and start both data pump threads"""
        self.udp.open()
        self.adapter.open()
        self.downlink_thread.start()
        self.uplink_thread.start()
        LOGGER.info("Bridge up: downlink and uplink pumps running")

    def stop(self):
        """Stop the data pump threads and release resources"""
        self.running = False
        self.downlink_thread.join(timeout=STOP_JOIN_TIMEOUT)
        self.uplink_thread.join(timeout=STOP_JOIN_TIMEOUT)
        self.adapter.close()
        self.udp.close()

    def report_failure(self, direction, error):
        """Report the abnormal exit of a pump thread"""
        LOGGER.error("%s loop failed: %s", direction, error)
        if self.failure_handler is not None:
            self.failure_handler()

    def downlink_loop(self):
        """Read from the adapter, deframe, and push packets to the UDP telemetry intake"""
        try:
            pending = b""
            while self.running:
                data = self.adapter.read()
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
                    self.udp.send(packet)
        except Exception as error:
            self.report_failure("Downlink", error)
        LOGGER.debug("Downlink loop exited")

    def uplink_loop(self):
        """Receive datagrams from the UDP command outlet, frame, and write to the adapter"""
        try:
            while self.running:
                datagram = self.udp.receive()
                if datagram is None:
                    continue
                framed = self.framer.frame(datagram)
                if not self.adapter.write(framed):
                    LOGGER.warning(
                        "Failed to write %d bytes to adapter", len(framed)
                    )
        except Exception as error:
            self.report_failure("Uplink", error)
        LOGGER.debug("Uplink loop exited")
