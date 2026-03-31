"""Generic representation of autocoded array types

Created on May 29, 2020
@author: jishii
"""

import struct

from .type_base import DictionaryType
from .type_exceptions import (
    ArrayLengthException,
    NotInitializedException,
    TypeMismatchException,
    DeserializeException,
)
from .numerical_types import NumericalType


class ArrayType(DictionaryType):
    """Generic fixed-size array type representation.

    Represents a custom named type of a fixed number of like members, each of which are other types in the system.
    """

    @classmethod
    def construct_type(cls, name, member_type, length, format, default=None):
        """Constructs a sub-array type

        Constructs a new sub-type of array to represent an array of the given name, member type, length, and format
        string.

        Args:
            name: name of the array subtype
            member_type: type of the members of the array subtype
            length: length of the array subtype
            format: format string for members of the array subtype
            default [list]: default value for the array
        """
        return DictionaryType.construct_type(
            cls, name, MEMBER_TYPE=member_type, LENGTH=length, FORMAT=format, DEFAULT=default
        )

    @classmethod
    def validate(cls, val):
        """Validates the values of the array"""
        if not isinstance(val, (tuple, list)):
            raise TypeMismatchException(list, type(val))
        if len(val) != cls.LENGTH:
            raise ArrayLengthException(cls.MEMBER_TYPE, cls.LENGTH, len(val))
        for i in range(cls.LENGTH):
            cls.MEMBER_TYPE.validate(val[i])

    def _is_numerical_array(self) -> bool:
        return issubclass(self.MEMBER_TYPE, NumericalType)

    @property
    def val(self) -> list:
        """
        The .val property typically returns the python-native type. This the python native type closes to a serializable
        without generating full classes would be a dictionary (anonymous object). This returns such an object.

        :return dictionary of member names to python values of member keys
        """
        if self._val is None:
            return None
        elif self._is_numerical_array():
            return list(self._val)
        else:
            return [item.val for item in self._val]

    @property
    def formatted_val(self) -> list:
        """
        Format all the elements of array according to the arr_format.
        Note 1: All elements will be cast to str
        Note 2: If a member is a serializable will call serializable formatted_val
        :return a formatted array
        """
        result = []
        if self._is_numerical_array():
            for item in self._val:
                result.append(self.FORMAT.format(item))
        else:
            for item in self._val:
                if hasattr(item, "formatted_val"):
                    result.append(item.formatted_val)
                else:
                    result.append(self.FORMAT.format(item.val))
        return result

    @val.setter
    def val(self, val: list):
        """
        The .val property typically returns the python-native type. This the python native type closes to a serializable
        without generating full classes would be a dictionary (anonymous object). This takes such an object and sets the
        member val list from it.

        :param val: dictionary containing python types to key names. This
        """
        self.validate(val)
        if self._is_numerical_array():
            items = list(val)
        else:
            items = [self.MEMBER_TYPE(item) for item in val]
        self._val = items

    def to_jsonable(self):
        """
        JSONable array object format
        """
        if self._val is None:
            vals = None
        elif self._is_numerical_array():
            vals = list(self._val)
        else:
            vals = [member.val for member in self._val]
        return {
            "name": self.__class__.__name__,
            "type": self.__class__.__name__,
            "size": self.LENGTH,
            "format": self.FORMAT,
            "value_type": repr(self.MEMBER_TYPE()),
            "values": vals,
        }

    def serialize(self):
        """Serialize the array by serializing the elements one by one"""
        if self.val is None:
            raise NotInitializedException(type(self))
        if self._is_numerical_array():
            value_format_raw = self.MEMBER_TYPE().get_serialize_format()
            value_endian = ''
            if self.MEMBER_TYPE.getSize() > 1:
                assert value_format_raw[0] in ('>', '<'), \
                       f'Expected explicit endian numerical type format but found {value_format_raw}'
                value_endian = value_format_raw[0]
            value_format = value_format_raw.strip('><')

            array_format = f"{value_endian}{self.LENGTH}{value_format}"
            return struct.pack(array_format, *self._val)
        else:
            return b"".join([item.serialize() for item in self._val])

    def deserialize(self, data, offset):
        """Deserialize the members of the array"""
        if issubclass(self.MEMBER_TYPE, NumericalType) and self.LENGTH > 0:
            try:
                value_format_raw = self.MEMBER_TYPE().get_serialize_format()
                value_endian = ''
                if self.MEMBER_TYPE.getSize() > 1:
                    assert value_format_raw[0] in ('>', '<'), \
                           f'Expected explicit endian numerical type format but found {value_format_raw}'
                    value_endian = value_format_raw[0]
                value_format = value_format_raw.strip('><')

                array_format = f"{value_endian}{self.LENGTH}{value_format}"
                values = list(struct.unpack_from(array_format, data, offset))
            except Exception as exc:
                raise DeserializeException(
                    f"Array NumericalType optimization failed to deserialize: {exc}"
                )
        else:
            values = []
            for field_index in range(self.LENGTH):
                try:
                    item = self.MEMBER_TYPE()
                    item.deserialize(data, offset)
                    offset += item.getSize()
                    values.append(item)
                except Exception as exc:
                    raise DeserializeException(
                        f"Array index {field_index} failed to deserialize: {exc}"
                    )
        self._val = values

    def getSize(self):
        """Return the size in bytes of the array"""
        if self._is_numerical_array():
            return self.MEMBER_TYPE.getMaxSize() * len(self._val)
        else:
            return sum(item.getSize() for item in self._val)

    @classmethod
    def getMaxSize(cls):
        """Return the maximum size in bytes of the array"""
        return cls.MEMBER_TYPE.getMaxSize() * cls.LENGTH

    def __iter__(self):
        """Allow the array object to be iterated"""
        return iter(self._val)
