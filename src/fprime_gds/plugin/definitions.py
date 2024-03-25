""" fprime_gds.plugin.definitions: definitions of plugin specifications and decorators

In order to define a plugin, an implementation decorator is used. Users can import `gds_plugin_implementation` from this
file to decorate functions that implement plugins.

This file also defines helper classes to support the plugin system.

@author lestarch
"""
import pluggy
from enum import Enum, auto
from typing import Any, Dict, Tuple, Type

PROJECT_NAME = "fprime_gds"

gds_plugin_specification = pluggy.HookspecMarker(PROJECT_NAME)
gds_plugin_implementation = pluggy.HookimplMarker(PROJECT_NAME)


class PluginType(Enum):
    """ Enumeration of plugin types"""
    ALL = auto()
    """ Plugin selection including all types of plugins """

    SELECTION = auto()
    """ Plugin that provides a selection between implementations """

    FEATURE = auto()
    """ Plugin that provides a feature """


class Plugin(object):
    """ Plugin wrapper object """

    def __init__(self, category: str, plugin_type: PluginType, plugin_class: Type[Any]):
        """ Initialize the plugin

        Args:
            category: category of the plugin (i.e. register_<category>_function)
            plugin_type: type of plugin
            plugin_class: implementation class of the plugin
        """
        self.category = category
        self.type = plugin_type
        self.plugin_class = plugin_class

    def get_name(self):
        """ Get the name of the plugin

        Plugin names are derived from the `get_name` class method of the plugin's implementation class. When not defined
        that name is derived from the plugin's implementation class __name__ property instead.

        Returns:
            name of plugin
        """
        return (
            self.plugin_class.get_name() if hasattr(self.plugin_class, "get_name")
            else self.plugin_class.__name__
        )

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """ Get arguments needed by plugin

        Plugin argument are derived from the `get_arguments` class method of the plugin's implementation class. When not
        defined an empty dictionary is returned.

        Returns:
            argument specification for plugin
        """
        return self.plugin_class.get_arguments() if hasattr(self.plugin_class, "get_arguments") else {}

