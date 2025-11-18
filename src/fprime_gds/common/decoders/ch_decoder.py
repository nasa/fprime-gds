"""
@brief Channel Decoder class used to parse binary channel telemetry data

Decoders are responsible for taking in serialized data and parsing it into
objects. Decoders receive serialized data (that had a specific descriptor) from
a distributer that it has been registered to. The distributer will send the
binary data after removing any length and descriptor headers.

Example data that would be sent to a decoder that parses channels:
    +-------------------+---------------------+------------ - - -
    | ID (4 bytes) | Time Tag (11 bytes) | Data....
    +-------------------+---------------------+------------ - - -

@date Created July 11, 2018
@author R. Joseph Paetz

@bug No known bugs
"""

from fprime_gds.common.models.serialize.time_type import TimeType

from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.decoders.decoder import Decoder, DecodingException
from fprime_gds.common.utils.config_manager import ConfigManager


class ChDecoder(Decoder):
    """Decoder class for Channel data"""

    def __init__(self, ch_dict):
        """
        ChDecoder class constructor

        Args:
            ch_dict: Channel telemetry dictionary. Channel IDs should be keys
                     and ChTemplate objects should be values

        Returns:
            An initialized channel decoder object.
        """
        super().__init__()

        self.__dict = ch_dict
        self.id_obj = ConfigManager().get_type("FwChanIdType")()

    def decode_api(self, data):
        """
        Decodes the given data and returns the result.

        This function allows for non-registered code to call the same decoding
        code as is used to parse data passed to the data_callback function.

        Args:
            data: Binary telemetry channel data to decode

        Returns:
            Parsed version of the channel telemetry data in the form of a
            ChData object or None if the data is not decodable
        """
        ptr = 0

        # list for decoded channel values
        ch_list = []

        while ptr < len(data):

            # Decode Ch ID here...
            self.id_obj.deserialize(data, ptr)
            ptr += self.id_obj.getSize()
            ch_id = self.id_obj.val

            # Decode time...
            ch_time = TimeType()
            ch_time.deserialize(data, ptr)
            ptr += ch_time.getSize()

            if ch_id not in self.__dict:
                msg = f"Channel {ch_id} not found in dictionary"
                raise DecodingException(msg)
            # Retrieve the template instance for this channel
            ch_temp = self.__dict[ch_id]

            try:
                val_obj = self.decode_ch_val(data, ptr, ch_temp)
            except Exception as exc:
                msg = f"Channel {ch_temp.name} failed to decode: {exc}"
                raise DecodingException(msg)
            ch_list.append(ChData(val_obj, ch_time, ch_temp))
            ptr += val_obj.getSize()
        return ch_list

    @staticmethod
    def decode_ch_val(val_data, offset, template):
        """
        Decodes the given channel's value from the given data

        Args:
            val_data: Data to parse the value out of
            offset: Location in val_data to start the parsing
            template: Channel Template object for the channel

        Returns:
            The channel's value as an instance of a class derived from
            the BaseType class. The val_data has been deserialized using this
            object, and so the channel value can be retrieved from the obj's
            val field.
        """
        val_obj = template.get_type_obj()()
        val_obj.deserialize(val_data, offset)
        return val_obj
