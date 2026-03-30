"""
Handles executing the "send-raw" CLI command for the GDS
"""

import struct
import sys
from pathlib import Path

from fprime_gds.common.gds_cli.base_commands import BaseCommand
from fprime_gds.common.models.dictionaries import Dictionaries
from fprime_gds.common.testing_fw import predicates
from fprime_gds.common.testing_fw.api import IntegrationTestAPI


class SendRawCommand(BaseCommand):
    """
    The implementation for sending raw data via the GDS to the spacecraft
    without further serialization (data is sent through framing only)
    """

    @classmethod
    def _get_item_list(
        cls,
        project_dictionary: Dictionaries,
        filter_predicate: predicates.predicate,
    ):
        """
        Not applicable for send-raw command as it doesn't use dictionary items
        """
        return []

    @classmethod
    def _get_item_string(
        cls,
        item,
        json: bool = False,
    ) -> str:
        """
        Not applicable for send-raw command
        """
        return ""

    @classmethod
    def _execute_command(cls, args, api: IntegrationTestAPI):
        """
        Logic for sending raw data through the framing layer
        """
        raw_data = None

        # Get raw data from either bin file or hex string
        if args.bin_path:
            try:
                bin_path = Path(args.bin_path)
                if not bin_path.exists():
                    cls._log(f"Error: Binary file not found at {args.bin_path}")
                    sys.exit(1)
                with open(bin_path, 'rb') as f:
                    raw_data = f.read()
                cls._log(f"Read {len(raw_data)} bytes from {args.bin_path}")
            except Exception as e:
                cls._log(f"Error reading binary file: {e}")
                sys.exit(1)
        elif args.hex_string:
            try:
                # Remove '0x' prefix if present and any whitespace
                hex_str = args.hex_string.replace('0x', '').replace('0X', '').replace(' ', '')
                raw_data = bytes.fromhex(hex_str)
            except ValueError as e:
                cls._log(f"Error parsing hex string: {e}")
                sys.exit(1)
        else:
            cls._log("Error: Either --bin-path or --hex-string must be provided")
            sys.exit(1)

        # Send raw data through the client socket (to comm.py)
        # The ZMQ transport strips the
        # first 4 bytes on the receiving end (ZmqGround.receive_all) because the
        # normal encoder path (via CmdEncoder) includes them after the ZZZZ marker.
        try:
            data_to_send = raw_data
            if args.zmq:
                # If using ZMQ, prepend the length of the data as a 4-byte big-endian integer
                data_to_send = struct.pack(">I", len(raw_data)) + raw_data
            if args.verbose:
                cls._log(f"Sending {len(raw_data)} bytes of raw data: {raw_data.hex()}")
            api.pipeline.client_socket.send(data_to_send)
        except Exception as e:
            cls._log(f"Error sending raw data: {e}")
            sys.exit(1)
