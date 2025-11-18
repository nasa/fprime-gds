"""
Created on Jan 5, 2015

@author: tcanham
"""

import copy
from enum import Enum

from fprime_gds.common.models.serialize.type_base import BaseType

# Import the types this way so they do not need prefixing for execution.
from fprime_gds.common.models.serialize.type_exceptions import (
    ArgLengthMismatchException,
    ArgNotFoundException,
    TypeMismatchException,
)
from fprime_gds.common.utils.config_manager import ConfigManager

Descriptor = Enum(value="Descriptor", names="ABSOLUTE RELATIVE")


class Command:
    """
    classdocs
    """

    def __init__(
        self,
        component,
        mnemonic,
        opcode,
        description,
        arguments,
        seconds=0,
        useconds=0,
        descriptor=Descriptor.RELATIVE,
    ):
        """
        Constructor
        """

        # Make sure correct types are passed

        if not isinstance(component, str):
            raise TypeMismatchException(str, type(component))

        if not isinstance(mnemonic, str):
            raise TypeMismatchException(str, type(mnemonic))

        if not isinstance(opcode, int):
            raise TypeMismatchException(int, type(opcode))

        if not isinstance(description, str):
            raise TypeMismatchException(str, type(description))

        if not isinstance(arguments, list):
            raise TypeMismatchException(list, type(arguments))

        for argname, argdesc, argtype in arguments:
            #
            if not isinstance(argname, str):
                raise TypeMismatchException(str, type(argname))
            #
            if not isinstance(argdesc, str):
                raise TypeMismatchException(str, type(argdesc))
            #
            if not isinstance(argtype, BaseType):
                raise TypeMismatchException(BaseType, type(argtype))

        # Initialize command internal variables
        self.__component = component
        self.__mnemonic = mnemonic
        self.__opcode = opcode
        self.__description = description
        self.__arguments = arguments

        # If part of a sequence we need to set these as well
        self.setSeconds(seconds)
        self.setUseconds(useconds)
        self.setDescriptor(descriptor)

    def serialize(self):
        """
        Serializes command arguments
        """
        # first, serialize opcode
        opcode = ConfigManager().get_type("FwOpcodeType")(self.__opcode)
        ser_data = opcode.serialize()

        # then, serialize arguments
        for arg_name, arg_desc, arg_type in self.__arguments:
            ser_data += arg_type.serialize()
        return ser_data

    def getComponent(self):
        return self.__component

    def getMnemonic(self):
        return self.__mnemonic

    def getOpCode(self):
        return self.__opcode

    def getDescription(self):
        return self.__description

    def getSeconds(self):
        return self.__secs

    def getUseconds(self):
        return self.__usecs

    def getDescriptor(self):
        return self.__desc

    def getArgs(self):
        return self.__arguments

    def setSeconds(self, seconds):
        if not isinstance(seconds, int):
            raise TypeMismatchException(int, type(seconds))
        self.__secs = seconds

    def setUseconds(self, useconds):
        if not isinstance(useconds, int):
            raise TypeMismatchException(int, type(useconds))
        self.__usecs = useconds

    def setDescriptor(self, descriptor):
        if not isinstance(descriptor, type(Descriptor.ABSOLUTE)):
            raise TypeMismatchException(type(Descriptor.ABSOLUTE), type(descriptor))
        self.__desc = descriptor

    # value needs to be the Python class, not the raw value
    def setArg(self, arg_name, arg_type):
        """
        Method to set up an argument value of any
        of the types specified in serialize package.
        @param arg_name: string name of the argument.
        @param arg_type: object type to store argument value in.
        """
        # double check argument types
        if not isinstance(arg_name, str):
            raise TypeMismatchException(str, type(arg_name))

        if not isinstance(arg_type, BaseType):
            raise TypeMismatchException(BaseType, type(arg_type))

        new_arg_list = []
        found = False
        # search for argument
        for arg, arg_desc, arg_value in self.__arguments:
            if arg_name == arg:
                arg_value = arg_type
                found = True
            new_arg_list.append((arg, arg_desc, arg_value))

        if not found:
            raise ArgNotFoundException(arg_name)
        self.__arguments = new_arg_list

    def setArgs(self, values):
        """
        Given a list of values for the arguments, set the command arguments in order.
        @param values: raw python values (floats, ints, and strings) that will be converted
        into arg_types and stored as the command arg
        """

        # Make sure that the correct number of arguments is given
        if len(values) != len(self.__arguments):
            raise ArgLengthMismatchException(len(self.__arguments), len(values))

        # Set the new arguments by converting each value to an type:
        new_arg_list = []
        for value, (arg_name, arg_desc, arg_value) in zip(values, self.__arguments):
            new_value = copy.deepcopy(arg_value)
            new_value.val = value
            new_arg_list.append((arg_name, arg_desc, new_value))
        self.__arguments = new_arg_list
