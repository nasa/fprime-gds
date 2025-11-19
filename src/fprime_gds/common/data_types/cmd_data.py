"""
@brief Command Data class

Instances of this class define a specific instance of a command with specific
argument values.

@data Created July 3, 2018
@author Josef Biberstein

@bug No known bugs
"""

import json

from fprime_gds.common.models.serialize.array_type import ArrayType
from fprime_gds.common.models.serialize.bool_type import BoolType
from fprime_gds.common.models.serialize.enum_type import EnumType
from fprime_gds.common.models.serialize.numerical_types import (
    F32Type,
    F64Type,
    I8Type,
    I16Type,
    I32Type,
    I64Type,
    U8Type,
    U16Type,
    U32Type,
    U64Type,
)
from fprime_gds.common.models.serialize.serializable_type import SerializableType
from fprime_gds.common.models.serialize.string_type import StringType
from fprime_gds.common.models.serialize.time_type import TimeType

from fprime_gds.common.data_types import sys_data


class CmdData(sys_data.SysData):
    """The CmdData class stores a specific command"""

    def __init__(self, cmd_args, cmd_temp, cmd_desc=None, cmd_time=None):
        """
        Constructor.

        Args:
            cmd_args: The arguments for the command. Should match the types of the
                      arguments in the cmd_temp object. Should be a tuple.
            cmd_temp: Command Template instance for this command (this provides
                      the opcode and argument types are stored)
            cmd_desc: command descriptor: Absolute/Relative. For sequences
            cmd_time: The time the command should occur. This is for sequences.
                      Should be a TimeType object with time base=TB_DONT_CARE

        Returns:
            An initialized CmdData object
        """
        super().__init__()
        self.id = cmd_temp.get_id()
        self.template = cmd_temp

        self.args, errors = self.process_args(cmd_args)
        self.time = cmd_time or TimeType(
            TimeType.TimeBase("TB_DONT_CARE")
        )
        self.descriptor = cmd_desc

        # If any errors occur, then raise a aggregated error
        if [error for error in errors if error != ""]:
            raise CommandArgumentsException(errors)

    def get_template(self):
        """Get the template class associate with this specific data object

        Returns:
            Template -- The template class for this data object
        """

        return self.template

    def get_time(self):
        """ Return time """
        return self.time

    def get_descriptor(self):
        """ Return the descriptor """
        return self.descriptor

    def get_id(self):
        """Get the ID associate with the template of this data object

        Returns:
            An ID number
        """

        return self.id

    def get_arg_vals(self):
        """Get the values for each argument in a command.

        Returns:
            list -- a list of value objects that were used in this data object.
        """

        return [arg.val for arg in self.args]

    def get_args(self):
        """Get the arguments associate with the template of this data object

        Returns:
            list -- A list of type objects representing the arguments of the template of this data object (in order)
        """

        return self.args

    def get_str(self, time_zone=None, verbose=False, csv=False):
        """
        Convert the command data to a string

        Args:
            time_zone: (tzinfo, default=None) Timezone to print time in. If
                      time_zone=None, use local time.
            verbose: (boolean, default=False) Prints extra fields if True
            csv: (boolean, default=False) Prints each field with commas between
                                          if true

        Returns:
            String version of the command data
        """
        time_str = self.time.to_readable(time_zone)
        raw_time_str = str(self.time)
        name = self.template.get_full_name()

        if self.args is None:
            arg_str = "EMPTY COMMAND OBJ"
        else:
            # The arguments are currently serializable objects which cannot be
            # used to fill in a format string. Convert them to values that can be
            arg_val_list = self.get_arg_vals()
            arg_str = str(arg_val_list)

        if verbose and csv:
            return f"{time_str},{raw_time_str},{name},{self.id},{arg_str}"
        if verbose and not csv:
            return f"{time_str}: {name} ({self.id}) {raw_time_str} : {arg_str}"
        if not verbose and csv:
            return f"{time_str},{name},{arg_str}"
        return f"{time_str}: {name} : {arg_str}"

    def process_args(self, input_values):
        """ Process input arguments """
        errors = []
        args = []
        for val, arg_tuple in zip(input_values, self.template.arguments):
            try:
                arg_name, _, arg_type = arg_tuple
                arg_value = arg_type()
                self.convert_arg_value(val, arg_value)
                args.append(arg_value)
                errors.append("")
            except Exception as exc:
                errors.append(f"{arg_name}[{arg_type.__name__}]: {exc}")
        return args, errors

    @staticmethod
    def convert_arg_value(arg_val, arg_instance):
        if arg_val is None:
            raise CommandArgumentException(
                "Argument was not set"
            )
        if isinstance(arg_instance, BoolType):
            value = str(arg_val).lower().strip()
            if value in {"true", "yes"}:
                av = True
            elif value in {"false", "no"}:
                av = False
            else:
                raise CommandArgumentException("Argument value is not a valid boolean")
            arg_instance.val = av
        elif isinstance(arg_instance, EnumType):
            arg_instance.val = arg_val
        elif isinstance(arg_instance, (F64Type, F32Type)):
            arg_instance.val = float(arg_val)
        elif isinstance(
            arg_instance,
            (I64Type, U64Type, I32Type, U32Type, I16Type, U16Type, I8Type, U8Type),
        ):
            arg_instance.val = int(arg_val, 0) if isinstance(arg_val, str) else int(arg_val)
        elif isinstance(arg_instance, StringType):
            arg_instance.val = arg_val
        elif isinstance(arg_instance, (ArrayType, SerializableType)):
            arg_instance.val = json.loads(arg_val)
        else:
            raise CommandArgumentException(
                "Argument value could not be converted to type object"
            )

    def __str__(self):
        arg_str = "".join(f"{name} : {str(typ.val)} |" for name, typ in zip([arg[0] for arg in self.template.get_args()], self.args))
        arg_str = f"w/ args | {arg_str}"

        arg_info = f"{self.template.mnemonic} "

        return arg_info + arg_str if len(self.args) > 0 else arg_info


class CommandArgumentException(Exception):
    pass


class CommandArgumentsException(Exception):
    def __init__(self, errors):
        """
        Handle a list of errors as an exception.
        """
        super().__init__(" ".join(errors))
        self.errors = errors