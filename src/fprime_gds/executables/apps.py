""" fprime_gds.executables.apps: an implementation of start-up apps in fprime

There are twp ways to approach start=up applications in fprime. First, is to implement a run method via a subclass of
`GdsFunction`. This gives the implementor the ability to run anything within the run function that python offers,
however; this comes with complexity of setting up a new thread/process/isolation to ensure that the plugin does not
threaten the fprime-gds core functionality and processes.

The second method is to inherit from `GdsApp` implementing the `get_process_invocation` function to return the necessary
command line that will be spun into its own process.

@author lestarch
"""
import subprocess
from abc import ABC, abstractmethod
from typing import List, Type

from fprime_gds.plugin.definitions import gds_plugin_specification


class GdsBaseFunction(ABC):
    """ Base functionality for pluggable GDS start-up functions

    GDS start-up functionality is pluggable. This class acts as a base for pluggable functionality supplies helpers to
    the various start-up plugins.

    Developers who intend to run in an isolated subprocess are strongly encouraged to use `GdsApp` (see below).
    Developers who need flexibility may use GdsFunction.
    """

    @abstractmethod
    def run(self):
        """ Run the start-up function

        Run the start-up function unconstrained by the limitations of running in a dedicated subprocess.

        """
        raise NotImplementedError()


class GdsFunction(GdsBaseFunction, ABC):
    """ Functionality for pluggable GDS start-up functions

    GDS start-up functionality is pluggable. This class acts as a wide-open implementation of functionality via a single
    `run` callback. Developers have complete control of the start-up functionality. However, this comes at the cost of
    instability in that case of poorly designed functions.

    Developers who intend to run in an isolated subprocess are strongly encouraged to use `GdsApp` (see below).

    Plugin developers are required to implement a single function `run`, which must take care of setting up and running
    the start-up function. Developers **must** handle the isolation of this functionality including spinning off a new
    thread, subprocess, etc. Additionally, the developer must define the `register_gds_function_plugin` class method
    annotated with the @gds_plugin_implementation annotation.

    Standard plug-in functions (get_name, get_arguments) are available should the implementer desire these features.
    Arguments will be supplied to the class's `__init__` function.
    """

    @classmethod
    @gds_plugin_specification
    def register_gds_function_plugin(cls) -> Type["GdsFunction"]:
        """Register gds start-up functionality

        Plugin hook for registering a plugin that supplies start-up functionality. This functionality will run on start-up
        of the GDS network.

        Note: users should return the class, not an instance of the class. Needed arguments for instantiation are
        determined from class methods, solicited via the command line, and provided at construction time to the chosen
        instantiation.

        Returns:
            GDSFunction subclass
        """
        raise NotImplementedError()


class GdsApp(GdsBaseFunction):
    """ GDS start-up process functionality

    A pluggable base class used to start a new process as part of the GDS command line invocation. This allows
    developers to add process-isolated functionality to the GDS network.

    Plugin developers are required to implement the `get_process_invocation` function that returns a list of arguments
    needed to invoke the process via python's `subprocess`. Additionally, the developer must define the
    `register_gds_function_plugin` class method annotated with the @gds_plugin_implementation annotation.

    Standard plug-in functions (get_name, get_arguments) are available should the implementer desire these features.
    Arguments will be supplied to the class's `__init__` function.
    """
    def __init__(self, **arguments):
        """ Construct the communication applications around the arguments

        Command line arguments are passed in to match those returned from the `get_arguments` functions.

        Args:
            arguments: arguments from the command line
        """
        self.process = None
        self.arguments = arguments

    def run(self):
        """ Run the application as an isolated process

        GdsFunction objects require an implementation of the `run` command. This implementation will take the arguments
        provided from `get_process_invocation` function and supplies them as an invocation of the isolated subprocess.
        """
        invocation_arguments = self.get_process_invocation()
        self.process = subprocess.Popen(invocation_arguments)

    def wait(self, timeout=None):
        """ Wait for the app to complete then return the return code

        Waits (blocking) for the process to complete. Then returns the return code of the underlying process. If timeout
        is non-None then the process will be killed after waiting for the timeout and another wait of timeout will be
        allowed for the killed process to exit.

        Return:
            return code of the underlying process
        """
        try:
            _, _ = self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            _, _ = self.process.wait(timeout=timeout)
        return self.process.returncode

    @abstractmethod
    def get_process_invocation(self) -> List[str]:
        """ Run the start-up function

        Run the start-up function unconstrained by the limitations of running in a dedicated subprocess.

        """
        raise NotImplementedError()

    @classmethod
    @gds_plugin_specification
    def register_gds_app_plugin(cls) -> Type["GdsApp"]:
        """Register a gds start-up application

        Plugin hook for registering a plugin that supplies start-up functionality. This functionality will run on start-up
        of the GDS network isolated into a dedicated process.

        Note: users should return the class, not an instance of the class. Needed arguments for instantiation are
        determined from class methods, solicited via the command line, and provided at construction time to the chosen
        instantiation.

        Returns:
            GdsApp subclass
        """
        raise NotImplementedError()
