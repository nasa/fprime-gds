""" fprime_gds.plugin.system: implementation of plugins

This file contains the implementation and registration of plugins for fprime_gds. Primarily, it defines the Plugins
class that handles plugins. Users can acquire the Plugin singleton with `Plugin.system()`.

This file also imports and registers plugin implementations built-into fprime-gds. These plugins are not registered
using entrypoints.

@author lestarch
"""
import os
import importlib
import inspect
import logging
from typing import Iterable, List, Union

import pluggy

from fprime_gds.plugin.definitions import Plugin, PluginType, PROJECT_NAME

# For automatic validation of plugins, each plugin class type must be imported here
from fprime_gds.executables.apps import GdsFunction, GdsApp
from fprime_gds.common.communication.framing import FramerDeframer, FpFramerDeframer
from fprime_gds.common.communication.adapters.base import BaseAdapter, NoneAdapter
from fprime_gds.common.communication.adapters.ip import IpAdapter

try:
    from fprime_gds.common.communication.adapters.uart import SerialAdapter
except ImportError:
    SerialAdapter = None

# Handy constants
LOGGER = logging.getLogger(__name__)


# Metadata regarding each plugin:
_PLUGIN_METADATA = {
    "framing": {
        "class": FramerDeframer,
        "type": PluginType.SELECTION,
        "built-in": [FpFramerDeframer]
    },
    "communication": {
        "class": BaseAdapter,
        "type": PluginType.SELECTION,
        "built-in": [adapter for adapter in [NoneAdapter, IpAdapter, SerialAdapter] if adapter is not None]
    },
    "gds_function": {
        "class": GdsFunction,
        "type": PluginType.FEATURE,
        "built-in": []
    },
    "gds_app": {
        "class": GdsApp,
        "type": PluginType.FEATURE,
        "built-in": []
    }
}


class PluginException(Exception):
    pass


class InvalidCategoryException(PluginException):
    pass


class Plugins(object):
    """GDS plugin system providing a plugin Singleton for use across the GDS

    GDS plugins are broken into categories (e.g. framing) that represent the key features users can adjust. Each GDS
    application will support and load the plugins for a given category.
    """
    PLUGIN_ENVIRONMENT_VARIABLE = "FPRIME_GDS_EXTRA_PLUGINS"
    _singleton = None

    def __init__(self, categories: Union[None, List] = None):
        """ Initialize the plugin system with specific categories

        Initialize the plugin system with support for the supplied categories. Only plugins for the specified categories
        will be loaded for use. Other plugins will not be available for use.

        Args:
            categories: None for all categories otherwise a list of categories
        """
        categories = self.get_all_categories() if categories is None else categories
        self.categories = categories
        self.manager = pluggy.PluginManager(PROJECT_NAME)

        # Load hook specifications from only the configured categories
        for category in categories:
            self.manager.add_hookspecs(_PLUGIN_METADATA[category]["class"])

        # Load plugins from setuptools entrypoints and the built-in plugins (limited to category)
        self.manager.load_setuptools_entrypoints(PROJECT_NAME)

        # Load plugins from environment variable specified modules
        for token in [token for token in os.environ.get(self.PLUGIN_ENVIRONMENT_VARIABLE, "").split(";") if token]:
            module, class_token = token.split(":")
            try:
                imported_module = importlib.import_module(module)
                module_class = module if class_token == "" else getattr(imported_module, class_token, imported_module)
                self.register_plugin(module_class)
            except ImportError as imp:
                LOGGER.debug("Failed to load %s.%s as plugin", module, class_token)

        # Load built-in plugins
        for category in categories:
            for built_in in _PLUGIN_METADATA[category]["built-in"]:
                self.register_plugin(built_in)

    def get_plugins(self, category) -> Iterable:
        """Get available plugins for the given category

        Gets all plugin implementors of "category" by looking for register_<category>_plugin implementors. If such a
        function does not exist then this results in an exception.

        Args:
            category: category of the plugin requested

        Return:
            validated list of plugin implementor classes
        """
        try:
            plugin_classes = getattr(self.manager.hook, f"register_{category}_plugin")()
        except KeyError as error:
            raise InvalidCategoryException(f"Invalid plugin category: {error}")

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

    def get_categories(self):
        """ Get plugin categories """
        return self.categories

    @staticmethod
    def get_all_categories():
        """ Get all plugin categories """
        return _PLUGIN_METADATA.keys()

    @staticmethod
    def get_plugin_metadata(category):
        """ Get the plugin metadata for a given plugin category """
        return _PLUGIN_METADATA[category]

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
    def system(cls, categories: Union[None, List] = None) -> "Plugins":
        """ Get plugin system singleton

        Constructs the plugin system singleton (when it has yet to be constructed) then returns the singleton. The
        singleton will support specific categories and further requests for a singleton will cause an assertion error
        unless the categories match or is None.

        Args:
            categories: a list of categories to support or None to use the existing categories

        Returns:
            plugin system
        """
        # Singleton undefined, construct it
        if cls._singleton is None:
            cls._singleton = cls(cls.get_all_categories() if categories is None else categories)
        # Ensure categories was unspecified or matches the singleton
        assert categories is None or cls._singleton.categories == categories, "Inconsistent plugin categories"
        return cls._singleton

