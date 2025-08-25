"""
handlers.py:

Defines a set of base classes that allow for the system to handle various functions of the system. Primarily this
defines the "DataHandler" base class for handling data.

@author mstarch
"""

import abc
from typing import List, Type
from fprime_gds.plugin.definitions import gds_plugin_specification


class DataHandler(abc.ABC):
    """
    Defines the necessary functions required to handle data as part of the F prime project. This allows any implementer
    to be used to handle data.
    """

    @abc.abstractmethod
    def data_callback(self, data, sender=None):
        """
        Callback function used to handle data being produced elsewhere in the system and processed by the given object.
        Data supplied should be of a known type for the given object, and sender is an id of the sender. If not supplied
        sender will be None.

        :param data: data to be handled by this class
        :param sender: (optional) id of sender, otherwise None
        """


class DataHandlerPlugin(DataHandler, abc.ABC):
    """PLugin class allowing for custom data handlers

    This class acts as a DataHandler class with the addition that it can be used as a plugin and thus self reports the
    data types it handles (whereas DataHandler leaves that up to the registration call). Users shall concretely subclass
    this class with their own data handling functionality.
    """
    def __init__(self, **kwargs):
        """ Initialize """
        self.publisher = None

    def set_publisher(self, publisher):
        """ Set publishing pipeline """
        self.publisher = publisher

    @abc.abstractmethod
    def get_handled_descriptors() -> List[str]:
        """Return a list of data descriptor names this plugin handles"""
        raise NotImplementedError()

    @classmethod
    @gds_plugin_specification
    def register_data_handler_plugin(cls) -> Type["DataHandlerPlugin"]:
        """Register a plugin to provide post-decoding data handling capabilities

        Plugin hook for registering a plugin that supplies a DataHandler implementation. Implementors of this hook must
        return a non-abstract subclass of DataHandlerPlugin. This class will be provided as a data handling
        that is automatically enabled. Users may disable this via the command line. This data handler will be supplied
        all data types returned by the `get_data_types()` method.

        This DataHandler will run within the standard GDS (UI) process. Users wanting a separate process shall use a
        GdsApp plugin instead.

        Note: users should return the class, not an instance of the class. Needed arguments for instantiation are
        determined from class methods, solicited via the command line, and provided at construction time to the chosen
        instantiation.

        Returns:
            DataHandlerPlugin subclass (not instance)
        """
        raise NotImplementedError()


class HandlerRegistrar(abc.ABC):
    """
    Defines a class that will take in registrants and remember them for calling back later. These objects should be of
    the type "DataHandler" as this handler will send data back to these handlers when asked to do so.
    """

    def __init__(self):
        """
        Constructor defining the internal lists needed to store the registrants.
        """
        super().__init__()
        self._registrants = []

    def register(self, registrant):
        """
        Register a registrant with this registrar. Will be stored and called back when asked to send data to all the
        handlers registered.

        :param registrant: handler to register
        """
        if not isinstance(registrant, DataHandler):
            raise ValueError("Cannot register non data handler")
        self._registrants.append(registrant)

    def deregister(self, registrant):
        """
        Remove a registrant from the registrar such that it will not be called back later. Note: ignores invalid
        removals by trapping the error, as the desired effect is already satisfied.

        :param registrant: registrant to remove
        :return: True if found, False if not. May safely be ignored.
        """
        try:
            self._registrants.remove(registrant)
            return True
        except ValueError:
            return False

    def send_to_all(self, data, sender=None):
        """
        Sends the given data to all registrants.

        :param data: data to send back to registrants
        :param sender: (optional) sender to pass to data_callback
        """
        for registrant in self._registrants:
            registrant.data_callback(data, sender)


class MappedRegistrar(abc.ABC):
    """ Class to register a mapping """

    def __init__(self):
        """ Initialize an empty registrant list  """
        super().__init__()
        self._registrants = {}

    def register(self, id, registrant):
        """
        Register a registrant with this registrar associated with the ID. Will be stored and called back when asked to
        send data to all the handlers registered at the id

        :param id: id to register to
        :param registrant: handler to register
        """
        self._registrants[id] = self._registrants.get(id, HandlerRegistrar())
        self._registrants[id].register(registrant)

    def deregister(self, id, registrant):
        """
        Remove a registrant from the registrar such that it will not be called back later. Note: ignores invalid
        removals by trapping the error, as the desired effect is already satisfied.

        :param id: id to register to
        :param registrant: registrant to remove
        :return: True if found, False if not. May safely be ignored.
        """
        try:
            self._registrants[id].deregister(registrant)
            return True
        except (ValueError, KeyError):
            return False

    def send_to_all(self, id, data, sender=None):
        """
        Sends the given data to all registrants at id.

        :param id: id to send to 
        :param data: data to send back to registrants
        :param sender: (optional) sender to pass to data_callback
        """
        try:
            self._registrants[id].send_to_all(data, sender)
        except KeyError:
            print("KeyERROR")
            pass