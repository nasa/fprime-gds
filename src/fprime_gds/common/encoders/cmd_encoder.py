"""
@brief Encoder for cmd data

This encoder takes in cmd_data objects, serializes them, and sends the results
to all registered senders.

Serialized command format:
    +--------------------------------+          -
    | Header = "A5A5 "               |          |
    | (5 byte string)                |          |
    +--------------------------------+      Added by
    | Destination = "GUI " or "FSW " |       Sender
    | (4 byte string)                |          |
    +--------------------------------+          -
    | Command descriptor             |
    | (0x5A5A5A5A)                   |
    | (4 byte number)                |
    +--------------------------------+
    | Length of descriptor, opcode,  |
    | and argument data              |
    | (4 bytes)                      |
    +--------------------------------+
    | Descriptor type = 0            |
    | (4 bytes)                      |
    +--------------------------------+
    | Op code                        |
    | (4 bytes)                      |
    +--------------------------------+
    | Argument 1 value               |
    +--------------------------------+
    | Argument 2 value               |
    +--------------------------------+
    | ...                            |
    +--------------------------------+
    | Argument n value               |
    +--------------------------------+

@date Created July 9, 2018
@author R. Joseph Paetz

@bug No known bugs
"""

from fprime_gds.common.models.serialize.numerical_types import U32Type

from fprime_gds.common.data_types.cmd_data import CmdData
from fprime_gds.common.utils.config_manager import ConfigManager

from . import encoder


class CmdEncoder(encoder.Encoder):
    """Encoder class for command data"""

    def __init__(self):
        """
        CmdEncoder class constructor

        Returns:
            An initialized CmdEncoder object
        """

        super().__init__()

        self.len_obj = ConfigManager().get_config("msg_len")()
        self.desc_obj = ConfigManager().get_type("FwPacketDescriptorType")()
        self.opcode_obj = ConfigManager().get_type("FwOpcodeType")()

    def encode_api(self, data):
        """
        Encodes the given CmdData object as binary data and returns the result.

        Args:
            data: CmdData object to encode

        Returns:
            Encoded version of the data argument as binary data
        """
        assert isinstance(data, CmdData), "Encoder handling incorrect type"
        cmd_temp = data.get_template()

        desc = U32Type(0x5A5A5A5A).serialize()

        descriptor = (
            ConfigManager().get_type("ComCfg.Apid")("FW_PACKET_COMMAND").serialize()
        )

        self.opcode_obj.val = cmd_temp.get_op_code()
        op_code = self.opcode_obj.serialize()

        arg_data = b""
        for arg in data.get_args():
            arg_data += arg.serialize()

        length_val = len(descriptor) + len(op_code) + len(arg_data)
        self.len_obj.val = length_val
        length = self.len_obj.serialize()

        binary_data = desc + length + descriptor + op_code + arg_data

        return binary_data
