"""
@brief Class to store data from a specific event

@date Created July 2, 2018
@author R. Joseph Paetz

@bug No known bugs
"""

from fprime_gds.common.models.serialize import time_type

from fprime_gds.common.data_types import sys_data
from fprime_gds.common.utils.string_util import format_string_template

import os

class EventData(sys_data.SysData):
    """
    The EventData class stores a specific event message.
    """

    def __init__(self, event_args, event_time, event_temp):
        """
        Constructor.

        Args:
            event_args: The arguments of the event being stored. This should
                        be a tuple where each element is an object of a class
                        derived from the BaseType class with a filled in value.
                        Each element's class should match the class of the
                        corresponding argument type object in the event_temp
                        object. This can be None.
            event_time: The time the event occurred (TimeType)
            event_temp: Event template instance for this event

        Returns:
            An initialized EventData object
        """
        super().__init__()
        self.id = event_temp.get_id()
        self.args = event_args
        self.time = event_time
        self.template = event_temp

        if event_args is None:
            self.display_text = event_temp.description
            return

        if (
            (event_temp.name.startswith('AF_ASSERT') or event_temp.name == "AF_UNEXPECTED_ASSERT") and
            'FPRIME_HASHES_TXT_FILE' in os.environ
        ):
            self._decode_hashed_files()
                
        if event_temp.format_str == "":
            args_template = self.template.get_args()

            self.display_text = str(
                [
                    {args_template[index][0]: arg.val}
                    for index, arg in enumerate(event_args)
                ]
            )
        else:
            self.display_text = format_string_template(
                event_temp.format_str, tuple([arg.val for arg in event_args])
            )

    def _decode_hashed_files(self):
        "Searches event args for hashed files and replaces each with its corresponding file name"

        args_template = self.template.get_args()
        for index, arg in enumerate(self.args):

            if not args_template[index]:
                continue
            if args_template[index][0] != 'file':
                continue
            try:
                hash_value = int(arg.val, 16)
            except ValueError:
                continue

            hash_file = os.environ['FPRIME_HASHES_TXT_FILE']
            with open(hash_file) as file_handle:
                for line in file_handle:
                    if hash_value == int(line.split(" ")[-1], 0):
                        arg.val = line.split(':')[0].strip()
                        break

    def get_args(self):
        return self.args

    def get_severity(self):
        return self.template.get_severity()

    @staticmethod
    def get_empty_obj(event_temp):
        """
        Obtains an event object that is empty (arguments = None)

        Args:
            event_temp: (EventTemplate obj) Template describing event

        Returns:
            An EventData object with argument value of None
        """
        return EventData(None, time_type.TimeType(), event_temp)

    @staticmethod
    def get_csv_header(verbose=False):
        """
        Get the header for a csv file containing event data

        Args:
            verbose: (boolean, default=False) Indicates if header should be for
                                              regular or verbose output

        Returns:
            String version of the channel data
        """
        if verbose:
            return "Time,Raw Time,Name,ID,Severity,Args\n"
        return "Time,Name,Severity,Args\n"

    def get_display_text(self):
        """
        Get the display text for the event. This is the event's format string
        filled with the event's arguments.
        """
        return self.display_text

    def get_str(self, time_zone=None, verbose=False, csv=False):
        """
        Convert the event data to a string

        Args:
            time_zone: (tzinfo, default=None) Timezone to print time in. If
                      time_zone=None, use local time.
            verbose: (boolean, default=False) Prints extra fields if True
            csv: (boolean, default=False) Prints each field with commas between
                                          if true

        Returns:
            String version of the event data
        """
        time_str = self.time.to_readable(time_zone)
        raw_time_str = str(self.time)
        name = self.template.get_full_name()
        severity = self.template.get_severity()
        display_text = self.display_text

        if verbose and csv:
            return (
                f"{time_str},{raw_time_str},{name},{self.id},{severity},{display_text}"
            )
        if verbose and not csv:
            return f"{time_str}: {name} ({self.id}) {raw_time_str} {severity} : {display_text}"
        if not verbose and csv:
            return f"{time_str},{name},{severity},{display_text}"
        return f"{time_str}: {name} {severity} : {display_text}"

    def get_dict(self, time_zone=None) -> dict:
        """
        Convert the event data to a dictionary

        Returns:
            Dictionary of the event data containing the following fields:
                time: (str) Time the event occurred
                raw_time: (str) Time the event occurred in raw format
                name: (str) Name of the event
                id: (int) ID of the event
                severity: (str) Severity of the event
                args: (list) List of arguments for the event
                display_text: (str) Display text for the event
        """
        return {
            "time": self.time.to_readable(time_zone),
            "raw_time": str(self.time),
            "name": self.template.get_full_name(),
            "id": self.id,
            "severity": str(self.template.get_severity()),
            "args": self.args,
            "display_text": self.display_text,
        }

    def __str__(self):
        """
        Convert the event data to a string

        Returns:
            String version of the channel data
        """
        return self.get_str()
