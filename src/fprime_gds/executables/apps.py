"""fprime_gds.executables.apps: an implementation of start-up apps in fprime

There are twp ways to approach start=up applications in fprime. First, is to implement a run method via a subclass of
`GdsFunction`. This gives the implementor the ability to run anything within the run function that python offers,
however; this comes with complexity of setting up a new thread/process/isolation to ensure that the plugin does not
threaten the fprime-gds core functionality and processes.

The second method is to inherit from `GdsApp` implementing the `get_process_invocation` function to return the necessary
command line that will be spun into its own process.

@author lestarch
"""

import subprocess
import sys
from abc import ABC, abstractmethod
import argparse
from typing import final, List, Dict, Tuple, Type, Optional

from fprime_gds.plugin.definitions import gds_plugin_specification, gds_plugin
from fprime_gds.plugin.system import Plugins
from fprime_gds.executables.cli import (
    CompositeParser,
    ParserBase,
    BareArgumentParser,
    MiddleWareParser,
    DictionaryParser,
    StandardPipelineParser,
    PluginArgumentParser,
)
from fprime_gds.common.pipeline.standard import StandardPipeline
from fprime_gds.common.pipeline.publishing import PublishingPipeline


class GdsBaseFunction(ABC):
    """Base functionality for pluggable GDS start-up functions

    GDS start-up functionality is pluggable. This class acts as a base for pluggable functionality supplies helpers to
    the various start-up plugins.

    Developers who intend to run in an isolated subprocess are strongly encouraged to use `GdsApp` (see below).
    Developers who need flexibility may use GdsFunction.
    """

    @abstractmethod
    def run(self, parsed_args):
        """Run the start-up function

        Run the start-up function unconstrained by the limitations of running in a dedicated subprocess.

        """
        raise NotImplementedError()


class GdsFunction(GdsBaseFunction, ABC):
    """Functionality for pluggable GDS start-up functions

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
    """GDS start-up process functionality

    A pluggable base class used to start a new process as part of the GDS command line invocation. This allows
    developers to add process-isolated functionality to the GDS network.

    Plugin developers are required to implement the `get_process_invocation` function that returns a list of arguments
    needed to invoke the process via python's `subprocess`. Additionally, the developer must define the
    `register_gds_function_plugin` class method annotated with the @gds_plugin_implementation annotation.

    Standard plug-in functions (get_name, get_arguments) are available should the implementer desire these features.
    Arguments will be supplied to the class's `__init__` function.
    """

    def __init__(self, **arguments):
        """Construct the communication applications around the arguments

        Command line arguments are passed in to match those returned from the `get_arguments` functions.

        Args:
            arguments: arguments from the command line
        """
        self.process = None
        self.arguments = arguments

    def run(self, parsed_args):
        """Run the application as an isolated process

        GdsFunction objects require an implementation of the `run` command. This implementation will take the arguments
        provided from `get_process_invocation` function and supplies them as an invocation of the isolated subprocess.
        """
        invocation_arguments = self.get_process_invocation(parsed_args)
        self.process = subprocess.Popen(invocation_arguments)

    def wait(self, timeout=None):
        """Wait for the app to complete then return the return code

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
    def get_process_invocation(
        self, namespace: Optional[argparse.Namespace] = None
    ) -> List[str]:
        """Run the start-up function

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


class GdsStandardApp(GdsApp):
    """Standard GDS application that is built upon the StandardPipeline

    Use this class to help build a GdsApp plugin that has a known invocation and starts up the standard pipeline to
    enable standard GDS processes.

    Developers should implement a concrete subclass with the `start(pipeline)` function to run the application with the
    supplied pipeline. The subclass must supply **kwargs parent class constructor and extend a GdsApp plugin:

    ```
    @gds_plugin(GdsApp)
    class MyStandardApp(GdsStandardApp):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
        ...
    ```

    If the plugin requires more arguments beyond the standard pipeline arguments, supply those additional arguments via
    the `get_additional_arguments` method.
    """

    def __init__(self, **kwargs):
        """Take all arguments and store them"""
        super().__init__(**kwargs)

    @classmethod
    def get_additional_arguments(cls) -> Dict[Tuple, Dict[str, str]]:
        """Function to provide additional command line arguments beyond the standard pipeline

        Override this function to provide additional arguments. The form of the arguments are the same as returned by
        standard plugins: a dictionary of tuple flags to argparse kwargs inputs.

        Return:
            dictionary of flag tuple to argparse kwargs
        """
        return {}
    
    @classmethod
    def get_additional_cli_parsers(cls) -> List[ParserBase]:
        """ Supply a list of CLI parser objects
        
        Supply a list of CLI parser objects to the CLI system. This allows use of full ParserBase objects instead of
        the more restrictive dictionary approach seen in get_additional_arguments.

        Returns:
            list of parser objects as passed to ParserBase
        """
        return []

    @classmethod
    def init(cls):
        """Allows standard application plugins to initialize before argument parsing is performed"""
        pass

    @final
    @classmethod
    def get_arguments(cls):
        """Get the arguments for this plugin

        This will return the combined arguments needed for the standard pipeline, and those returned from
        `get_additional_arguments()`.
        """
        return {
            **cls.get_additional_arguments(),
            **StandardPipelineParser().get_arguments(),
        }

    @classmethod
    def get_cli_parser(cls):
        """Helper to get a parser for this applications' additional arguments"""
        return BareArgumentParser(
            cls.get_additional_arguments(), getattr(cls, "check_arguments", None)
        )

    @abstractmethod
    def start(self, pipeline: StandardPipeline):
        """Start function to contain behavior based in standard pipeline"""
        raise NotImplementedError()

    def get_process_invocation(self, namespace=None):
        """Return the process invocation for this class' main

        The process invocation of this application is to run cls.main and supply it a reproduced version of the
        arguments needed for the given parsers.  When main is loaded, it will dispatch to the sub-classing plugin's
        start method. The subclassing plugin will already have had the arguments supplied via the PluginParser's
        construction of plugin objects.

        Returns:
            list of arguments to pass to subprocess
        """
        cls = self.__class__.__name__
        module = self.__class__.__module__

        composite_parser = CompositeParser(
            [self.get_cli_parser(), StandardPipelineParser]
        )
        if namespace is None:
            namespace, _, _ = ParserBase.parse_known_args([composite_parser], client=True)
        args = composite_parser.reproduce_cli_args(namespace)
        return [sys.executable, "-c", f"import {module}\n{module}.{cls}.main()"] + args

    @classmethod
    def main(cls):
        """Main function used as a generic entrypoint for GdsStandardApp derived GdsApp plugins"""
        try:
            cls.init()
            try:
                Plugins.system(
                    []
                )  # Disable plugin system unless specified through init
            # In the case where `init` sets up the plugin system, we want to pass the assertion
            # triggered by the code above that turns it off in the not-setup case.
            except AssertionError:
                pass
            plugin_name = getattr(cls, "get_name", lambda: cls.__name__)()
            plugin_composite = CompositeParser([cls.get_cli_parser()] + cls.get_additional_cli_parsers())

            parsed_arguments, _ = ParserBase.parse_args(
                # StandardPipelineParser first as it loads the FSW dictionary into global config
                [ StandardPipelineParser, PluginArgumentParser, plugin_composite],
                f"{plugin_name}: a standard app plugin",
                client=True,
            )
            pipeline = StandardPipeline()
            # Turn off history, file handling, and logging
            pipeline.histories.implementation = None
            pipeline.filing = None
            parsed_arguments.disable_data_logging = True 
            pipeline = StandardPipelineParser.pipeline_factory(
                parsed_arguments, pipeline
            )
            application = cls(
                **cls.get_cli_parser().extract_arguments(parsed_arguments),
                namespace=parsed_arguments, 

            )
            application.start(pipeline)
            sys.exit(0)
        except Exception as e:
            print(f"[ERROR] Error launching {cls.__name__}: {e}", file=sys.stderr)
            sys.exit(148)




