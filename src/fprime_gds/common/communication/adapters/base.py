"""
base.py:

This file specifies the base-adapter for the F prime comm-layer. This class defines the basic methods needed to interact
with various wire formats as they are supported by the F prime comm-layer. This file defines a single abstract base
class representing the core features of the adapter class that must be implemented by every implementation of the
adapter for use with the comm-layer.

@author lestarch
"""
import abc
from typing import Type
from fprime_gds.plugin.definitions import gds_plugin_implementation, gds_plugin_specification


class BaseAdapter(abc.ABC):
    """
    Base adapter for adapting the communications layer. This essentially breaks down to providing the ability to read
    data from, and write to the necessary wire-format. The children of this class must at least implement the 'read' and
    'write' functions to ensure that data can be read and written. 'open' and 'close' are also provided as a helper to
    the subclass implementer to place resource initialization and release code, however; these implementations are
    defaulted not overridden.
    """

    def open(self):
        """Null default implementation"""

    def close(self):
        """Null default implementation"""

    @abc.abstractmethod
    def read(self, timeout=0.500):
        """
        Read from the interface. Must be overridden by the child adapter. Throw no fatal errors, reconnect instead. This
        call is expected to block waiting on incoming data.

        :param size: maximum size of data to read before breaking
        :param timeout: timeout for the block, default: 0.500 (500ms) as blocking w/o timeout may be uninterruptible
        :return: byte array of data, or b'' if no data was read
        """

    @abc.abstractmethod
    def write(self, frame):
        """
        Write to the interface. Must be overridden by the child adapter. Throw no fatal errors, reconnect instead.

        :param frame: framed data to uplink
        :return: True if data sent through adapter, False otherwise
        """

    @classmethod
    @gds_plugin_specification
    def register_communication_plugin(cls) -> Type["BaseAdapter"]:
        """Register a communications adapter

        Plugin hook for registering a plugin that supplies an adapter to the communications interface (radio, uart, i2c,
        etc). This interface is expected to read and write bytes from a wire and will be provided to the framing system.

        Note: users should return the class, not an instance of the class. Needed arguments for instantiation are
        determined from class methods, solicited via the command line, and provided at construction time to the chosen
        instantiation.

        Returns:
            BaseAdapter subclass
        """
        raise NotImplementedError()


class NoneAdapter(BaseAdapter):
    """ None adapter used to turn off the comm script """

    @classmethod
    def get_name(cls):
        """ Get name of the non-adapter """
        return "none"

    def read(self, timeout=0.500):
        """ Raise exception if this is called"""
        raise NotImplementedError()

    def write(self, frame):
        """ Raise exception if this is called"""
        raise NotImplementedError()

    @classmethod
    @gds_plugin_implementation
    def register_communication_plugin(cls):
        """ Register this as a plugin """
        return cls