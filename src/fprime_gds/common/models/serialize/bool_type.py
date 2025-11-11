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


class BoolType(ValueType):
    """
    Representation of a boolean type that will be stored for F prime. True values are stored as a U8 of 0xFF and False
    is stored as a U8 of 0x00.
    """

    TRUE = 0xFF  # Hardcoded
    FALSE = 0x00

    @classmethod
    def validate(cls, val):
        """Validate the given class"""
        if not isinstance(val, bool):
            raise TypeMismatchException(bool, type(val))

    def serialize(self):
        """Serialize a boolean value"""
        if self._val is None:
            raise NotInitializedException(type(self))
        return struct.pack("B", self.TRUE if self._val else self.FALSE)

    def deserialize(self, data, offset):
        """Deserialize boolean value"""
        try:
            int_val = struct.unpack_from("B", data, offset)[0]
            if int_val not in [self.TRUE, self.FALSE]:
                raise TypeRangeException(int_val)
            self._val = int_val == self.TRUE
        except struct.error:
            raise DeserializeException("Not enough bytes to deserialize bool.")

    @classmethod
    def getSize(cls):
        return struct.calcsize("B")  # Hardcoded

    @classmethod
    def getMaxSize(cls):
        """Maximum size of type"""
        return cls.getSize()  # Always the same as getSize
