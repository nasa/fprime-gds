"""
Handles executing the "send-raw" CLI command for the GDS
"""
import sys
import struct
from typing import Iterable

from fprime_gds.common.gds_cli.base_commands import BaseCommand
from fprime_gds.common.models.dictionaries import Dictionaries
from fprime_gds.common.testing_fw import predicates
from fprime_gds.common.testing_fw.api import IntegrationTestAPI


def frame_ccsds(payload: bytes, apid: int = 0x64) -> bytes:
    """Standard CCSDS Primary Header (6 bytes)."""
    word1 = 0x1000 | (apid & 0x7FF)
    word2 = 0xC000
    length_field = len(payload) - 1
    return struct.pack(">HHH", word1, word2, length_field) + payload


def frame_native(payload: bytes) -> bytes:
    """Standard Native F Prime framing (8 bytes: Sync + Length)."""
    sync = 0x55555555
    length = len(payload)
    return struct.pack(">II", sync, length) + payload


def _get_fsw_routing_dest():
    try:
        from fprime_gds.common.transport import RoutingTag
        return RoutingTag.FSW
    except (ImportError, AttributeError):
        return "FSW"


def _send_to_fsw(client_socket, payload: bytes) -> None:
    import inspect
    sig = inspect.signature(client_socket.send)
    if len(sig.parameters) >= 2:
        dest = _get_fsw_routing_dest()
        client_socket.send(payload, dest)
    else:
        client_socket.send(payload)


class SendRawCommand(BaseCommand):
    @classmethod
    def _get_item_list(cls, project_dictionary, filter_predicate) -> Iterable:
        return []

    @classmethod
    def _get_item_string(cls, item, json: bool = False) -> str:
        return ""

    @classmethod
    def _execute_command(cls, args, api: IntegrationTestAPI):
        # 1. Parse hex input
        try:
            hex_data = "".join(args.hex_strings).replace(" ", "")
            raw_input = bytes.fromhex(hex_data)
        except ValueError as e:
            cls._log(f"ERROR: Invalid hex: {e}")
            sys.exit(1)

        # 2. Apply chosen framing
        if args.format == "none":
            payload = raw_input
            mode_str = "BYPASS (Verbatim)"
        elif args.format == "native":
            payload = frame_native(raw_input)
            mode_str = "NATIVE (0x55555555)"
        else:
            payload = frame_ccsds(raw_input)
            mode_str = "CCSDS (APID 0x64)"

        cls._log(f"[send-raw] Mode    : {mode_str}")
        cls._log(f"[send-raw] Sending : {payload.hex().upper()}")

        # 3. Transmit
        try:
            _send_to_fsw(api.pipeline.client_socket, payload)
            cls._log("[send-raw] Status  : SUCCESS")
        except Exception as exc:
            cls._log(f"[send-raw] ERROR   : {exc}")
            sys.exit(1)