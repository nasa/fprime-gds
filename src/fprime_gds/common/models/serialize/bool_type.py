"""
Created on Dec 18, 2014
@author: tcanham, reder
"""

import struct

from .type_base import ValueType
from .type_exceptions import (
    DeserializeException,
    NotInitializedException,
    TypeMismatchException,
    TypeRangeException,
)
from fprime_gds.common.utils.config_manager import ConfigManager


class BoolType(ValueType):
    """
    Representation of a boolean type that will be stored for F prime. True values are stored as a U8 of 0xFF and False
    is stored as a U8 of 0x00.
    """

    @classmethod
    def validate(cls, val):
        """Validate the given class"""
        if not isinstance(val, bool):
            raise TypeMismatchException(bool, type(val))

    def serialize(self):
        """Serialize a boolean value"""
        if self._val is None:
            raise NotInitializedException(type(self))
        return struct.pack(
            "B",
            (
                ConfigManager().get_constant("FW_SERIALIZE_TRUE_VALUE")
                if self._val
                else ConfigManager().get_constant("FW_SERIALIZE_FALSE_VALUE")
            ),
        )

    def deserialize(self, data, offset):
        """Deserialize boolean value"""
        TRUE_VAL = ConfigManager().get_constant("FW_SERIALIZE_TRUE_VALUE")
        FALSE_VAL = ConfigManager().get_constant("FW_SERIALIZE_FALSE_VALUE")
        try:
            int_val = struct.unpack_from("B", data, offset)[0]
            if int_val not in [TRUE_VAL, FALSE_VAL]:
                raise TypeRangeException(int_val)
            self._val = int_val == TRUE_VAL
        except struct.error:
            raise DeserializeException("Not enough bytes to deserialize bool.")

    @classmethod
    def getSize(cls):
        return struct.calcsize("B")

    @classmethod
    def getMaxSize(cls):
        """Maximum size of type"""
        return cls.getSize()  # Always the same as getSize
