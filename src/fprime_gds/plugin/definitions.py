
import pluggy
from typing import Type

PROJECT_NAME = "fprime_gds"

gds_plugin_specification = pluggy.HookspecMarker(PROJECT_NAME)
gds_plugin_implementation = pluggy.HookimplMarker(PROJECT_NAME)


@gds_plugin_specification
def register_framing_plugin() -> Type["FramerDeframer"]:
    """ Register a plugin to provide framing capabilities

    Plugin hook for registering a plugin that supplies a FramerDeframer implementation. Implementors of this hook must
    return a non-abstract subclass of FramerDeframer. This class will be provided as a framing implementation option
    that users may select via command line arguments.

    Note: users should return the class, not an instance of the class. Needed arguments for instantiation are
    determined from class methods, solicited via the command line, and provided at construction time to the chosen
    instantiation.

    Returns:
        FramerDeframer subclass
    """