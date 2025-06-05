""" ccsds.apid: APID mapping functions for F´ data """
from fprime_gds.common.utils.data_desc_type import DataDescType
from fprime.common.models.serialize.numerical_types import U32Type

class APID(object):
    """ APID implementations """
    #TODO: use the DataDescType configured by loading the dictionary

    @classmethod
    def from_type(cls, data_type: DataDescType):
        """ Map from data description type to APID """
        return data_type.value

    @classmethod
    def from_data(cls, data):
        """ Map from data bytes to APID """
        u32_type = U32Type()
        u32_type.deserialize(data, offset=0)
        return cls.from_type(DataDescType(u32_type.val))
