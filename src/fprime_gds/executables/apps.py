""" fprime_gds.executables.apps: an implementation of start-up apps in fprime

There are twp ways to approach start=up applications in fprime. First, is to implement a run method via a subclass of
`GdsFunction`. This gives the implementor the ability to run anything within the run function that python offers,
however; this comes with complexity of setting up a new thread/process/isolation to ensure that the plugin does not
threaten the fprime-gds core functionality and processes.

The second method is to inherit from `GdsApp` implementing the `get_process_invocation` function to return the necessary
command line that will be spun into its own process.

@author lestarch
"""
import abc
import subprocess
from typing import List


class GdsFunction(object):
    """ Base functionality for pluggable GDS start-up functions

    GDS start-up functionality is pluggable. This class acts as a base for pluggable functionality that requires
    complete control of the start-up functionality. However, this comes at the cost of instability in that case of
    poorly designed functions.

    Developers who intend to run in an isolated subprocess are strongly encouraged to use `GdsApp` (see below).

    Plugin developers are required to implement a single function `run`, which must take care of setting up and running
    the start-up function. Developers **must** handle the isolation of this functionality including spinning off a new
    thread, subprocess, etc. Additionally, the developer must define the `register_gds_function_plugin` class method
    annotated with the @gds_plugin_implementation annotation.

    Standard plug-in functions (get_name, get_arguments) are available should the implementer desire these features.
    Arguments will be supplied to the class's `__init__` function.
    """

    @abc.abstractmethod
    def run(self):
        """ Run the start-up function

        Run the start-up function unconstrained by the limitations of running in a dedicated subprocess.

        """
        raise NotImplementedError()


class GdsApp(GdsFunction):
    """ GDS start-up proces functionality

    A pluggable base class used to start a new process as part of the GDS command line invocation. This allows
    developers to add process-isolated functionality to the GDS network.

    Plugin developers are required to implement the `get_process_invocation` function that returns a list of arguments
    needed to invoke the process via python's `subrpocess`. Additionally, the developer must define the
    `register_gds_function_plugin` class method annotated with the @gds_plugin_implementation annotation.

    Standard plug-in functions (get_name, get_arguments) are available should the implementer desire these features.
    Arguments will be supplied to the class's `__init__` function.
    """
    def __init__(self):
        """ Constructor """
        self.process = None

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

    @abc.abstractmethod
    def get_process_invocation(self) -> List[str]:
        """ Run the start-up function

        Run the start-up function unconstrained by the limitations of running in a dedicated subprocess.

        """
        raise NotImplementedError()
