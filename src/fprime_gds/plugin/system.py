"""fprime_gds.plugin.system: implementation of plugins

This file contains the implementation and registration of plugins for fprime_gds. Primarily, it defines the Plugins
class that handles plugins. Users can acquire the Plugin singleton with `Plugin.system()`.

This file also imports and registers plugin implementations built-into fprime-gds. These plugins are not registered
using entrypoints.

@author lestarch
"""
import copy
import os
import importlib
import inspect
import logging
from typing import Iterable, List, Union

import pluggy

from fprime_gds.plugin.definitions import Plugin, PluginType, PROJECT_NAME


# Handy constants
LOGGER = logging.getLogger(__name__)


class PluginException(Exception):
    pass


class InvalidCategoryException(PluginException):
    pass


class PluginsNotLoadedException(PluginException):
    pass


class Plugins(object):
    """GDS plugin system providing a plugin Singleton for use across the GDS

    GDS plugins are broken into categories (e.g. framing) that represent the key features users can adjust. Each GDS
    application will support and load the plugins for a given category.
    """

    PLUGIN_ENVIRONMENT_VARIABLE = "FPRIME_GDS_EXTRA_PLUGINS"
    PLUGIN_METADATA = None
    _singleton = None

    def __init__(self, categories: Union[None, List] = None):
        """Initialize the plugin system with specific categories

        Initialize the plugin system with support for the supplied categories. Only plugins for the specified categories
        will be loaded for use. Other plugins will not be available for use.

        Args:
            categories: None for all categories otherwise a list of categories
        """
        self.metadata = copy.deepcopy(self.get_plugin_metadata())
        categories = self.get_all_categories() if categories is None else categories
        self.categories = categories
        self.manager = pluggy.PluginManager(PROJECT_NAME)

        # Load hook specifications from only the configured categories
        for category in categories:
            self.manager.add_hookspecs(self.metadata[category]["class"])

        # Load plugins from setuptools entrypoints and the built-in plugins (limited to category)
        try:
            self.manager.load_setuptools_entrypoints(PROJECT_NAME)
        except Exception as e:
            LOGGER.warning("Failed to load entrypoint plugins: %s", e)
        # Load plugins from environment variable specified modules
        for token in [
            token
            for token in os.environ.get(self.PLUGIN_ENVIRONMENT_VARIABLE, "").split(";")
            if token
        ]:
            module, class_token = token.split(":")
            try:
                imported_module = importlib.import_module(module)
                module_class = (
                    module
                    if class_token == ""
                    else getattr(imported_module, class_token, imported_module)
                )
                self.register_plugin(module_class)
            except ImportError as imp:
                LOGGER.debug("Failed to load %s.%s as plugin", module, class_token)

        # Load built-in plugins
        for category in categories:
            for built_in in self.metadata[category]["built-in"]:
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

    def start_loading(self, category: str):
        """Start a category loading

        When loading plugins via the CLI, it is imperative to distinguish between the no loaded implementors case, and
        the case where loading was never attempted. This sets the variable in metadata to [] to indicate the loading
        was attempted.
        """
        metadata = self.metadata[category]
        metadata["bound_classes"] = (
            metadata["bound_classes"] if "bound_classes" in metadata else []
        )

    def add_bound_class(self, category: str, bound_class: List[object]):
        """Add class for plugin category with constructor arguments bound

        Called from the plugin cli parser, this will add a class ready for zero-argument construction to the categories'
        list of classes. This is the plugin class with constructor arguments bound to the cli arguments that fill those
        values. For SELECTION plugins, only a single instance is allowed. For FEATURE plugins, multiple bound classes
        are  allowed.

        Args:
            category: category to set
            bound_class: constructor argument bound class
        """
        self.start_loading(category)
        metadata = self.metadata[category]
        metadata["bound_classes"].append(bound_class)
        assert (
            metadata["type"] == PluginType.FEATURE
            or len(metadata["bound_classes"]) == 1
        ), f"Multiple selections for: {category}"

    def get_selected_class(self, category: str) -> object:
        """Get the selected constructor-bound class for the category"""
        metadata = self.metadata[category]
        assert (
            metadata["type"] == PluginType.SELECTION
        ), "Features allow multiple plugins"
        try:
            return metadata["bound_classes"][0]
        except (KeyError, IndexError):
            raise PluginsNotLoadedException(
                f"Plugins not loaded for category: {category}"
            )

    def get_feature_classes(self, category: str) -> object:
        """Get the selected instance for the category"""
        metadata = self.metadata[category]
        assert (
            metadata["type"] == PluginType.FEATURE
        ), "Selections have single instances"
        try:
            return metadata["bound_classes"]
        except KeyError:
            raise PluginsNotLoadedException(
                f"Plugins not loaded for category: {category}"
            )

    def register_plugin(self, module_or_class):
        """Register a plugin directly

        Allows local registration of plugin implementations that are shipped as part of the GDS package.

        Args:
            module_or_class: module or class that has plugin implementations
        """
        self.manager.register(module_or_class)

    def get_categories(self):
        """Get plugin categories"""
        return self.categories

    @classmethod
    def get_all_categories(cls):
        """Get all plugin categories"""
        return cls.get_plugin_metadata().keys()

    @classmethod
    def get_plugin_metadata(cls, category: str = None):
        """Get the metadata describing a given category

        F Prime supports certain plugin types that break down into categories. Each category has a set of built-in
        plugins class type, and plugin type. This function will load that metadata for the supplied category. If no
        category is supplied then the complete metadata block is returned.

        On first invocation, the method will load plugin types and construct the metadata object.

        Warning:
            Since the loaded plugins may use features of the plugin system, these plugins must be imported at call time
            instead of imported at the top of the module to prevent circular imports.

        Return:
            plugin metadata definitions
        """
        # Load on the first time only
        if cls.PLUGIN_METADATA is None:
            from fprime_gds.executables.apps import GdsFunction, GdsApp
            from fprime_gds.common.handlers import DataHandlerPlugin
            from fprime_gds.common.communication.framing import (
                FramerDeframer,
                FpFramerDeframer,
            )
            from fprime_gds.common.communication.ccsds.chain import SpacePacketSpaceDataLinkFramerDeframer
            from fprime_gds.common.communication.adapters.base import (
                BaseAdapter,
                NoneAdapter,
            )
            from fprime_gds.common.communication.adapters.ip import IpAdapter
            from fprime_gds.executables.apps import CustomDataHandlers

            try:
                from fprime_gds.common.communication.adapters.uart import SerialAdapter
            except ImportError:
                SerialAdapter = None
            cls.PLUGIN_METADATA = {
                "framing": {
                    "class": FramerDeframer,
                    "type": PluginType.SELECTION,
                    "built-in": [FpFramerDeframer, SpacePacketSpaceDataLinkFramerDeframer],
                },
                "communication": {
                    "class": BaseAdapter,
                    "type": PluginType.SELECTION,
                    "built-in": [
                        adapter
                        for adapter in [NoneAdapter, IpAdapter, SerialAdapter]
                        if adapter is not None
                    ],
                },
                "gds_function": {
                    "class": GdsFunction,
                    "type": PluginType.FEATURE,
                    "built-in": [],
                },
                "gds_app": {
                    "class": GdsApp,
                    "type": PluginType.FEATURE,
                    "built-in": [CustomDataHandlers],
                },
                "data_handler": {
                    "class": DataHandlerPlugin,
                    "type": PluginType.FEATURE,
                    "built-in": [],
                },
            }
            assert cls.PLUGIN_METADATA is not None, "Failed to set plugin metadata"
        return (
            cls.PLUGIN_METADATA[category]
            if category is not None
            else cls.PLUGIN_METADATA
        )

    @classmethod
    def get_category_plugin_type(cls, category):
        """Get the plugin type given the category"""
        return cls.get_plugin_metadata(category)["type"]

    @classmethod
    def get_category_specification_class(cls, category):
        """Get the plugin class given the category"""
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
        """Get plugin system singleton

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
            cls._singleton = cls(
                cls.get_all_categories() if categories is None else categories
            )
        # Ensure categories was unspecified or matches the singleton
        assert (
            categories is None or cls._singleton.categories == categories
        ), f"Inconsistent plugin categories: {categories} vs {cls._singleton.categories}"
        return cls._singleton
