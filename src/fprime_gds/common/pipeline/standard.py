"""
standard.py:

This file contains the necessary functions used to setup a standard pipeline that will pull data from the middle-ware
layer into the python system. This layer is designed to setup the base necessary to running Gds objects up-to the layer
of decoding. This enables users to generate add-in that function above the decoders, and run on a standard pipeline
below.

:author: lestarch
"""

import datetime
import os.path
from pathlib import Path
from typing import Type

from fprime_gds.common.models.serialize.time_type import TimeType

import fprime_gds.common.data_types.cmd_data
import fprime_gds.common.distributor.distributor
import fprime_gds.common.logger.data_logger
from fprime_gds.common.transport import RoutingTag, ThreadedTCPSocketClient
from fprime_gds.common.utils.config_manager import ConfigManager

# Local imports for the sake of composition
from . import encoding, files, histories


class StandardPipeline:
    """
    Class used to encapsulate all of the components of a standard pipeline. The life-cycle of this class follows the
    basic steps:
       1. setup: creates objects needed to read from middle-ware layer and provide data up the stack
       2. register: consumers from this pipeline should register to receive decoder callbacks
       3. run: this pipeline should either take over the standard thread of execution, or be executed on another thread
       4. terminate: called to shutdown the pipeline
    This class provides for basic log files as a fallback for storing events as well. These logs are stored in a given
    directory, which is created on the initialization of this class.
    """

    def __init__(self):
        """
        Set core variables to None or their composition handlers.
        """
        self.distributor = None
        self.client_socket = None
        self.logger = None
        self.dictionary_path = None
        self.up_store = None
        self.down_store = None

        self.__dictionaries = None
        self.__coders = encoding.EncodingDecoding()
        self.__histories = histories.Histories()
        self.__filing = files.Filing()
        self.__transport_type = ThreadedTCPSocketClient

    def setup(
        self,
        config: ConfigManager,
        dictionaries,
        file_store,
        logging_prefix=None,
        data_logging_enabled=True,
    ):
        """
        Setup the standard pipeline for moving data from the middleware layer through the GDS layers using the standard
        patterns. This allows just registering the consumers, and invoking 'setup' all other of the GDS support layer.

        :param config: UNUSED argument; kept for backwards compatibility. ConfigManager is to be accessed via singleton
        :param dictionaries: dictionary path. Used to setup loading of dictionaries.
        :param file_store: uplink/downlink storage directory
        :param logging_prefix: logging prefix. Defaults to not logging at all.
        :param packet_spec: location of packetized telemetry XML specification.
        """
        self.distributor = fprime_gds.common.distributor.distributor.Distributor()
        self.client_socket = self.__transport_type()
        # File storage configuration for uplink and downlink
        self.up_store = Path(file_store) / "fprime-uplink"
        self.down_store = Path(file_store) / "fprime-downlink"
        try:
            self.down_store.mkdir(parents=True, exist_ok=True)
            self.up_store.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            raise PermissionError(
                f"{file_store} is not writable. Fix permissions or change storage directory with --file-storage-directory."
            )
        self.__dictionaries = dictionaries
        self.coders.setup_coders(
            self.dictionaries, self.distributor, self.client_socket
        )
        self.histories.setup_histories(self.coders)
        self.files.setup_file_handling(
            self.down_store,
            self.coders.file_encoder,
            self.coders.file_decoder,
            self.distributor,
            logging_prefix,
        )
        # Register distributor to client socket
        self.client_socket.register(self.distributor)
        # Final setup step is to make a logging directory, and register in the logger
        if logging_prefix and data_logging_enabled:
            self.setup_logging(logging_prefix)

    @property
    def transport_implementation(self):
        """Get implementation type for transport"""
        return self.__transport_type

    @transport_implementation.setter
    def transport_implementation(self, transport_type: Type[None]):
        """Set the implementation type for transport"""
        assert (
            self.client_socket is None
        ), "Cannot setup transport implementation type after setup"
        self.__transport_type = transport_type

    @classmethod
    def get_dated_logging_dir(cls, prefix=os.path.expanduser("~")):
        """
        Sets up the dated subdirectory based upon a given prefix

        :param prefix:
        :return: Path to new directory where logs will be stored for this pipeline
        """
        # Setup log file location
        dts = datetime.datetime.now()
        log_dir = os.path.join(prefix, dts.strftime("%Y-%m-%dT%H:%M:%S.%f"))
        # Make the directories if they do not exit
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        return log_dir

    def setup_logging(self, log_dir):
        """
        Setup logging based on the logging prefix supplied

        :param log_dir: logging output directory
        """
        # Setup the logging pipeline (register it to all its data sources)
        logger = fprime_gds.common.logger.data_logger.DataLogger(
            log_dir, verbose=True, csv=True
        )
        self.logger = logger
        self.coders.register_channel_consumer(self.logger)
        self.coders.register_event_consumer(self.logger)
        self.coders.register_command_consumer(self.logger)
        self.coders.register_packet_consumer(self.logger)
        self.client_socket.register(self.logger)

    def connect(
        self, connection_uri, incoming_tag=RoutingTag.GUI, outgoing_tag=RoutingTag.FSW
    ):
        """Connects to the middleware layer

        Connect to the middleware layer. This connection needs to identify if the object is a a FSW or GUI client. The
        default connection acts as a GUI client sending to FSW.

        Note: this function provides backwards compatibility with historical versions of this connect method of the form
        pipeline.connect(host, port). This version explicitly supplies a hostname without port, and integer port. No
        other arguments are excepted. Use is discouraged.

        Args:
            connection_uri: URI of the connection to make
            incoming_tag: this pipeline will act as supplied tag (GUI, FSW). Default: GUI
            outgoing_tag: this pipeline will produce data for supplied tag (FSW, GUI). Default: FSW
        """
        # Backwards compatibility with the old method .connect(host, port)
        if (
            isinstance(incoming_tag, int)
            and ":" not in connection_uri
            and outgoing_tag == RoutingTag.FSW
        ):
            connection_uri = f"{connection_uri}:{incoming_tag}"
            incoming_tag = RoutingTag.GUI
        self.client_socket.connect(connection_uri, incoming_tag, outgoing_tag)

    def disconnect(self):
        """
        Disconnect from socket
        """
        try:
            if self.client_socket is not None:
                self.client_socket.disconnect()
        finally:
            if self.files is not None and self.files.uplinker is not None:
                self.files.uplinker.exit()

    def send_command(self, command, args):
        """Sends commands to the encoder and history.

        :param command: command id from dictionary to get command template
        :param args: arguments to process
        """
        if isinstance(command, str):
            command_template = self.dictionaries.command_name[command]
        else:
            command_template = self.dictionaries.command_id[command]
        cmd_data = fprime_gds.common.data_types.cmd_data.CmdData(
            tuple(args), command_template
        )
        cmd_data.time = TimeType()
        cmd_data.time.set_datetime(datetime.datetime.now(), TimeType.TimeBase("TB_WORKSTATION_TIME"))
        self.coders.send_command(cmd_data)

    @property
    def dictionaries(self):
        """
        Get a dictionaries object

        :return: dictionaries composition
        """
        return self.__dictionaries

    @property
    def coders(self):
        """
        Get a coders object

        :return: coders composition
        """
        return self.__coders

    @property
    def histories(self):
        """
        Get a histories object

        :return: histories composition
        """
        return self.__histories

    @property
    def files(self):
        """
        Files member property

        :return: filing compositions
        """
        return self.__filing

    @property
    def dictionaries(self):
        """Dictionaries member"""
        return self.__dictionaries