@gds_plugin(GdsApp)
class CustomDataHandlers(GdsStandardApp):
    """Run an app that registers all custom data handlers

    A GdsApp plugin, built using the GdsStandardApp helper, that uses the provided standard pipeline to register each
    custom DataHandler plugin as a consumer of the appropriate type.
    """
    PLUGIN_PARSER = CompositeParser([DictionaryParser, MiddleWareParser])

    def __init__(self, namespace, **kwargs):
        """Required __init__ implementation"""
        super().__init__(**kwargs)
        self.connection_transport = namespace.connection_transport
        self.connection_uri = namespace.connection_uri
        self.dictionaries  = namespace.dictionaries

    @classmethod
    def get_additional_arguments(cls):
        """ Supplies additional arguments needed """
        return {}

    @classmethod
    def get_additional_cli_parsers(cls):
        """ Requires MiddleWareParser and Dictionary Parser"""
        return [cls.PLUGIN_PARSER]


    @classmethod
    def init(cls):
        """Set up the system to use only data_handler plugins"""
        Plugins.system(["data_handler"])

    def start(self, pipeline: StandardPipeline):
        """Iterates over each data handler, registering to the producing decoder"""
        DESCRIPTOR_TO_FUNCTION = {
            "FW_PACKET_TELEM": pipeline.coders.register_channel_consumer,
            "FW_PACKET_LOG": pipeline.coders.register_event_consumer,
            "FW_PACKET_FILE": pipeline.coders.register_file_consumer,
            "FW_PACKET_PACKETIZED_TLM": pipeline.coders.register_packet_consumer,
        }
        self.publisher = PublishingPipeline()
        self.publisher.transport_implementation = self.connection_transport
        self.publisher.setup(self.dictionaries)
        self.publisher.connect(self.connection_uri)

        data_handlers = Plugins.system().get_feature_classes("data_handler")
        for data_handler_class in data_handlers:
            data_handler = data_handler_class()
            data_handler.set_publisher(self.publisher)
            descriptors = data_handler.get_handled_descriptors()
            for descriptor in descriptors:
                DESCRIPTOR_TO_FUNCTION.get(descriptor, lambda discard: discard)(
                    data_handler
                )

    @classmethod
    def get_name(cls):
        """Return the name of this application"""
        return "custom-data-handlers-app"
