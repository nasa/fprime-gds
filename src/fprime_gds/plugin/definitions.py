"""fprime_gds.plugin.definitions: definitions of plugin specifications and decorators

In order to define a plugin, an implementation decorator is used. Users can import `gds_plugin_implementation` from this
file to decorate functions that implement plugins.

This file also defines helper classes to support the plugin system.

@author lestarch
"""

import inspect
import pluggy
from enum import Enum, auto
from typing import Any, Dict, Tuple, Type

PROJECT_NAME = "fprime_gds"

gds_plugin_specification = pluggy.HookspecMarker(PROJECT_NAME)
gds_plugin_implementation = pluggy.HookimplMarker(PROJECT_NAME)


def gds_plugin(plugin_class):
    """Decorator: make decorated class a plugin of the plugin_class

    This allows users to quickly define plugin implementations by decorating their class with the definition of the
    plugin they are implementing. This works by searching the plugin_class for a function with the attribute
    { PROJECT_NAME }_spec. This will be the specification function. It will then add an implementation of the
    implementation spec to the supplied class.

    It will check the following assertions:
      1. plugin_class has a valid gds_plugin_specification
      2. plugin_class specification is well-formed (no arguments, class method)
      2. The decorated class is a valid subclass of plugin_class
      3. The decorated class is non-abstract
    """
    assert isinstance(
        plugin_class, type
    ), "Must supply @gds_plugin valid plugin classes"
    plugin_name = plugin_class.__name__
    spec_attr = f"{ PROJECT_NAME }_spec"
    spec_methods = inspect.getmembers(
        plugin_class, predicate=lambda item: hasattr(item, spec_attr)
    )
    assert len(spec_methods) == 1, f"'{plugin_name}' is not a valid F Prime GDS plugin."
    spec_method = spec_methods[0]
    spec_method_name, spec_method_function = spec_method
    assert (
        getattr(spec_method_function, "__self__", None) == plugin_class
    ), f"'{plugin_name}' specification invalid."
    assert inspect.isabstract(
        plugin_class
    ), f"{plugin_class} is not a plugin superclass."

    def decorator(decorated_class):
        """Implementation of the decorator: check valid subclass, and add plugin method"""
        assert isinstance(decorated_class, type), "Must use @gds_plugin on classes"
        class_name = decorated_class.__name__
        assert issubclass(
            decorated_class, plugin_class
        ), f"{class_name} is not a subclass of {plugin_name}"
        assert not inspect.isabstract(
            decorated_class
        ), f"{class_name} is abstract. Plugins may not be abstract."

        def return_decorated_class(cls):
            """Function to become the plugin implementation method"""
            assert cls == decorated_class, "Plugin system failure"
            return decorated_class

        setattr(
            decorated_class,
            spec_method_name,
            classmethod(gds_plugin_implementation(return_decorated_class)),
        )
        return decorated_class

    return decorator


class PluginType(Enum):
    """Enumeration of plugin types"""

    ALL = auto()
    """ Plugin selection including all types of plugins """

    SELECTION = auto()
    """ Plugin that provides a selection between implementations """

    FEATURE = auto()
    """ Plugin that provides a feature """


class Plugin(object):
    """Plugin wrapper object"""

    def __init__(self, category: str, plugin_type: PluginType, plugin_class: Type[Any]):
        """Initialize the plugin

        Args:
            category: category of the plugin (i.e. register_<category>_function)
            plugin_type: type of plugin
            plugin_class: implementation class of the plugin
        """
        self.category = category
        self.type = plugin_type
        self.plugin_class = plugin_class

    def get_implementor(self):
        """Get the implementor of this plugin"""
        return self.plugin_class

    def get_name(self):
        """Get the name of the plugin

        Plugin names are derived from the `get_name` class method of the plugin's implementation class. When not defined
        that name is derived from the plugin's implementation class __name__ property instead.

        Returns:
            name of plugin
        """
        return (
            self.plugin_class.get_name()
            if hasattr(self.plugin_class, "get_name")
            else self.plugin_class.__name__
        )

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Get arguments needed by plugin

        Plugin argument are derived from the `get_arguments` class method of the plugin's implementation class. When not
        defined an empty dictionary is returned.

        Returns:
            argument specification for plugin
        """
        return (
            self.plugin_class.get_arguments()
            if hasattr(self.plugin_class, "get_arguments")
            else {}
        )

    def check_arguments(self, **kwargs):
        """Check a plugin's arguments

        Check a plugin's arguments if it defines a check method. Arguments are passed as kwargs just like the arguments are
        passed to the constructor.
        """
        if hasattr(self.plugin_class, "check_arguments"):
            self.plugin_class.check_arguments(**kwargs)
