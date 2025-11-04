"""
comm.py:

This is the F prime communications adapter. This allows the F prime ground tool suite to interact with running F prime
deployments that exist on the other end of a "wire" (some communication bus). This is done with the following mechanics:

1. An adapter is instantiated to handle "read" and "write" functions against the wire
2. A framer/deframer is instantiated in order to frame/deframe those packets as transported across the wire.
3. "Uplink" and "Downlink" threads are created to loop on data from flight (F prime) and ground (F prime ground)
   interfaces ensuring that ground data is framed and written to the wire, and flight data is deframed and sent to the
   ground side.

Note: assuming the module containing the ground adapter has been imported, then this code should provide it as a CLI
      argument, removing the need to rewrite most of this class to use something different.

@author lestarch
"""

import logging
import signal
import sys
from pathlib import Path

# Required adapters built on standard tools
import fprime_gds.common.communication.adapters.base
import fprime_gds.common.communication.adapters.ip
import fprime_gds.common.communication.ground
import fprime_gds.common.logger
import fprime_gds.executables.cli
from fprime_gds.common.communication.updown import Downlinker, Uplinker
from fprime_gds.common.zmq_transport import ZmqGround
from fprime_gds.plugin.system import Plugins

# Uses non-standard PIP package pyserial, so test the waters before getting a hard-import crash
try:
    import fprime_gds.common.communication.adapters.uart
except ImportError:
    pass


LOGGER = logging.getLogger("comm")


def main():
    """
    Main program, degenerates into the run loop.

    :return: return code
    """
    # comm.py supports 2 and only 2 plugin categories
    Plugins.system(["communication", "framing"])
    args, _ = fprime_gds.executables.cli.ParserBase.parse_args(
        [
            # CommParser must be first as it includes dictionary/config
            # loading which feeds into instantiation of the Framers
            fprime_gds.executables.cli.CommParser,
            fprime_gds.executables.cli.PluginArgumentParser,
        ],
        description="F prime communications layer.",
        client=True,
    )
    if args.communication_selection == "none":
        print(
            "[ERROR] Comm adapter set to 'none'. Nothing to do but exit.",
            file=sys.stderr,
        )
        sys.exit(-1)

    # Create the handling components for either side of this script, adapter for hardware, and ground for the GDS side
    if args.zmq:
        ground = ZmqGround(args.zmq_transport)
    else:
        ground = fprime_gds.common.communication.ground.TCPGround(
            args.tts_addr, args.tts_port
        )

    adapter = Plugins.system().get_selected_class("communication")()

    # Set the framing class used and pass it to the uplink and downlink component constructions giving each a separate
    # instantiation
    framer_instance = Plugins.system().get_selected_class("framing")()
    LOGGER.info(
        "Starting uplinker/downlinker connecting to FSW using %s with %s",
        args.communication_selection,
        args.framing_selection,
    )
    discarded_file_handle = None
    try:
        if args.output_unframed_data == "-":
            discarded_file_handle = sys.stdout.buffer
        elif args.output_unframed_data is not None:
            discarded_file_handle_path = (
                Path(args.logs) / Path(args.output_unframed_data)
            ).resolve()
            try:
                discarded_file_handle = open(discarded_file_handle_path, "wb")
                LOGGER.info("Logging unframed data to %s", discarded_file_handle_path)
            except OSError:
                LOGGER.warning(
                    "Failed to open %s. Unframed data will be discarded.",
                    discarded_file_handle_path,
                )
        downlinker = Downlinker(
            adapter, ground, framer_instance, discarded=discarded_file_handle
        )
        uplinker = Uplinker(adapter, ground, framer_instance, downlinker)

        # Open resources for the handlers on either side, this prepares the resources needed for reading/writing data
        ground.open()
        adapter.open()

        # Finally start the processing of uplink and downlink
        downlinker.start()
        uplinker.start()
        LOGGER.debug("Uplinker and downlinker running")

        # Wait for shutdown event in the form of a KeyboardInterrupt then stop the processing, close resources,
        # and wait for everything to terminate as expected.
        def shutdown(*_):
            """Shutdown function for signals"""
            uplinker.stop()
            downlinker.stop()
            uplinker.join()
            downlinker.join()
            ground.close()
            adapter.close()

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        uplinker.join()
        downlinker.join()
    finally:
        if discarded_file_handle is not None and args.output_unframed_data != "-":
            discarded_file_handle.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
