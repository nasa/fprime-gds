""" fprime_gds.plugin.system: implementation of plugins

This file contains the implementation and registration of plugins for fprime_gds. Primarily, it defines the Plugins
class that handles plugins. Users can acquire the Plugin singleton with `Plugin.system()`.

This file also imports and registers plugin implementations built-into fprime-gds. These plugins are not registered
using entrypoints.

@author lestarch
"""
import inspect
import logging
import re
from typing import Iterable

import pluggy

import fprime_gds.executables.apps
import fprime_gds.plugin.definitions as definitions

# For automatic validation of plugins, each plugin class type must be imported here
import fprime_gds.common.communication.framing as framing

import fprime_gds.common.communication.adapters.base as base
import fprime_gds.common.communication.adapters.ip as ip

from fprime_gds.plugin.definitions import *

try:
    import fprime_gds.common.communication.adapters.uart as uart
except ImportError:
    uart = None

# Handy constants
LOGGER = logging.getLogger(__name__)
_NAME_REGEX = re.compile(r"^register_(\w+)_plugin")

# Metadata regarding each plugin:
_PLUGIN_METADATA = {
    register_framing_plugin: {"class": framing.FramerDeframer, "type": PluginType.SELECTION},
    register_communication_plugin: {"class": base.BaseAdapter, "type": PluginType.SELECTION},
    register_gds_function_plugin: {"class": fprime_gds.executables.apps.GdsFunction, "type": PluginType.FEATURE},
    register_gds_app_plugin: {"class": fprime_gds.executables.apps.GdsApp, "type": PluginType.FEATURE}
}

# F´ supplied plugin classes to be registered directly and not via entrypoints
_SUPPLIED_PLUGIN_MODULES_OR_CLASSES = [
    framing.FpFramerDeframer,
    base.NoneAdapter,
    ip.IpAdapter,
]
if uart is not None:
    _SUPPLIED_PLUGIN_MODULES_OR_CLASSES.append(uart.SerialAdapter)


class PluginException(Exception):
    pass


class InvalidCategoryException(PluginException):
    pass




class Plugins(object):
    """GDS plugin system providing a plugin Singleton for use across the GDS"""

    _singleton = None

    def __init__(self):
        """Initialize the plugin system"""
        self.manager = pluggy.PluginManager(PROJECT_NAME)
        self.manager.add_hookspecs(definitions)
        self.manager.load_setuptools_entrypoints(PROJECT_NAME)
        for module in _SUPPLIED_PLUGIN_MODULES_OR_CLASSES:
            self.manager.register(module)

    def get_plugins(self, category) -> Iterable:
        """Get available plugins for the given category

        Gets all plugin implementors of "category" by looking for register_<category>_plugin implementors. If such a
        function does not exist then this results in an exception.

        Args:
            category: category of the plugin requested

        Return:
            validated list of plugin implementor classes
        """
        plugin_function_name = f"register_{category}_plugin"
        if not hasattr(definitions, plugin_function_name) or not hasattr(
            self.manager.hook, plugin_function_name
        ):
            raise InvalidCategoryException(f"Invalid plugin category: {category}")
        plugin_classes = getattr(self.manager.hook, plugin_function_name)()
        return [
            Plugin(category, self.get_category_plugin_type(category), plugin_class)
            for plugin_class in plugin_classes
            if self.validate_selection(category, plugin_class)
        ]

    def register_plugin(self, module_or_class):
        """Register a plugin directly

        Allows local registration of plugin implementations that are shipped as part of the GDS package.

        Args:
            module_or_class: module or class that has plugin implementations
        """
        self.manager.register(module_or_class)

    @staticmethod
    def get_categories():
        """Get all plugin categories"""
        specifications = _PLUGIN_METADATA.keys()
        matches = [
            _NAME_REGEX.match(specification.__name__)
            for specification in specifications
        ]
        return [match.group(1) for match in matches if match]

    @staticmethod
    def get_plugin_metadata(category):
        """ Get the plugin metadata for a given plugin category """
        plugin_function_name = f"register_{category}_plugin"
        plugin_specification_function = getattr(definitions, plugin_function_name)
        assert hasattr(
            definitions, plugin_function_name
        ), "Plugin category failed pre-validation"
        return _PLUGIN_METADATA[plugin_specification_function]

    @classmethod
    def get_category_plugin_type(cls, category):
        """ Get the plugin type given the category """
        return cls.get_plugin_metadata(category)["type"]

    @classmethod
    def get_category_specification_class(cls, category):
        """ Get the plugin class given the category """
        return cls.get_plugin_metadata(category)["class"]

    @classmethod
    def validate_selection(cls, category, result):
        """Validate the result of plugin hook

        Validates the result of a plugin hook call to ensure the result meets the expected properties for plugins of the
        given category. Primarily this ensures that this plugin returns a concrete subclass of the expected type.

        Args:
            category: category of plugin used
            result: result from the plugin hook call
        Return:
            True when the plugin passes validation, False otherwise
        """
        # Typing library not intended for introspection at runtime, thus we maintain a map of plugin specification
        # functions to the types expected as a return value. When this is not found, plugins may continue without
        # automatic validation.
        try:
            expected_class = cls.get_category_specification_class(category)
            # Validate the result
            if not issubclass(result, expected_class):
                LOGGER.warning(
                    f"{result.__name__} is not a subclass of {expected_class.__name__}. Not registering."
                )
                return False
            elif inspect.isabstract(result):
                LOGGER.warning(
                    f"{result.__name__} is an abstract class. Not registering."
                )
                return False
        except KeyError:
            LOGGER.warning(
                f"Plugin not registered for validation. Continuing without validation."
            )
        return True

    @classmethod
    def system(cls) -> "PluginSystem":
        """Construct singleton if needed then return it"""
        return cls._build_singleton()

    @classmethod
    def _build_singleton(cls) -> "PluginSystem":
        """Build a singleton for this class"""
        cls._singleton = cls._singleton if cls._singleton is not None else cls()
        return cls._singleton
