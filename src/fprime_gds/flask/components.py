"""
flask/components.py:

This sets up the primary data components that allow Flask to connect into the system. This is where the standard
pipeline and other components are created to interact with Flask.
"""
import os
import sys

import fprime_gds.common.pipeline.standard
from fprime_gds.common.history.ram import SelfCleaningRamHistory

try:
    from fprime_gds.common.zmq_transport import ZmqClient
except ImportError:
    ZmqClient = None
from fprime_gds.common.transport import ThreadedTCPSocketClient

# Module variables, should remain hidden. These are singleton top-level objects used by Flask, and its various
# blueprints needed to run the system.
__PIPELINE = None


class FlaskEndpointRamHistory(SelfCleaningRamHistory):
    """A RAM history that is designed to work with the Flask/HTTP endpoints

    Counts object as the objects are submitted into the history tracking a total number of object tracked. During
    retrieval of the object, a counter value is saved w.r.t. the session token such that the response may be augmented
    with a validation count of objects consistent with this request. This is designed to help track GDS performance
    and track missing/lost data.

    In addition, this history creates new session tokens and uses them when a session token has not been supplied. In
    this way, HTTP clients are not free to create (potentially colliding) session tokens.
    """

    def __init__(self):
        """Constructor"""
        super().__init__()
        self.count = 0
        self.count_offsets = {}
        self.count_values = {}

    def data_callback(self, data, sender=None):
        """Counts this object before adding to history

        Callback passed in data. This variant counts the object that is supplied and passes the object back out to the
        parent history in order to store this object in the history.

        :param data: object to store
        """
        with self.lock:
            self.count += 1
            super().data_callback(data, sender)

    def retrieve(self, start=None):
        """Retrieve objects and store current count

        Stash the current count of objects w.r.t the supplied session when supplied and then retrieve the objects in
        history through the parent. In this way the current count of objects w.r.t. the session is kept consistent with
        the last call through this retrieve function.
        """
        with self.lock:

            if start is not None:
                if start not in self.retrieved_cursors:
                    self.count_offsets[start] = self.count
                self.count_values[start] = self.count - self.count_offsets[start]
            return super().retrieve(start)

    def get_seen_count(self, start=None):
        """Get the count of the seen items at the time of the last retrieve call"""
        with self.lock:
            return self.count_values.get(start, self.count)


def setup_pipelined_components(
    debug,
    logger,
    config,
    dictionary,
    down_store,
    log_dir,
    tts_address,
    tts_port,
    zmq_transport,
):
    """
    Setup the standard pipeline and related components. This is done once, and then the resulting singletons are
    returned so that one object is used throughout the system.

    :param debug: used to prevent the construction of the standard pipeline
    :param logger: logger to use for output
    :param config: GDS configuration
    :param dictionary: path to F prime dictionary
    :param down_store:
    :param log_dir: log directory to write logs to, and serve logs from
    :param tts_address: address to the middleware layer
    :param tts_port: port of the middleware layer
    :param zmq_transport: set to zmq transport if using ZMQ or None to use TTS
    :return: F prime pipeline
    """
    global __PIPELINE
    if (
        __PIPELINE is None
        and not debug
        or os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    ):
        if zmq_transport is not None and ZmqClient is None:
            print("[ERROR] ZMQ transportation is not available.", file=sys.stderr)
            sys.exit(-1)
        connection_uri = (
            zmq_transport
            if zmq_transport is not None
            else f"tcp://{ tts_address }:{ tts_port }"
        )
        pipeline = fprime_gds.common.pipeline.standard.StandardPipeline()
        pipeline.histories.implementation = FlaskEndpointRamHistory
        pipeline.transport_implementation = (
            ZmqClient if zmq_transport is not None else ThreadedTCPSocketClient
        )
        pipeline.setup(config, dictionary, down_store, logging_prefix=log_dir)

        logger.info(
            f"Connecting to GDS at: { connection_uri } from pid: { os.getpid() }"
        )
        pipeline.connect(connection_uri)
        __PIPELINE = pipeline
    return __PIPELINE


def get_pipelined_components():
    """
    Returns the setup pipelined components, or raises exception if not setup yet.

    :return: F prime pipeline
    """
    assert __PIPELINE is not None, "Pipeline must be setup before use"
    return __PIPELINE
