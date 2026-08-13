"""
Handles executing the "file-uplink" CLI command for the GDS
"""

import sys
import time
from pathlib import Path

from fprime_gds.common.gds_cli.base_commands import BaseCommand
from fprime_gds.common.models.dictionaries import Dictionaries
from fprime_gds.common.testing_fw import predicates
from fprime_gds.common.testing_fw.api import IntegrationTestAPI

# Terminal states reported by the uplinker for a queued file
SUCCESS_STATE = "FINISHED"
FAILURE_STATES = ["CANCELED", "TIMEOUT"]
POLL_PERIOD_SECONDS = 0.25


class FileUplinkCommand(BaseCommand):
    """
    The implementation for uplinking a local file to the spacecraft via the GDS
    file uplink system
    """

    @classmethod
    def _get_item_list(
        cls,
        project_dictionary: Dictionaries,
        filter_predicate: predicates.predicate,
    ):
        """
        Not applicable for file-uplink command as it doesn't use dictionary items
        """
        return []

    @classmethod
    def _get_item_string(
        cls,
        item,
        json: bool = False,
    ) -> str:
        """
        Not applicable for file-uplink command
        """
        return ""

    @classmethod
    def _get_file_entry(cls, api: IntegrationTestAPI, source_name: str):
        """
        Finds the uplink queue entry whose source basename matches the given file
        """
        uplinker = api.pipeline.files.uplinker
        for entry in uplinker.current_files():
            if Path(entry.get("source", "")).name == source_name:
                return entry
        return None

    @classmethod
    def _await_completion(cls, args, api: IntegrationTestAPI, source_name: str) -> bool:
        """
        Polls the uplinker until the file reaches a terminal state or the timeout
        expires. Returns True on successful uplink, False otherwise.
        """
        last_percent = -1
        end_time = time.time() + args.timeout
        while time.time() < end_time:
            entry = cls._get_file_entry(api, source_name)
            if entry is None:
                cls._log(f"Error: '{source_name}' is no longer tracked by the uplinker")
                return False
            percent = entry.get("percent", 0)
            if entry.get("state") == "TRANSMITTING" and percent != last_percent:
                cls._log(f"Uplinking '{source_name}': {percent}%")
                last_percent = percent
            if entry.get("state") == SUCCESS_STATE:
                cls._log(f"Uplink of '{source_name}' to '{entry.get('destination')}' complete")
                return True
            if entry.get("state") in FAILURE_STATES:
                cls._log(f"Uplink of '{source_name}' failed with state {entry.get('state')}")
                return False
            time.sleep(POLL_PERIOD_SECONDS)
        cls._log(f"Error: uplink of '{source_name}' did not complete within {args.timeout} seconds")
        return False

    @classmethod
    def _execute_command(cls, args, api: IntegrationTestAPI):
        """
        Logic for uplinking a file through the GDS file uplink system
        """
        file_path = Path(args.file_path)
        if not file_path.is_file():
            cls._log(f"Error: File not found at {args.file_path}")
            sys.exit(1)

        try:
            api.uplink_file(str(file_path), args.destination)
        except Exception as exc:
            cls._log(f"Error starting file uplink: {exc}")
            sys.exit(1)

        destination = args.destination if args.destination else f"/{file_path.name}"

        # Transports with a blocking upload_file (e.g. YAMCS) complete synchronously
        if hasattr(api.pipeline.client_socket, "upload_file"):
            cls._log(f"Uplink of '{file_path.name}' to '{destination}' complete")
            return

        cls._log(f"Queued '{file_path}' for uplink to '{destination}'")
        if args.no_wait:
            return

        if not cls._await_completion(args, api, file_path.name):
            sys.exit(1)
