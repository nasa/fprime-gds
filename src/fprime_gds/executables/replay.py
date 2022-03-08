import argparse
import copy
import time
import sys
from pathlib import Path

from fprime_gds.common.pipeline.standard import StandardPipeline
from fprime_gds.common.handlers import DataHandler
from fprime_gds.common.client_socket.client_socket import ThreadedTCPSocketClient, GUI_TAG, FSW_TAG

from fprime_gds.common.data_types.event_data import EventData
from fprime_gds.common.data_types.ch_data import ChData

from fprime_gds.common.encoders.encoder import Encoder
from fprime_gds.common.encoders.event_encoder import EventEncoder
from fprime_gds.common.encoders.ch_encoder import ChEncoder
from fprime_gds.common.utils.config_manager import ConfigManager


# Global tracking tokens
TRACKING = {
    "realtime_slips": 0,
    "out_of_order_packets": 0,
    "realtime_slip_data": []
}


class MultiEncoder(Encoder):
    """ Encodes multiple different object types """

    def __init__(self, config):
        """ Sets up sub-encoders """
        super().__init__(config)
        self.encoders = {
            EventData: EventEncoder(config),
            ChData: ChEncoder(config)
        }

    def encode_api(self, data):
        """ Delegates encoding to sub encoder by type """
        encoder = self.encoders.get(type(data), None)
        if encoder is not None:
            return encoder.encode_api(data)
        print("[WARNING] Cannot handle data of type:", type(data))
        return None


class ReplayForwarder(DataHandler):
    """ Class used to replay data by forwarding packets to GDS """

    def __init__(self, encoder, realtime=False, filter_times=(0, 99999999999999.999999), base=None, filter_after=False):
        """ Setup the forwarder """
        self.last_stamp = None
        self.last_time = None
        self.encoder = encoder
        self.realtime = realtime
        self.filter_times = filter_times
        self.base = base
        self.offset = None
        self.rt_threshold = 0.050 # 50 ms before printing warning
        self.filter_after = filter_after

    @staticmethod
    def as_fraction(time_val):
        """ Convert timeval to fractional time """
        return time_val.seconds + time_val.useconds / 100000.0

    @staticmethod
    def populate_time(time_item, time_fraction):
        """ Populate time item with fractional time """
        time_item.seconds = int(time_fraction)
        time_item.useconds = int((time_fraction - int(time_fraction)) * 100000.0)

    def set_offset_time(self, time_frac):
        """ Sets the first_time time if not set """
        if self.offset is None:
            self.offset = self.base - time_frac

    def get_sleep_time(self, new_stamp):
        """ Get the necessary sleep time """
        now = time.time()
        last_as_fraction = self.as_fraction(self.last_stamp if self.last_stamp is not None else new_stamp)
        new_as_fraction = self.as_fraction(new_stamp)

        # Check out-of-order packets. Ill-ordered packets do not wait
        if last_as_fraction > new_as_fraction:
            TRACKING["out_of_order_packets"] += 1
            self.last_stamp = new_stamp
            return 0.0

        # Non-realtime runs also doe not wait
        if not self.realtime:
            return 0.0

        # Calculate the new sleep time based on what time it is now, and the needed data
        needed_delta = new_as_fraction - last_as_fraction
        current_delta = now - (self.last_time if self.last_time is not None else now)

        # Update the last tracking tokens
        self.last_stamp = new_stamp

        sleep_time_calculate = needed_delta - current_delta
        # Ignore sleeps within threshold
        if abs(sleep_time_calculate) < self.rt_threshold:
            return 0.0
        elif needed_delta < current_delta:
            TRACKING["realtime_slips"] += 1
            if len(TRACKING["realtime_slip_data"]) < 10000:
                TRACKING["realtime_slip_data"].append(abs(sleep_time_calculate))
            return 0.0
        assert sleep_time_calculate >= 0, f"Sleep time must be positive not {sleep_time_calculate}"
        return sleep_time_calculate

    def rewrite_time(self, data):
        """ Rewrite the time of the item w.r.t. the base if set """
        if self.base is None:
            return data
        new_item = copy.copy(data)
        new_time = copy.copy(new_item.time)
        new_item.time = new_time
        fractional = self.as_fraction(new_time)

        self.set_offset_time(fractional)
        self.populate_time(new_time, self.offset + fractional)
        return new_item

    def data_callback(self, data, sender=None):
        """ Encode and send the data packet """
        data_new = self.rewrite_time(data)

        item_time = self.as_fraction((data_new if self.filter_after else data).time)
        # Filter out items for focusing on items
        if item_time < self.filter_times[0] or item_time > self.filter_times[1]:
            return
        data = data_new

        sleep_time = self.get_sleep_time(data.time)
        # Handle realtime
        if self.realtime and sleep_time > 0:
            time.sleep(sleep_time)
        # Update the last time we did something after the sleep
        self.last_time = time.time()

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
    parser.add_argument(
        "-s",
        "--starttime",
        type=float,
        default=0.0,
        help="Filter out all objects before this time in seconds.microseconds format.",
    )
    parser.add_argument(
        "-e",
        "--endtime",
        type=float,
        default=99999999999999.999999,
        help="Filter out all objects after this time in seconds.microseconds format.",
    )
    parser.add_argument(
        "--shift-to-time",
        type=float,
        default=None,
        help="Shift times so the first post-filter record starts at the given time in seconds.microseconds format.",
        dest="shift"
    )
    parser.add_argument("--filter-after-shift", default=False, action="store_true",
                        help="Change filtering to affect post shifted data")
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
    try:
        client_socket.register_to_server(FSW_TAG) # Pretend to be FSW

        pipeline.client_socket = client_socket # Override client socket
        multi_encoder = MultiEncoder(config)
        multi_encoder.register(client_socket)

        forwarder = ReplayForwarder(multi_encoder, args.realtime, (args.starttime, args.endtime),
                                    args.shift, args.filter_after_shift)

        # Update handlers
        pipeline.histories.channels = forwarder
        pipeline.histories.events = forwarder

        with open(args.raw, "rb") as file_handle:
            pipeline.distributor.on_recv(file_handle.read())
    finally:
        client_socket.disconnect()
        pipeline.disconnect()

    print(f"[INFO] Run ended:")
    print(f"    { TRACKING['out_of_order_packets'] } out-of-order packets")
    # Print realtime slip data
    rt_data = TRACKING["realtime_slip_data"]
    if args.realtime and rt_data:
        print(f"    { TRACKING['realtime_slips'] } realtime slips with duration min ~{ min(rt_data) } max ~{ max(rt_data) }")


if __name__ == "__main__":
    main()