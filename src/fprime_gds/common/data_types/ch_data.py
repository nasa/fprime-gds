"""
@brief Class to store a specific channel telemetry reading

@date Created July 2, 2018
@author R. Joseph Paetz

@bug No known bugs
"""

from fprime_gds.common.models.serialize import time_type
from fprime_gds.common.models.serialize.array_type import ArrayType
from fprime_gds.common.models.serialize.serializable_type import SerializableType

from fprime_gds.common.data_types import sys_data
from fprime_gds.common.utils.string_util import format_string_template


class ChData(sys_data.SysData):
    """
    The ChData class stores a specific channel telemetry reading.
    """

    def __init__(self, ch_val_obj, ch_time, ch_temp):
        """
        Constructor.

        Args:
            ch_val_obj: The channel's value at the given time. Should be an
                        instance of a class derived from the BaseType class
                        (with a deserialized data value) or None
            ch_temp: Channel template instance for this channel
            ch_time: Time the reading was made

        Returns:
            An initialized ChData object
        """
        super().__init__()
        self.id = ch_temp.get_id()
        self.val_obj = ch_val_obj
        self.time = ch_time
        self.template = ch_temp
        self.pkt = None
        self.display_text = self._compute_display_text(ch_val_obj, ch_temp)

    @staticmethod
    def get_empty_obj(ch_temp):
        """
        Obtains a channel object that is empty (has a value of None)

        Args:
            ch_temp: (ChTemplate object) Template describing the channel

        Returns:
            A ChData Object with ch value of None
        """
        return ChData(None, time_type.TimeType(), ch_temp)

    def _compute_display_text(self, val_obj, template):
        """
        Returns the display_text for the channel by computing it. This function is defined so as not to clutter __init__()
        but should not be called elsewhere. Use get_display_text() instead.
        Does not depend on self state so as not to be dependent on the order of initialization.
        """
        # This can happen when constructing empty objects (e.g. when listing channels)
        # in which case we just display the description
        if val_obj is None:
            return template.ch_desc
        temp_val = (
            val_obj.val
            if not isinstance(val_obj, (SerializableType, ArrayType))
            else val_obj.formatted_val
        )
        fmt_str = template.get_format_str()
        if temp_val is None:
            return ""
        if fmt_str:
            return format_string_template(fmt_str, (temp_val,))
        return temp_val

    def set_pkt(self, pkt):
        """
        Set the packet object to which this channel belongs (can be None)

        Args:
            pkt: The packet object to which these channels were transmitted in
        """
        self.pkt = pkt

    def get_pkt(self):
        """
        Return the packet object to which this channel belongs (could be None)

        Returns:
            The channel's packet
        """
        return self.pkt

    def get_val(self):
        """
        Return the channel value

        Returns:
            The channel reading
        """
        return None if self.val_obj is None else self.val_obj.val

    def get_val_obj(self):
        """
        Return the channel's value object

        Returns:
            The channel's value object containing the value (obj of a type
            inherited from TypeBase
        """
        return self.val_obj

    def get_display_text(self):
        """
        Convert the channel value to a string, using the format specifier if provided
        """
        return self.display_text

    @staticmethod
    def get_csv_header(verbose=False):
        """
        Get the header for a csv file containing channel data

        Args:
            verbose: (boolean, default=False) Indicates if header should be for
                                              regular or verbose output

        Returns:
            Header for a csv file containing channel data
        """
        return "Time,Raw Time,Name,ID,Value\n" if verbose else "Time,Name,Value\n"

    def get_dict(self, time_zone=None):
        """
        Convert the channel data to a dictionary

        Args:
            time_zone: (tzinfo, default=None) Timezone to print time in. If
                      time_zone=None, use local time.

        Returns:
            Dictionary version of the channel data
        """
        return {
            "time": self.time.to_readable(time_zone),
            "raw_time": str(self.time),
            "name": self.template.get_full_name(),
            "id": self.id,
            "display_text": self.get_display_text(),
        }

    def get_str(self, time_zone=None, verbose=False, csv=False):
        """
        Convert the channel data to a string

        Args:
            time_zone: (tzinfo, default=None) Timezone to print time in. If
                      time_zone=None, use local time.
            verbose: (boolean, default=False) Prints extra fields if True
            csv: (boolean, default=False) Prints each field with commas between
                                          if true

        Returns:
            String version of the channel data
        """
        time_str_nice = self.time.to_readable(time_zone)
        raw_time_str = str(self.time)
        ch_name = self.template.get_full_name()
        display_text = self.get_display_text()

        if verbose and csv:
            return f"{time_str_nice},{raw_time_str},{ch_name},{self.id},{display_text}"
        if verbose and not csv:
            return (
                f"{time_str_nice}: {ch_name} ({self.id}) {raw_time_str} {display_text}"
            )
        if not verbose and csv:
            return f"{time_str_nice},{ch_name},{display_text}"
        return f"{time_str_nice}: {ch_name} = {display_text}"

    def __str__(self):
        """
        Convert the ch data to a string

        Returns:
            String version of the channel data
        """
        return self.get_str()
