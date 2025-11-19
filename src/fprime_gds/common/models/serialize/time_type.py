"""
@file time_tag.py
@brief Class used to parse and store time tags sent with serialized data

This Class is used to parse, store, and create human readable strings for the
time tags sent with serialized data in the fprime architecture.

@date Created Dec 16, 2015
@author: dinkel

@date Updated June 18, 2018
@author R. Joseph Paetz (rpaetz@jpl.nasa.gov)

@date Updated July 22, 2019
@author Kevin C Oran (kevin.c.oran@jpl.nasa.gov)

@bug No known bugs
"""

import datetime
import math

from fprime_gds.common.utils.config_manager import ConfigManager
from fprime_gds.common.models.serialize import type_base

# Custom Python Modules
from fprime_gds.common.models.serialize.numerical_types import U8Type, U32Type

from fprime_gds.common.models.serialize.enum_type import EnumType
from fprime_gds.common.models.serialize.type_exceptions import TypeRangeException

from typing import Optional, Union

class TimeType(type_base.BaseType):
    """
    Representation of the time type

    Used to parse, store, and create human readable versions of the time tags
    included in serialized output from fprime_gds systems

    Note: comparisons support comparing to numbers or other instances of TimeType. If comparing to
    another TimeType, these comparisons use the provided compare method. See TimeType.compare for
    a description of this behavior.  See comparison functions at the end.
    """

    @staticmethod
    def TimeBase(enum_constant: str) -> EnumType:
        """Constructs a TimeBase instance (EnumType) from a string constant, as defined in the
        ConfigManager.

        Args:
            enum_constant (str): String name of the TimeBase enum constant (e.g., "TB_DONT_CARE")

        Returns:
            An EnumType instance representing the TimeBase type
        """
        return ConfigManager().get_type("TimeBase")(enum_constant)  # type: ignore

    def __init__(self, time_base: Optional[Union[EnumType, int]] = None, time_context: int = 0, seconds: int = 0, useconds: int = 0):
        """
        Constructor

        Note: time_base may be an integer for the time being for backward compatibility, but
        this will be deprecated in the future in favor of only using EnumType instances. Users should
        prefer using TimeType.TimeBase

        Args:
            time_base (Optional[Union[EnumType, int]]): TimeBase object or integer for the time tag. Must be a valid
                             TimeBase Enum value.
            time_context (int): Time context for the time tag
            seconds (int): Seconds elapsed since specified time base
            useconds (int): Microseconds since start of current second. Must
                            be in range [0, 999999] inclusive

        Returns:
            An initialized TimeType object
        """
        # Layout of time tag:
        #
        # START (LSB)
        # |  2 bytes  |    1 byte    | 4 bytes |   4 bytes    |
        # |-----------|--------------|---------|--------------|
        # | Time Base | Time Context | Seconds | Microseconds |
        super().__init__()

        enum_time_base: EnumType  # for type checkers not to be confused by the union type argument
        if time_base is None:
            enum_time_base = TimeType.TimeBase("TB_NONE")
        elif isinstance(time_base, int):
            enum_time_base = ConfigManager().get_type("TimeBase").from_int(time_base)
        else:
            enum_time_base = time_base

        self._check_time_base(enum_time_base)
        self._check_useconds(useconds)

        self.__timeBase = enum_time_base
        self.__timeContext = ConfigManager().get_type("FwTimeContextStoreType")(time_context)
        self.__secs = U32Type(seconds)
        self.__usecs = U32Type(useconds)

    @staticmethod
    def _check_useconds(useconds):
        """
        Checks if a given microsecond value is valid.

        Args:
            usecs (int): The value to check

        Returns:
            None if valid, raises TypeRangeException if not valid.
        """
        if (useconds < 0) or (useconds > 999999):
            raise TypeRangeException(useconds)

    @staticmethod
    def _check_time_base(time_base: EnumType):
        """
        Checks if a given TimeBase value is valid.

        Args:
            time_base (EnumType): The value to check; should be a TimeType.TimeBase enum

        Returns:
            Returns if valid, raises TypeRangeException if not valid.
        """
        if type(time_base) != ConfigManager().get_type("TimeBase"):
            raise TypeRangeException(time_base)
        ConfigManager().get_type("TimeBase").validate(time_base.val)

    def to_jsonable(self):
        """
        JSONable object format
        """
        return {
            "type": self.__repr__(),
            "base": self.__timeBase.numeric_value,
            "context": self.__timeContext,
            "seconds": self.seconds,
            "microseconds": self.useconds,
        }

    @property
    def timeBase(self) -> EnumType:
        return self.__timeBase

    @timeBase.setter
    def timeBase(self, val: EnumType):
        self._check_time_base(val)
        self.__timeBase = val

    @property
    def timeContext(self):
        return self.__timeContext.val

    @timeContext.setter
    def timeContext(self, val):
        self.__timeContext = U8Type(val)

    @property
    def seconds(self):
        return self.__secs.val

    @seconds.setter
    def seconds(self, val):
        self.__secs = U32Type(val)

    @property
    def useconds(self):
        return self.__usecs.val

    @useconds.setter
    def useconds(self, val):
        self._check_useconds(val)
        self.__usecs = U32Type(val)

    def serialize(self):
        """
        Serializes the time type

        Returns:
            Byte array containing serialized time type
        """
        buf = b""
        buf += self.__timeBase.serialize()
        buf += self.__timeContext.serialize()
        buf += self.__secs.serialize()
        buf += self.__usecs.serialize()
        return buf

    def deserialize(self, data, offset):
        """
        Deserializes a serialized time type in data starting at offset.

        Internal values to the object are updated.

        Args:
            data: binary data containing the time tag (type = bytearray)
            offset: Index in data where time tag starts
        """

        # Decode Time Base
        self.__timeBase.deserialize(data, offset)
        offset += self.__timeBase.getSize()

        # Decode Time Context
        self.__timeContext.deserialize(data, offset)
        offset += self.__timeContext.getSize()

        # Decode Seconds
        self.__secs.deserialize(data, offset)
        offset += self.__secs.getSize()

        # Decode Microseconds
        self.__usecs.deserialize(data, offset)
        offset += self.__usecs.getSize()

    @classmethod
    def getSize(cls):
        """
        Return the size of the time type object when serialized

        Returns:
            The size of the time type object when serialized
        """
        return (
            ConfigManager().get_type("TimeBase").getMaxSize()
            + ConfigManager().get_type("FwTimeContextStoreType")().getSize()   # time context
            + U32Type.getSize()  # seconds
            + U32Type.getSize()  # microseconds
        )

    @classmethod
    def getMaxSize(cls):
        """
        Return the size of the time type object when serialized

        Returns:
            The size of the time type object when serialized
        """
        # Always the same as getSize. Must be updated when time types are configurable.
        return cls.getSize()

    @staticmethod
    def compare(t1, t2):
        """
        Compares two TimeType objects

        This function sorts times in the order of: timeBase, secs, usecs, and
        then timeContext.

        Returns:
            Negative, 0, or positive for t1<t2, t1==t2, t1>t2 respectively
        """

        def cmp(x, y):
            return (x > y) - (x < y)  # added to support Python 2/3

        # Compare Base
        base_cmp = cmp(t1.timeBase.numeric_value, t2.timeBase.numeric_value)
        if base_cmp != 0:
            return base_cmp

        # Compare seconds
        sec_cmp = cmp(t1.seconds, t2.seconds)
        if sec_cmp != 0:
            return sec_cmp

        # Compare usecs
        usec_cmp = cmp(t1.useconds, t2.useconds)
        return usec_cmp if usec_cmp != 0 else cmp(t1.timeContext, t2.timeContext)

    def __str__(self):
        """
        Formats the time type object for printing

        Returns:
            A string representing the time type object
        """
        return "(%d(%d)-%d:%d)" % (
            self.__timeBase.numeric_value,
            self.__timeContext.val,
            self.__secs.val,
            self.__usecs.val,
        )

    def to_readable(self, time_zone=None):
        """
        Returns a string of the time object in a human readable format

        Args:
            time_zone (tzinfo): Time zone to convert the TimeType
                      object to before printing. Timezone also displayed.
                      If time_zone=None, local timezone is used.
                      Defaults to None.

        Returns:
            A human readable string representing the time type object
        """
        dt = self.get_datetime(time_zone)

        # If we could convert to a valid datetime, use that, otherwise, format
        if dt:
            # datetime.isoformat() returns time string with microsecond
            # precision.
            # This line can be changed for other precisions or needs.
            return dt.isoformat(timespec="microseconds")
        return "%s: %d.%06ds, context=%d" % (
            self.__timeBase.val,
            self.__secs.val,
            self.__usecs.val,
            self.__timeContext.val,
        )

    def get_datetime(self, tz=None):
        """
        Returns the python datetime object for UTC time

        Args:
            tz (tzinfo): timezone to create the datetime object
               in. If tz=None, local time zone used. Defaults to None.
        Returns:
            datetime object for the time type or None if the time couldn't
            be determined.
        """
        dt = None

        if self.__timeBase.val in ["TB_WORKSTATION_TIME", "TB_SC_TIME"]:
            # This finds the local time corresponding to the timestamp and
            # timezone object, or local time zone if tz=None
            dt = datetime.datetime.fromtimestamp(self.__secs.val, tz)

            dt = dt.replace(microsecond=self.__usecs.val)

        return dt

    def set_datetime(self, dt, time_base: EnumType):
        """
        Sets the timebase from a datetime object.

        Args:
            dt (datetime): datetime object to read from time.
        """
        total_seconds = (dt - datetime.datetime.fromtimestamp(0)).total_seconds()
        seconds = int(total_seconds)
        useconds = int((total_seconds - seconds) * 1000000)

        self.timeBase = time_base
        self.seconds = seconds
        self.useconds = useconds

    # The following Python special methods add support for rich comparison of TimeTypes to other
    # TimeTypes and numbers.

    def get_float(self):
        """
        a helper method that gets the current TimeType as a float where the non-fraction is seconds
        and the fraction is microseconds. This enables comparisons with numbers.
        """
        return self.seconds + (self.useconds / 1000000)

    def __lt__(self, other):
        """Less than"""
        if isinstance(other, TimeType):
            return self.compare(self, other) < 0
        return self.get_float() < other

    def __le__(self, other):
        """Less than or equal"""
        if isinstance(other, TimeType):
            return self.compare(self, other) <= 0
        return self.get_float() <= other

    def __eq__(self, other):
        """Equal"""
        if isinstance(other, TimeType):
            return self.compare(self, other) == 0
        return self.get_float() == other

    def __ne__(self, other):
        """Not equal"""
        if isinstance(other, TimeType):
            return self.compare(self, other) != 0
        return self.get_float() != other

    def __gt__(self, other):
        """Greater than"""
        if isinstance(other, TimeType):
            return self.compare(self, other) > 0
        return self.get_float() > other

    def __ge__(self, other):
        """Greater than or equal"""
        if isinstance(other, TimeType):
            return self.compare(self, other) >= 0
        return self.get_float() >= other

    # The following helper methods enable support for arithmetic operations on TimeTypes.

    def set_float(self, num):
        """
        a helper method that takes a float and sets a TimeType's seconds and useconds fields.
        Note: This method is private because it is only used by the _get_type_from_float helper to
        generate new TimeType instances. It is not meant to be used to modify an existing timestamp.
        Note: Present implementation will set any negative result to 0
        """
        num = max(num, 0)
        self.seconds = int(math.floor(num))
        self.useconds = int(math.floor((num - self.seconds) * 1000000))

    def get_type_from_float(self, num):
        """
        a helper method that returns a new instance of TimeType and sets the seconds and useconds
        fields using the given number. The new TimeType's time_base and time_context will be
        preserved from the calling object.
        """
        tType = TimeType(self.__timeBase, self.__timeContext.val)
        tType.set_float(num)
        return tType

    # The following Python special methods add support for arithmetic operations on TimeTypes.

    def __add__(self, other):
        """Addition"""
        if isinstance(other, TimeType):
            other = other.get_float()
        num = self.get_float() + other
        return self.get_type_from_float(num)

    def __sub__(self, other):
        """Subtraction"""
        if isinstance(other, TimeType):
            other = other.get_float()
        num = self.get_float() - other
        return self.get_type_from_float(num)

    def __mul__(self, other):
        """Multiplication"""
        if isinstance(other, TimeType):
            other = other.get_float()
        num = self.get_float() * other
        return self.get_type_from_float(num)

    def __truediv__(self, other):
        """True division"""
        if isinstance(other, TimeType):
            other = other.get_float()
        num = self.get_float() / other
        return self.get_type_from_float(num)

    def __floordiv__(self, other):
        """Floored division"""
        if isinstance(other, TimeType):
            other = other.get_float()
        num = self.get_float() // other
        return self.get_type_from_float(num)

    # The following Python special methods add support for reflected arithmetic operations on TimeTypes.

    def __radd__(self, other):
        """Reflected addition"""
        if isinstance(other, TimeType):
            other = other.get_float()
        num = other + self.get_float()
        return self.get_type_from_float(num)

    def __rsub__(self, other):
        """Reflected subtraction"""
        if isinstance(other, TimeType):
            other = other.get_float()
        num = other - self.get_float()
        return self.get_type_from_float(num)

    def __rmul__(self, other):
        """Reflected multiplication"""
        if isinstance(other, TimeType):
            other = other.get_float()
        num = other * self.get_float()
        return self.get_type_from_float(num)

    def __rtruediv__(self, other):
        """Reflected division"""
        if isinstance(other, TimeType):
            other = other.get_float()
        num = other / self.get_float()
        return self.get_type_from_float(num)

    def __rfloordiv__(self, other):
        """Reflected floored division"""
        if isinstance(other, TimeType):
            other = other.get_float()
        num = other // self.get_float()
        return self.get_type_from_float(num)
