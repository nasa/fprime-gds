"""fprime_gds.executables.comm_bridge: entry point for the fprime-comm-bridge

fprime-comm-bridge bridges an F Prime endpoint (reached through an F Prime GDS
communication adapter plugin: TCP, UART, etc.) and a ground system exchanging packets as UDP
datagrams (YAMCS, OpenC3 COSMOS, ...). A single stage of framing/deframing (an F Prime GDS
framing plugin) sits between the two sides.

By default the endpoint side is a `tcp-fast-server` on port 50000 (the F Prime GDS default
the `Ref` deployment's Drv.TcpClient connects to) and the framing stage is the
`tm-frame-aggregator`, which re-establishes CCSDS TM transfer frame boundaries in the byte
stream so each frame reaches the ground system as one UDP datagram; uplink passes through
unchanged. The aggregator reads the frame size and spacecraft ID from the dictionary
(`--dictionary`) or from `--frame-size`/`--scid`. Other framing plugins (`no-op`, `fprime`,
`raw-space-data-link` to expose Space Packets, ...) may be selected with `--framing-selection`.
"""

import logging
import signal
import sys
import threading
from typing import Any, Dict, Tuple

# Required adapters built on standard tools
import fprime_gds.common.communication.adapters.base
import fprime_gds.common.communication.adapters.ip
import fprime_gds.common.communication.adapters.tcp_fast
import fprime_gds.executables.cli
from fprime_gds.common.communication.bridge import DEFAULT_COMMUNICATION, DEFAULT_FRAMING
from fprime_gds.common.communication.bridge.bridge import UdpBridge
from fprime_gds.common.communication.bridge.udp import UdpLinks
from fprime_gds.plugin.system import Plugins

# Uses non-standard PIP package pyserial, so test the waters before getting a hard-import crash
try:
    import fprime_gds.common.communication.adapters.uart
except ImportError:
    pass

LOGGER = logging.getLogger(__name__)

# Adapters known to expose a byte stream, where read-chunk boundaries are arbitrary and
# no-op framing cannot reliably preserve packet boundaries
STREAM_ADAPTERS = {"uart", "ip", "tcp-fast-server", "tcp-fast-client"}


class UdpLinksParser(fprime_gds.executables.cli.ParserBase):
    """Parser for the ground system UDP intake/outlet options"""

    DESCRIPTION = "UDP Link Options"

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Arguments for the UDP side of the bridge"""
        return {
            ("--tm-host",): {
                "dest": "tm_host",
                "type": str,
                "default": "127.0.0.1",
                "help": "Host of the ground system UDP telemetry intake to send packets to.",
            },
            ("--tm-port",): {
                "dest": "tm_port",
                "type": int,
                "default": 50000,
                "help": "Port of the ground system UDP telemetry intake to send packets to.",
            },
            ("--tc-host",): {
                "dest": "tc_host",
                "type": str,
                "default": "127.0.0.1",
                "help": "Local address to bind for receiving ground system UDP command packets.",
            },
            ("--tc-port",): {
                "dest": "tc_port",
                "type": int,
                "default": 50001,
                "help": "Local port to bind for receiving ground system UDP command packets.",
            },
            ("--tc-allowed-source",): {
                "dest": "tc_sources",
                "type": str,
                "action": "append",
                "default": None,
                "help": "Additional source address allowed to send command packets "
                "(repeatable). The TM host and loopback are always allowed.",
            },
        }

    def handle_arguments(self, args, **kwargs):
        """Validate the UDP link arguments"""
        for port in (args.tm_port, args.tc_port):
            if not 0 < port <= 65535:
                raise ValueError(f"Invalid UDP port: {port}")
        return args


class OptionalDictionaryParser(fprime_gds.executables.cli.DictionaryParser):
    """GDS dictionary parser made optional: loads only when --dictionary or --deployment is given"""

    def handle_arguments(self, args, **kwargs):
        """Skip dictionary detection when no dictionary source was supplied (e.g. no-op framing)"""
        if args.dictionary is None and args.deployment is None:
            return args
        return super().handle_arguments(args, **kwargs)


class BridgePluginArgumentParser(fprime_gds.executables.cli.PluginArgumentParser):
    """Plugin parser defaulting to a TCP server aggregating TM frames"""

    FPRIME_CHOICES = {
        **fprime_gds.executables.cli.PluginArgumentParser.FPRIME_CHOICES,
        "communication": DEFAULT_COMMUNICATION,
        "framing": DEFAULT_FRAMING,
    }


def main():
    """Run the fprime-comm-bridge"""
    logging.basicConfig(level=logging.INFO)
    # fprime-comm-bridge supports 2 and only 2 plugin categories
    Plugins.system(["communication", "framing"])
    args, _ = fprime_gds.executables.cli.ParserBase.parse_args(
        [OptionalDictionaryParser, UdpLinksParser, BridgePluginArgumentParser],
        description="F Prime communication adapter to UDP packet bridge.",
    )
    if args.communication_selection == "none":
        LOGGER.error("Comm adapter set to 'none'. Nothing to do but exit.")
        return 1
    if (
        args.framing_selection == "no-op"
        and args.communication_selection in STREAM_ADAPTERS
    ):
        LOGGER.warning(
            "'no-op' framing over the stream-oriented '%s' adapter cannot preserve "
            "packet boundaries: packets may be split or merged across UDP datagrams "
            "depending on read timing. Use a boundary-recovering framing plugin "
            "(e.g. --framing-selection tm-frame-aggregator) unless the endpoint stream carries "
            "self-delimiting data that the ground system deframes. Note: this detection covers "
            "only the built-in stream adapters; third-party stream adapters are not "
            "detected.",
            args.communication_selection,
        )

    adapter = Plugins.system().get_selected_class("communication")()
    try:
        framer = Plugins.system().get_selected_class("framing")()
    except (TypeError, ValueError) as error:
        LOGGER.error("Failed to configure '%s' framing: %s", args.framing_selection, error)
        return 1
    try:
        udp = UdpLinks(
            args.tm_host, args.tm_port, args.tc_host, args.tc_port, args.tc_sources
        )
    except OSError as error:
        LOGGER.error("Failed to resolve UDP hosts: %s", error)
        return 1
    LOGGER.info(
        "Bridging '%s' adapter and UDP links using '%s' framing",
        args.communication_selection,
        args.framing_selection,
    )

    shutdown_event = threading.Event()
    failure_event = threading.Event()

    def fail(*_):
        """Failure handler for abnormal pump-thread exits"""
        failure_event.set()
        shutdown_event.set()

    bridge = UdpBridge(adapter, framer, udp, failure_handler=fail)

    def shutdown(*_):
        """Shutdown handler for signals"""
        shutdown_event.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        bridge.start()
    except OSError as error:
        LOGGER.error("Failed to open bridge resources: %s", error)
        return 1
    try:
        shutdown_event.wait()
    finally:
        bridge.stop()
    return 1 if failure_event.is_set() else 0


if __name__ == "__main__":
    sys.exit(main())
