import argparse
import copy
import time
import sys
import functools
from pathlib import Path

try:
    import zmq
except ImportError:
    zmq = None
from fprime_gds.common.pipeline.standard import StandardPipeline
from fprime_gds.common.handlers import DataHandler


from fprime_gds.common.transport import ThreadedTCPSocketClient, RoutingTag
try:
    from fprime_gds.common.zmq_transport import ZmqClient
except ImportError:
    ZmqClient = None


from fprime_gds.common.data_types.event_data import EventData
from fprime_gds.common.data_types.ch_data import ChData

from fprime_gds.common.encoders.encoder import Encoder
from fprime_gds.common.encoders.event_encoder import EventEncoder
from fprime_gds.common.encoders.ch_encoder import ChEncoder
from fprime_gds.common.utils.config_manager import ConfigManager

CHUNK_SIZE = 1024 * 1024


def as_fraction(time_val):
    """Convert timeval to fractional time"""
    time_val = getattr(time_val, "time", time_val)
    return time_val.seconds + time_val.useconds / 1000000.0


class MultiEncoder(Encoder):
    """Encodes multiple different object types"""

    def __init__(self, config):
        """Sets up sub-encoders"""
        super().__init__(config)
        self.encoders = {EventData: EventEncoder(config), ChData: ChEncoder(config)}

    def encode_api(self, data):
        """Delegates encoding to sub encoder by type"""
        encoder = self.encoders.get(type(data), None)
        if encoder is not None:
            return encoder.encode_api(data)
        print("[WARNING] Cannot handle data of type:", type(data))
        return None


class ChainableDataHandler(DataHandler):
    """Chainable data handler"""

    def __init__(self):
        """Constructor"""
        self.next = None

    def data_callback(self, data, sender=None):
        """Callback that passes data onward"""
        if self.next is not None:
            self.next.data_callback(data, self)


class DataWatcher(ChainableDataHandler):
    """Handler for watching data"""

    def __init__(self, watched_ids=None):
        """Initialize this watcher"""
        super().__init__()
        self.watchers = {
            watch_id: None for watch_id in (watched_ids if watched_ids else [])
        }

    def data_callback(self, item, sender=None):
        """Look at data for watchers"""
        if item.id in self.watchers:
            time_as_fraction = as_fraction(item)
            print(f"[WATCH {time.time()}] {time_as_fraction} {item}")
        super().data_callback(item, self)


class SleepingDataHandler(ChainableDataHandler):
    """Sleeping data handler"""

    def __init__(self, threshold=0.50):
        """Sleep"""
        super().__init__()
        self.initial_data_time = None
        self.initial_program_time = None
        self.threshold = threshold
        self.slip_count = 0
        self.slip_history = []
        self.last_sleep_item_time = None

    def data_callback(self, data, sender=None):
        """Sleeps based on the delta from the start of the run"""
        current_data_time = as_fraction(data)
        now = time.time()
        if not self.initial_data_time or not self.initial_program_time:
            self.initial_data_time = current_data_time
            self.initial_program_time = now
            self.last_sleep_item_time = current_data_time
        rt_delta = now - self.initial_program_time
        data_delta = current_data_time - self.initial_data_time

        # Check if sleep is needed
        sleep_time = data_delta - rt_delta
        if (
            sleep_time > self.threshold
            and current_data_time > self.last_sleep_item_time
        ):
            self.last_sleep_item_time = current_data_time
            time.sleep(sleep_time)
        elif (
            sleep_time < -self.threshold
            and current_data_time > self.last_sleep_item_time
        ):
            self.slip_count += 1
            if len(self.slip_history) < 10000:
                self.slip_history.append(abs(sleep_time))
        self.last_item_time = current_data_time
        super().data_callback(data, self)


