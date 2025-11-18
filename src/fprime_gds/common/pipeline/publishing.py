"""
publishing.py:

This file contains a basic publishing pipeline. It reads and writes data bound for the GDS.

:author: lestarch
"""


from typing import Type

from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.data_types.event_data import EventData
from fprime_gds.common.encoders.ch_encoder import ChEncoder
from fprime_gds.common.encoders.event_encoder import EventEncoder
from fprime_gds.common.transport import RoutingTag, ThreadedTCPSocketClient
from fprime_gds.common.utils.config_manager import ConfigManager

from fprime_gds.common.handlers import DataHandler, MappedRegistrar
from ..models import dictionaries


class PublishingPipeline(DataHandler, MappedRegistrar):
    """ Pipeline for publishing

    This pipeline sets up the following process:

    Data -> Encoder -> Client -> <wire>
    """
    DEFAULT_ENCODERS = {
        "FW_PACKET_LOG": EventEncoder,
        "FW_PACKET_TELEM": ChEncoder
    }

    def __init__(self):
        """
        Set core variables to None or their composition handlers.
        """
        super().__init__()
        self.client_socket = None

        self._dictionaries = dictionaries.Dictionaries()
        self._transport_type = ThreadedTCPSocketClient

    def setup(self, dictionaries):
        """ Set up the publishing pipeline """
        self._dictionaries = dictionaries
        self.client_socket = self.__transport_type()
    
        for id, encoder_class in self.DEFAULT_ENCODERS.items():
            encoder_instance = encoder_class()
            encoder_instance.register(self.client_socket)
            self.register(id, encoder_instance)

    def data_callback(self, data, sender=None):
        """ Publish data """
        if isinstance(data, ChData):
            self.send_to_all("FW_PACKET_TELEM", data)
        elif isinstance(data, EventData):
            self.send_to_all("FW_PACKET_LOG", data)
        return super().data_callback(data, sender)
    
    def publish_channel(self, name, value, time):
        """ Publish channel value using name, time, and value

        Looks up the channel template in the dictionary and constructs a new channel object given the time and value.
        This ChData object is then sent into the outgoing "publish" pipeline.

        """
        template = self._dictionaries.channel_name[name]
        copied_value_object = template.get_type_obj()(value)
        copied_value_object.val = value
        object = ChData(copied_value_object, time, template)
        return self.data_callback(object, self)

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


    def connect(
        self, connection_uri, incoming_tag=RoutingTag.GUI, outgoing_tag=RoutingTag.GUI
    ):
        """Connects to the middleware layer

        Connect to the middleware layer. This connection needs to identify if the object is a a FSW or GUI client. The
        default connection acts as a GUI client sending back to the GUI.

        Args:
            connection_uri: URI of the connection to make
            incoming_tag: this pipeline will act as supplied tag (GUI, FSW). Default: GUI
            outgoing_tag: this pipeline will produce data for supplied tag (FSW, GUI). Default: FSW
        """
        self.client_socket.connect(connection_uri, incoming_tag, outgoing_tag)

    def disconnect(self):
        """ Disconnect from the client socket """
        if self.client_socket is not None:
            self.client_socket.disconnect()

    
