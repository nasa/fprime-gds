"""
numerical_types.py:

A file that contains the definitions for all the integer types provided as part of F prime.  F prime supports integers
that map to stdint.h integer sizes, that is, 8-bit, 16-bit, 32-bit, and 64-bit signed and unsigned integers.

@author mstarch
"""

import abc
import struct

from .type_base import ValueType
from .type_exceptions import (
    DeserializeException,
    NotInitializedException,
    TypeMismatchException,
    TypeRangeException,
)


class NumericalType(ValueType, abc.ABC):
    """Numerical types that can be serialized using struct and are of some power of 2 byte width"""

    @classmethod
    def get_canonical_name(cls):
        """Returns the fprime C++ name for the type"""
        return cls.__name__.replace("Type", "")

    @classmethod
    @abc.abstractmethod
    def get_bits(cls):
        """Gets the integer bits of a given type"""

    @classmethod
    def getSize(cls):
        """Gets the size of the integer based on the size specified in the class name"""
        return int(cls.get_bits() >> 3)  # Divide by 8 quickly

    @classmethod
    def getMaxSize(cls):
        """Maximum size of type"""
        return cls.getSize()  # Always the same as getSize

    @staticmethod
    @abc.abstractmethod
    def get_serialize_format():
        """Gets the format serialization string such that the class can be serialized via struct"""
        raise NotImplementedError("get_serialize_format")

    def serialize(self):
        """Serializes this type using struct and the val property"""
        if self._val is None:
            raise NotInitializedException(type(self))
        return struct.pack(self.get_serialize_format(), self._val)

    def deserialize(self, data, offset):
        """Serializes this type using struct and the val property"""
        try:
            self._val = struct.unpack_from(self.get_serialize_format(), data, offset)[0]
        except struct.error as err:
            raise DeserializeException(str(err))


class IntegerType(NumericalType, abc.ABC):
    """Base class that represents all integer common functions"""

    @classmethod
    @abc.abstractmethod
    def range(cls):
        """Gets signed/unsigned of this type"""

    @classmethod
    def validate(cls, val):
        """Validates the given integer."""
        if not isinstance(val, int):
            raise TypeMismatchException(int, type(val))
        min_val, max_val = cls.range()
        if val < min_val or val > max_val:
            raise TypeRangeException(val)


class FloatType(NumericalType, abc.ABC):
    """Base class that represents all float common functions"""

    @classmethod
    def validate(cls, val):
        """Validates the given integer."""
        if not isinstance(val, (float, int)):
            raise TypeMismatchException(float, type(val))


class I8Type(IntegerType):
    """Single byte integer type. Represents C chars"""

    @classmethod
    def range(cls):
        """Gets signed/unsigned of this type"""
        return (-128, 127)

    @classmethod
    def get_bits(cls):
        """Get the bit count of this type"""
        return 8

    @staticmethod
    def get_serialize_format():
        """Allows serialization using struct"""
        return "b"


class I16Type(IntegerType):
    """Double byte integer type. Represents C shorts"""

    @classmethod
    def range(cls):
        """Gets signed/unsigned of this type"""
        return (-32768, 32767)

    @classmethod
    def get_bits(cls):
        """Get the bit count of this type"""
        return 16

    @staticmethod
    def get_serialize_format():
        """Allows serialization using struct"""
        return ">h"


class I32Type(IntegerType):
    """Four byte integer type. Represents C int32_t,"""

    @classmethod
    def range(cls):
        """Gets signed/unsigned of this type"""
        return (-2147483648, 2147483647)

    @classmethod
    def get_bits(cls):
        """Get the bit count of this type"""
        return 32

    @staticmethod
    def get_serialize_format():
        """Allows serialization using struct"""
        return ">i"


class I64Type(IntegerType):
    """Eight byte integer type. Represents C int64_t,"""

    @classmethod
    def range(cls):
        """Gets signed/unsigned of this type"""
        return (-9223372036854775808, 9223372036854775807)

    @classmethod
    def get_bits(cls):
        """Get the bit count of this type"""
        return 64

    @staticmethod
    def get_serialize_format():
        """Allows serialization using struct"""
        return ">q"


class U8Type(IntegerType):
    """Single byte integer type. Represents C chars"""

    @classmethod
    def range(cls):
        """Gets signed/unsigned of this type"""
        return (0, 0xFF)

    @classmethod
    def get_bits(cls):
        """Get the bit count of this type"""
        return 8

    @staticmethod
    def get_serialize_format():
        """Allows serialization using struct"""
        return "B"


class U16Type(IntegerType):
    """Double byte integer type. Represents C shorts"""

    @classmethod
    def range(cls):
        """Gets signed/unsigned of this type"""
        return (0, 0xFFFF)

    @classmethod
    def get_bits(cls):
        """Get the bit count of this type"""
        return 16

    @staticmethod
    def get_serialize_format():
        """Allows serialization using struct"""
        return ">H"


class U32Type(IntegerType):
    """Four byte integer type. Represents C unt32_t,"""

    @classmethod
    def range(cls):
        """Gets signed/unsigned of this type"""
        return (0, 0xFFFFFFFF)

    @classmethod
    def get_bits(cls):
        """Get the bit count of this type"""
        return 32

    @staticmethod
    def get_serialize_format():
        """Allows serialization using struct"""
        return ">I"


class U64Type(IntegerType):
    """Eight byte integer type. Represents C unt64_t,"""

    @classmethod
    def range(cls):
        """Gets signed/unsigned of this type"""
        return (0, 0xFFFFFFFFFFFFFFFF)

    @classmethod
    def get_bits(cls):
        """Get the bit count of this type"""
        return 64

    @staticmethod
    def get_serialize_format():
        """Allows serialization using struct"""
        return ">Q"


class F32Type(FloatType):
    """Eight byte integer type. Represents C unt64_t,"""

    @classmethod
    def get_bits(cls):
        """Get the bit count of this type"""
        return 32

    @staticmethod
    def get_serialize_format():
        """Allows serialization using struct"""
        return ">f"


class F64Type(FloatType):
    """Eight byte integer type. Represents C unt64_t,"""

    @classmethod
    def get_bits(cls):
        """Get the bit count of this type"""
        return 64

    @staticmethod
    def get_serialize_format():
        """Allows serialization using struct"""
        return ">d"