class ShiftyDataHandler(ChainableDataHandler):
    """Data handler used to shift data"""

    def __init__(self, base):
        """Initialize"""
        super().__init__()
        self.base = base
        self.offset = None

    def rewrite_time(self, data):
        """Rewrite the time of the item w.r.t. the base if set"""
        if self.base is None:
            return data
        new_item = copy.copy(data)
        new_time = copy.copy(new_item.time)
        new_item.time = new_time
        fractional = as_fraction(new_time)

        self.set_offset_time(fractional)
        self.populate_time(new_time, self.offset + fractional)
        return new_item

    def set_offset_time(self, time_frac):
        """Sets the first_time time if not set"""
        if self.offset is None:
            self.offset = self.base - time_frac

    def data_callback(self, data, sender=None):
        """Data callback that shifts data"""
        data = self.rewrite_time(data)
        super().data_callback(data, self)

    @staticmethod
    def populate_time(time_item, time_fraction):
        """Populate time item with fractional time"""
        time_item.seconds = int(time_fraction)
        time_item.useconds = int((time_fraction - int(time_fraction)) * 100000.0)


class FilteringDataHandler(ChainableDataHandler):
    """Filters data"""

    def __init__(self, filters=(0, 99999999999999.999999)):
        """Filter times"""
        super().__init__()
        self.filters = filters

    def data_callback(self, data, sender=None):
        """Callback to do"""
        item_time = as_fraction(data)
        if item_time < self.filters[0] or item_time > self.filters[1]:
            return
        super().data_callback(data, self)


class TrackingDataHandler(ChainableDataHandler):
    """Tracks various items about our data"""

    def __init__(self, verbose=False):
        """Initialize"""
        super().__init__()
        self.verbose = verbose
        self.count = 0
        self.bounding = (None, None)
        self.last_times = {}
        self.ooo_counts = {}

    def data_callback(self, data, sender=None):
        """Track items"""
        self.count += 1
        current_time = as_fraction(data)
        if not self.verbose and (self.count % 100) == 0:
            print(f"[INFO] Processing item: {self.count}          ", end="\r")
        # Channel Key
        ooo_key = type(data).__name__ + "-" + data.template.get_full_name()
        last_seen_yolo_time = self.last_times.get(ooo_key, 0.000)
        if last_seen_yolo_time > current_time:
            self.ooo_counts[ooo_key] = self.ooo_counts.get(ooo_key, 0) + 1
        else:
            self.last_times[ooo_key] = current_time

        self.bounding = (
            current_time if self.bounding[0] is None else self.bounding[0],
            current_time,
        )
        super().data_callback(data, self)


class ReplayForwarder(DataHandler):
    """Class used to replay data by forwarding packets to GDS"""

    def __init__(self, encoder, handlers):
        """Setup the forwarder"""
        self.handlers = handlers + [encoder]

        def chainer(last, current):
            """Chains the callbacks together"""
            last.next = current
            return current

        functools.reduce(chainer, self.handlers)

    def data_callback(self, data, sender=None):
        """Encode and send the data packet"""
        self.handlers[0].data_callback(data, self)


def parse_args():
    """Setup argument parser"""
    parser = argparse.ArgumentParser(description="A replayer for RAW GUI logged data")
    parser.add_argument(
        "-d",
        "--dictionary",
        type=str,
        default=None,
        help='path from the current working directory to the "<project name>Dictionary.xml" file for the project you\'re using the API with; if unused, tries to search the current working directory for such a file',
    )
    # May use ZMQ transportation layer if zmq package is available
    if zmq is not None:
        parser.add_argument(
            "--zmq",
            dest="zmq",
            action="store_true",
            help="Switch to using the ZMQ transportation layer",
            default=False,
        )
        parser.add_argument(
            "--zmq-server",
            dest="zmq_server",
            action="store_true",
            help="Sets the ZMQ connection to be a server. Default: false (client)",
            default=False,
        )
        parser.add_argument(
            "--zmq-transport",
            dest="zmq_transport",
            action="store",
            type=str,
            help="Sets ZMQ transport layer url for use when --zmq has been supplied [default: %(default)s]",
            default="tcp://localhost:5005",  # "ipc:///tmp/fprime-ipc-0"
        )
    parser.add_argument(
        "--tts-port",
        dest="tts_port",
        action="store",
        type=int,
        help="Set the threaded TCP socket server port [default: %(default)s]",
        default=50050,
    )
    parser.add_argument(
        "--tts-addr",
        dest="tts_addr",
        action="store",
        type=str,
        help="Set the threaded TCP socket server address [default: %(default)s]",
        default="0.0.0.0",
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
        "-w",
        "--watch",
        type=lambda x: int(x, 0),
        action="append",
        default=None,
        help="Watch the values of a specific id in the system.",
    )
    parser.add_argument(
        "--shift-to-time",
        type=float,
        default=None,
        help="Shift times so the first post-filter record starts at the given time in seconds.microseconds format.",
        dest="shift",
    )
    parser.add_argument(
        "--filter-after-shift",
        default=False,
        action="store_true",
        help="Change filtering to affect post shifted data",
    )
    parser.add_argument(
        "--realtime",
        default=False,
        action="store_true",
        help="Delay replay to be pseudo-realtime",
    )
    parser.add_argument("raw", help="Raw logfile to replay")
    return parser.parse_args()


