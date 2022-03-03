import argparse
import time
import sys
from pathlib import Path

from fprime_gds.common.pipeline.standard import StandardPipeline
from fprime_gds.common.handlers import DataHandler
from fprime_gds.common.client_socket.client_socket import ThreadedTCPSocketClient, GUI_TAG, FSW_TAG

from fprime_gds.common.encoders.event_encoder import EventEncoder
from fprime_gds.common.encoders.ch_encoder import ChEncoder
from fprime_gds.common.utils.config_manager import ConfigManager


class ReplayForwarder(DataHandler):
    """ Class used to replay data by forwarding packets to GDS """

    def __init__(self, encoder, sender, realtime=False):
        """ Setup the forwarder """
        self.last_time = None
        self.encoder = encoder
        self.encoder.register(sender)
        self.realtime = realtime

    @staticmethod
    def as_fraction(time_val):
        """ Convert timeval to fractional time """
        return time_val.seconds + time_val.useconds / 100000

    def get_sleep_time(self, new_time):
        """ Get the necessary sleep time """


        last_as_fraction = self.last_time.seconds + (self.last_time.useconds / 1000000)
        new_as_fraction = new_time.seconds + (new_time)


    def data_callback(self, data, sender=None):
        """ Encode and send the data packet """
        sleep_time = self.as_fraction(data.time) - self.as_fraction(data.time if self.last_time is None else self.last_time)
        self.last_time = data.time
        # Handle time
        if self.realtime and sleep_time > 0:
            time.sleep(sleep_time)
        elif self.realtime and sleep_time < 0:
            print("[WARNING] Unable to keep up with realtime flow")
        self.encoder.data_callback(data)


def parse_args():
    """ Setup argument parser """
    parser = argparse.ArgumentParser(description="A replayer for RAW GUI logged data")
    parser.add_argument(
        "-d",
        "--dictionary",
        type=str,
        default=None,
        help='path from the current working directory to the "<project name>Dictionary.xml" file for the project you\'re using the API with; if unused, tries to search the current working directory for such a file',
    )
    parser.add_argument(
        "-ip",
        "--ip-address",
        type=str,
        default="127.0.0.1",
        help="connect to the GDS server using the given IP or hostname (default=127.0.0.1 (i.e. localhost))",
        metavar="IP",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=50050,
        help="connect to the GDS server using the given port number (default=50050)",
        metavar="PORT",
    )
    parser.add_argument("--realtime", default=False, action="store_true", help="Delay replay to be pseudo-realtime")
    parser.add_argument("raw", help="Raw logfile to replay")
    return parser.parse_args()


def main():
    """ """
    args = parse_args()
    config = ConfigManager()

    if not Path(args.raw).exists():
        print(f"[ERROR] {args.raw} does not exist", file=sys.stderr)

    # Setup standard pipeline
    pipeline = StandardPipeline()
    pipeline.setup(config, args.dictionary, "/tmp/replay-store", None, None)


    # Setup custom connection
    client_socket = ThreadedTCPSocketClient(dest=GUI_TAG)
    client_socket.stop_event.set() # Kill the receive thread before it gets going
    client_socket.connect(args.ip_address, args.port)
    client_socket.register_to_server(FSW_TAG) # Pretend to be FSW

    pipeline.client_socket = client_socket # Override client socket

    event_forwarder = ReplayForwarder(EventEncoder(config), client_socket, args.realtime)
    ch_forwarder = ReplayForwarder(ChEncoder(config), client_socket, args.realtime)

    # Update handlers
    pipeline.histories.channels = ch_forwarder
    pipeline.histories.events = event_forwarder

    with open(args.raw, "rb") as file_handle:
        pipeline.distributor.on_recv(file_handle.read())
    client_socket.disconnect()
    pipeline.disconnect()


if __name__ == "__main__":
    main()