"""ccsds.apid: APID mapping functions for F´ data"""

from fprime_gds.common.utils.data_desc_type import DataDescType
from fprime.common.models.serialize.numerical_types import NumericalType


class APID(object):
    """APID implementations"""

    # TODO: use the DataDescType configured by loading the dictionary

    @classmethod
    def from_type(cls, data_type: DataDescType):
        """Map from data description type to APID"""
        return data_type.value

    @classmethod
    def from_data(cls, data, packet_descriptor_type: NumericalType):
        """Map from data bytes to APID"""
        packet_descriptor_type.deserialize(data, offset=0)
        return cls.from_type(DataDescType(packet_descriptor_type.val))