def main():
    """ """
    args = parse_args()
    use_zmq = ZmqClient is not None and args.zmq

    # Build hanndler chain for processing
    # Needed for tracking purposes
    tracker_pre = TrackingDataHandler(True)
    tracker_post = TrackingDataHandler(False)
    filtering = [FilteringDataHandler((args.starttime, args.endtime))]
    shifter = [ShiftyDataHandler(args.shift)]

    # Build handlers set for processing data
    handlers = [tracker_pre]
    if not args.filter_after_shift:
        handlers += filtering
    if args.shift:
        handlers += shifter
    if args.filter_after_shift:
        handlers += filtering
    handlers += [DataWatcher(args.watch), tracker_post]
    sleep_handler = None
    if args.realtime:
        sleep_handler = SleepingDataHandler()
        handlers += [sleep_handler]

    # Config manager setup
    config = ConfigManager()

    if not Path(args.raw).exists():
        print(f"[ERROR] {args.raw} does not exist", file=sys.stderr)

    # Setup standard pipeline
    pipeline = StandardPipeline()
    pipeline.transport_implementation = ZmqClient if use_zmq else ThreadedTCPSocketClient

    time_pairs = ((None, None), (None, None))
    forwarder = None
    start_time = 0.0
    try:
        multi_encoder = MultiEncoder(config)
        forwarder = lambda *_, **__: ReplayForwarder(multi_encoder, handlers, *_, **__)

        pipeline.histories.implementation = forwarder
        pipeline.setup(config, args.dictionary, "/tmp/replay-store", None, None)
        pipeline.client_socket.stop()

        # Handle post setup registrations
        multi_encoder.register(pipeline.client_socket)
        if use_zmq:
            pipeline.client_socket.zmq.make_server()
        pipeline.connect(args.zmq_transport if use_zmq else f"tcp://{ args.tts_addr }:{ args.tts_port }",
                         RoutingTag.FSW, RoutingTag.GUI)

        with open(args.raw, "rb") as file_handle:
            print("[INFO] Reading data from disk. This may take a few moments.")
            data = file_handle.read()
            print(
                "[INFO] Processing raw data through: ",
                [type(item).__name__ for item in handlers],
            )
            start_time = time.time()
            pipeline.distributor.on_recv(data)
    finally:
        end_time = time.time()
        if forwarder is not None:
            time_pairs = (tracker_pre.bounding, tracker_post.bounding)
        pipeline.disconnect()

        print(
            f"[INFO] Run ended with total processed items: {tracker_post.count}/{tracker_pre.count} in {end_time - start_time} S"
        )
        time_data = time_pairs[0]
        total_time = (time_data[1] if time_data[1] is not None else 0) - (
            time_data[0] if time_data[0] is not None else 0
        )
        print(
            f"    Time range {time_pairs[0]} shifted/filtered to {time_pairs[1]} with total time range of {total_time} S"
        )
        for tracker, stage in [(tracker_pre, "input"), (tracker_post, "output")]:
            for type_prefix in ["Ch", "Ev"]:
                print(
                    f"    { sum([value for key, value in tracker.ooo_counts.items() if key.startswith(type_prefix)]) } out-of-order {type_prefix} packets on {stage}"
                )
                for key_name, key_value in tracker.ooo_counts.items():
                    if key_name.startswith(type_prefix):
                        print(f"        {key_name} (Missing Update): {key_value}")
        # Print realtime slip data
        if args.realtime and sleep_handler.slip_history:
            print(
                f"  **** { sleep_handler.slip_count } realtime slips with duration min ~{ min(sleep_handler.slip_history) } max ~{ max(sleep_handler.slip_history) }"
            )
        sys.stdout.flush()


if __name__ == "__main__":
    main()
