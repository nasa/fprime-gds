"""
cli.py:

This file sets up the command line interface and argument parsing that is done to support the F prime executable tools
layer. It is designed to allow users to import standard sets of arguments that applied to the various aspects of the
code that they are importing.

@author mstarch
"""

import argparse
import datetime
import errno
import getpass
import itertools
import os
import platform
import re
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Required to set the checksum as a module variable
import fprime_gds.common.communication.checksum
import fprime_gds.common.logger
from fprime_gds.common.communication.adapters.ip import check_port
from fprime_gds.common.pipeline.standard import StandardPipeline
from fprime_gds.common.transport import ThreadedTCPSocketClient
from fprime_gds.common.utils.config_manager import ConfigManager
from fprime_gds.executables.utils import find_app, find_dict, get_artifacts_root
from fprime_gds.plugin.definitions import PluginType
from fprime_gds.plugin.system import Plugins

# Optional import: ZeroMQ. Requires package: pyzmq
try:
    import zmq

    from fprime_gds.common.zmq_transport import ZmqClient
except ImportError:
    zmq = None
    ZmqClient = None

# Optional import: Serial Adapter. Requires package: SerialAdapter
try:
    from fprime_gds.common.communication.adapters.uart import SerialAdapter
except ImportError:
    SerialAdapter = None

GUIS = ["none", "html"]


class ParserBase(ABC):
    """Base parser for handling fprime command lines

    Parsers must define several functions. They must define "get_parser", which will produce a parser to parse the
    arguments, and an optional "handle_arguments" function to do any necessary processing of the arguments. Note: when
    handling arguments.
    """

    DESCRIPTION = None

    @property
    def description(self):
        """Return parser description"""
        return self.DESCRIPTION if self.DESCRIPTION else "Unknown command line parser"

    @abstractmethod
    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Return argument list handled by this parser

        Produce the arguments that can be processed by multiple parsers. i.e. argparse, and pytest parsers are the
        intended consumers. Returns a tuple of dictionary of flag tuples (--flag, -f) to keyword arguments to pass to
        argparse and list of arguments calculated by the parser (generated).

        Returns:
            tuple of dictionary of flag tuple to keyword arguments, list of generated fields
        """

    def get_parser(self) -> argparse.ArgumentParser:
        """Return an argument parser to parse arguments here-in

        Produce a parser that will handle the given arguments. These parsers can be combined for a CLI for a tool by
        assembling them as parent processors to a parser for the given tool.

        Return:
            argparse parser for supplied arguments
        """
        parser = argparse.ArgumentParser(
            description=self.description,
            add_help=True,
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        self.fill_parser(parser)
        return parser

    def fill_parser(self, parser):
        """ Fill supplied parser with arguments

        Fills the supplied parser with the arguments returned via the `get_arguments` method invocation. This
        implementation add the arguments directly to the parser.

        Args:
            parser: parser to fill with arguments

        """
        for flags, keywords in self.get_arguments().items():
            try:
                parser.add_argument(*flags, **keywords)
            except argparse.ArgumentError:
                # flag has already been added, pass
                pass

    def reproduce_cli_args(self, args_ns):
        """Reproduce the list of arguments needed on the command line"""

        def flag_member(flags, argparse_inputs) -> Tuple[str, str]:
            """Get the best CLI flag and namespace member"""
            best_flag = (
                [flag for flag in flags if flag.startswith("--")] + list(flags)
            )[0]
            member = argparse_inputs.get(
                "dest", re.sub(r"^-+", "", best_flag).replace("-", "_")
            )
            return best_flag, member

        def cli_arguments(flags, argparse_inputs) -> List[str]:
            """Get CLI argument list fro argument entry"""
            best_flag, member = flag_member(flags, argparse_inputs)
            value = getattr(args_ns, member, None)

            action = argparse_inputs.get("action", "store")
            assert action in [
                "store",
                "store_true",
                "store_false",
            ], f"{action} not supported by reproduce_cli_args"

            # Handle arguments
            if (action == "store_true" and value) or (
                action == "store_false" and not value
            ):
                return [best_flag]
            elif action != "store" or value is None:
                return []
            return [best_flag] + (
                [str(item) for item in value]
                if isinstance(value, list)
                else [str(value)]
            )

        cli_pairs = [
            cli_arguments(flags, argparse_ins)
            for flags, argparse_ins in self.get_arguments().items()
        ]
        return list(itertools.chain.from_iterable(cli_pairs))

    @abstractmethod
    def handle_arguments(self, args, **kwargs):
        """Post-process the parser's arguments

        Handle arguments from the given parser. The expectation is that the "args" namespace is taken in, processed, and
        a new namespace object is returned with the processed variants of the arguments.

        Args:
            args: arguments namespace of processed arguments
        Returns: namespace with processed results of arguments.
        """

    @staticmethod
    def parse_args(
        parser_classes,
        description="No tool description provided",
        arguments=None,
        **kwargs,
    ):
        """Parse and post-process arguments

        Create a parser for the given application using the description provided. This will then add all specified
        ParserBase subclasses' get_parser output as parent parses for the created parser. Then all of the handle
        arguments methods will be called, and the final namespace will be returned.

        Args:
            parser_classes: a list of ParserBase subclasses that will be used to
            description: description passed ot the argument parser
            arguments: arguments to process, None to use command line input
        Returns: namespace with all parsed arguments from all provided ParserBase subclasses
        """
        composition = CompositeParser(parser_classes, description)
        parser = composition.get_parser()
        try:
            args_ns = parser.parse_args(arguments)
            args_ns = composition.handle_arguments(args_ns, **kwargs)
        except ValueError as ver:
            print(f"[ERROR] Failed to parse arguments: {ver}", file=sys.stderr)
            parser.print_help()
            sys.exit(-1)
        except Exception as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            raise
            sys.exit(-1)
        return args_ns, parser

    @staticmethod
    def find_in(token, deploy, is_file=True):
        """
        Find token in deploy directory by walking the directory looking for reg-ex. This effectively finds a file in a
        subtree and provides the path to it. Returns None when not found

        :param token: token to search for in the directory structure
        :param deploy: directory to start with
        :param is_file: true if looking for file, otherwise false
        :return: full path to token in tree
        """
        for dirpath, dirs, files in os.walk(deploy):
            for check in files if is_file else dirs:
                if re.match(f"^{str(token)}$", check):
                    return os.path.join(dirpath, check)
        return None


class DetectionParser(ParserBase):
    """Parser that detects items from a root/directory or deployment"""

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Arguments needed for root processing"""
        return {
            ("-d", "--deployment"): {
                "dest": "deployment",
                "action": "store",
                "required": False,
                "type": str,
                "help": "Deployment installation/build output directory. [default: install_dest field in settings.ini]",
            }
        }

    def handle_arguments(self, args, **kwargs):
        """Handle the root, detecting it if necessary"""
        if args.deployment:
            args.deployment = Path(args.deployment)
            return args
        detected_toolchain = get_artifacts_root() / platform.system()
        if not detected_toolchain.exists():
            msg = f"{detected_toolchain} does not exist. Make sure to build."
            raise Exception(msg)
        likely_deployment = detected_toolchain / Path.cwd().name
        # Check if the deployment exists
        if likely_deployment.exists():
            args.deployment = likely_deployment
            return args
        child_directories = [
            child for child in detected_toolchain.iterdir() if child.is_dir()
        ]
        if not child_directories:
            msg = f"No deployments found in {detected_toolchain}. Specify deployment with: --deployment"
            raise Exception(msg)
        # Works for the old structure where the bin, lib, and dict directories live immediately under the platform
        elif len(child_directories) == 3 and set(
            [path.name for path in child_directories]
        ) == {"bin", "lib", "dict"}:
            args.deployment = detected_toolchain
            return args
        elif len(child_directories) > 1:
            msg = f"Multiple deployments found in {detected_toolchain}. Choose using: --deployment"
            raise Exception(msg)
        args.deployment = child_directories[0]
        return args


class PluginArgumentParser(ParserBase):
    """Parser for arguments coming from plugins"""

    DESCRIPTION = "Plugin options"
    FPRIME_CHOICES = {
        "framing": "fprime",
        "communication": "ip",
    }

    def __init__(self):
        """Initialize the plugin information for this parser"""
        self._plugin_map = {
            category: Plugins.system().get_plugins(category)
            for category in Plugins.system().get_categories()
        }

    @staticmethod
    def safe_add_argument(parser, *flags, **keywords):
        """ Add an argument allowing duplicates

        Add arguments to the parser (passes through *flags and **keywords) to the supplied parser. This method traps
        errors to prevent duplicates.

        Args:
            parser: parser or argument group to add arguments to
            *flags: positional arguments passed to `add_argument`
            **keywords: key word arguments passed to `add_argument`
        """
        try:
            parser.add_argument(*flags, **keywords)
        except argparse.ArgumentError:
            # flag has already been added, pass
            pass

    def fill_parser(self, parser):
        """ File supplied parser with grouped arguments

        Fill the supplied parser with arguments from the `get_arguments` method invocation. This implementation groups
        arguments based on the constituent that sources the argument.

        Args:
            parser: parser to fill
        """
        for category, plugins in self._plugin_map.items():
            argument_group = parser.add_argument_group(title=f"{category.title()} Plugin Options")
            for flags, keywords in self.get_category_arguments(category).items():
                self.safe_add_argument(argument_group, *flags, **keywords)

            for plugin in plugins:
                argument_group = parser.add_argument_group(title=f"{category.title()} Plugin '{plugin.get_name()}' Options")
                if plugin.type == PluginType.FEATURE:
                    self.safe_add_argument(argument_group,
                                           f"--disable-{plugin.get_name()}",
                                           action="store_true",
                                           default=False,
                                           help=f"Disable the {category} plugin '{plugin.get_name()}'")
                for flags, keywords in plugin.get_arguments().items():
                    self.safe_add_argument(argument_group, *flags, **keywords)

    def get_category_arguments(self, category):
        """ Get arguments for a plugin category """
        arguments: Dict[Tuple[str, ...], Dict[str, Any]] = {}
        plugins = self._plugin_map[category]
        # Add category options: SELECTION plugins add a selection flag
        plugin_type = Plugins.get_category_plugin_type(category)
        if plugin_type == PluginType.SELECTION:
            arguments.update(
                {
                    (f"--{category}-selection",): {
                        "choices": [choice.get_name() for choice in plugins],
                        "help": f"Select {category} implementer.",
                        "default": self.FPRIME_CHOICES.get(
                            category, list(plugins)[0].get_name()
                        ),
                    }
                }
            )
        return arguments

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Return arguments to used in plugins"""
        arguments: Dict[Tuple[str, ...], Dict[str, Any]] = {}
        for category, plugins in self._plugin_map.items():
            arguments.update(self.get_category_arguments(category))
            for plugin in plugins:
                # Add disable flags for feature type plugins
                if plugin.type == PluginType.FEATURE:
                    arguments.update({
                        (f"--disable-{plugin.get_name()}", ): {
                            "action": "store_true",
                            "default": False,
                            "help": f"Disable the {category} plugin '{plugin.get_name()}'"
                        }
                    })
                arguments.update(plugin.get_arguments())
        return arguments

    def handle_arguments(self, args, **kwargs):
        """Handles the arguments"""
        for category, plugins in self._plugin_map.items():
            plugin_type = Plugins.get_category_plugin_type(category)

            # Selection plugins choose one plugin and instantiate it
            if plugin_type == PluginType.SELECTION:
                selection_string = getattr(args, f"{category}_selection")
                matching_plugins = [plugin for plugin in plugins if plugin.get_name() == selection_string]
                assert len(matching_plugins) == 1, "Plugin selection system failed"
                selection_class = matching_plugins[0].plugin_class
                filled_arguments = self.extract_plugin_arguments(args, selection_class)
                selection_instance = selection_class(**filled_arguments)
                setattr(args, f"{category}_selection_instance", selection_instance)
            # Feature plugins instantiate all enabled plugins
            elif plugin_type == PluginType.FEATURE:
                enabled_plugins = [
                    plugin for plugin in plugins
                    if not getattr(args, f"disable_{plugin.get_name().replace('-', '_')}", False)
                ]
                plugin_instantiations = [
                    plugin.plugin_class(**self.extract_plugin_arguments(args, plugin))
                    for plugin in enabled_plugins
                ]
                setattr(args, f"{category}_enabled_instances", plugin_instantiations)
        return args

    @staticmethod
    def extract_plugin_arguments(args, plugin) -> Dict[str, Any]:
        """Extract plugin argument values from the args namespace into a map

        Plugin arguments will be supplied to the `__init__` function of the plugin via a keyword argument dictionary.
        This function maps from the argument namespace from parsing back into that dictionary.

        Args:
            args: argument namespace from argparse
            plugin: plugin to extract arguments for
        Return:
            filled arguments dictionary
        """
        expected_args = plugin.get_arguments()
        argument_destinations = [
            (
                value["dest"]
                if "dest" in value
                else key[0].replace("--", "").replace("-", "_")
            )
            for key, value in expected_args.items()
        ]
        filled_arguments = {
            destination: getattr(args, destination)
            for destination in argument_destinations
        }
        # Check arguments or yield a Value error
        if hasattr(plugin, "check_arguments"):
            plugin.check_arguments(**filled_arguments)
        return filled_arguments


class CompositeParser(ParserBase):
    """Composite parser handles parsing as a composition of multiple other parsers"""

    def __init__(self, constituents, description=None):
        """Construct this parser by instantiating the sub-parsers"""
        self.given = description
        constructed = [constituent() for constituent in constituents]
        flattened = [
            item.constituents if isinstance(item, CompositeParser) else [item]
            for item in constructed
        ]
        self.constituent_parsers = {*itertools.chain.from_iterable(flattened)}

    def fill_parser(self, parser):
        """ File supplied parser with grouped arguments

        Fill the supplied parser with arguments from the `get_arguments` method invocation. This implementation groups
        arguments based on the constituent that sources the argument.

        Args:
            parser: parser to fill
        """
        for constituent in sorted(self.constituents, key=lambda x: x.description):
            if isinstance(constituent, (PluginArgumentParser, CompositeParser)):
                constituent.fill_parser(parser)
            else:
                argument_group = parser.add_argument_group(title=constituent.description)
                constituent.fill_parser(argument_group)

    @property
    def constituents(self):
        """Get constituent"""
        return self.constituent_parsers

    @property
    def description(self):
        """Return parser description"""
        return (
            self.given
            if self.given
            else ",".join(item.description for item in self.constituents)
        )

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Get the argument from all constituents"""
        arguments = {}
        for constituent in self.constituents:
            arguments.update(constituent.get_arguments())
        return arguments

    def handle_arguments(self, args, **kwargs):
        """Process all constituent arguments"""
        for constituent in self.constituents:
            args = constituent.handle_arguments(args, **kwargs)
        return args


class CommExtraParser(ParserBase):
    """Parses extra communication arguments"""

    DESCRIPTION = "Communications options"

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Get arguments for the comm-layer parser"""
        com_arguments = {
            ("--output-unframed-data",): {
                "dest": "output_unframed_data",
                "action": "store",
                "nargs": "?",
                "help": "Log unframed data to supplied file relative to log directory. Use '-' for standard out.",
                "default": None,
                "const": "unframed.log",
                "required": False,
            },
        }
        return com_arguments

    def handle_arguments(self, args, **kwargs):
        return args


class LogDeployParser(ParserBase):
    """
    A parser that handles log files by reading in a '--logs' directory or a '--deploy' directory to put the logs into
    as a default. This is useful as a parsing fragment for any application that produces log files and needs these logs
    to end up in the proper place.
    """

    DESCRIPTION = "Logging options"

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Return arguments to parse logging options"""
        return {
            ("-l", "--logs"): {
                "dest": "logs",
                "action": "store",
                "default": os.path.join(os.getcwd(), "logs"),
                "type": str,
                "help": "Logging directory. Created if non-existent. [default: %(default)s]",
            },
            ("--log-directly",): {
                "dest": "log_directly",
                "action": "store_true",
                "default": False,
                "help": "Logging directory is used directly, no extra dated directories created.",
            },
            ("--log-to-stdout",): {
                "action": "store_true",
                "default": False,
                "help": "Log to standard out along with log output files",
            },
        }

    def handle_arguments(self, args, **kwargs):
        """
        Read the arguments specified in this parser and validate the expected inputs.

        :param args: parsed arguments as namespace
        :return: args namespace
        """
        # Get logging dir
        if not args.log_directly:
            args.logs = os.path.abspath(
                os.path.join(
                    args.logs, datetime.datetime.now().strftime("%Y_%m_%d-%H_%M_%S")
                )
            )
            # A dated directory has been set, all log handling must now be direct
            args.log_directly = True

        # Make sure directory exists
        try:
            os.makedirs(args.logs, exist_ok=True)
        except OSError as osexc:
            if osexc.errno != errno.EEXIST:
                raise
        # Setup the basic python logging
        fprime_gds.common.logger.configure_py_log(
            args.logs, mirror_to_stdout=args.log_to_stdout
        )
        return args


class MiddleWareParser(ParserBase):
    """
    Middleware (ThreadedTcpServer, ZMQ) interface that looks for an address and a port. The argument handling will
    attempt to connect to the socket to ensure that it is a valid address/port and report any errors. This is then
    immediately closes the port after use. There is a minor race-condition between this check and the actual usage,
    however; it should be close enough.
    """

    DESCRIPTION = "Middleware options"

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Return arguments necessary to run a and connect to the GDS middleware"""
        # May use ZMQ transportation layer if zmq package is available
        zmq_arguments = {}
        if zmq is not None and ZmqClient is not None:
            zmq_arguments = {
                ("--zmq",): {
                    "dest": "zmq",
                    "action": "store_true",
                    "help": "Switch to using the ZMQ transportation layer",
                    "default": False,
                },
                ("--zmq-transport",): {
                    "dest": "zmq_transport",
                    "nargs": 2,
                    "help": "Pair of URls used with --zmq to setup ZeroMQ transportation [default: %(default)s]",
                    "default": [
                        "ipc:///tmp/fprime-server-in",
                        "ipc:///tmp/fprime-server-out",
                    ],
                    "metavar": ("serverInUrl", "serverOutUrl"),
                },
            }
        tts_arguments = {
            ("--tts-port",): {
                "dest": "tts_port",
                "action": "store",
                "type": int,
                "help": "Set the threaded TCP socket server port [default: %(default)s]",
                "default": 50050,
            },
            ("--tts-addr",): {
                "dest": "tts_addr",
                "action": "store",
                "type": str,
                "help": "Set the threaded TCP socket server address [default: %(default)s]",
                "default": "0.0.0.0",
            },
        }
        return {**zmq_arguments, **tts_arguments}

    def handle_arguments(self, args, **kwargs):
        """
        Checks to ensure that the specified port and address is available before connecting. This prevents user from
        attempting to run on a port that is unavailable.

        :param args: parsed argument namespace
        :return: args namespace
        """
        is_client = kwargs.get("client", False)
        args.zmq = getattr(args, "zmq", False)
        tts_connection_address = (
            args.tts_addr.replace("0.0.0.0", "127.0.0.1")
            if is_client
            else args.tts_addr
        )

        args.connection_uri = f"tcp://{tts_connection_address}:{args.tts_port}"
        args.connection_transport = ThreadedTCPSocketClient
        if args.zmq:
            args.connection_uri = args.zmq_transport
            args.connection_transport = ZmqClient
        elif not is_client:
            check_port(args.tts_addr, args.tts_port)
        return args


class DictionaryParser(DetectionParser):
    """Parser for deployments"""

    DESCRIPTION = "Dictionary options"

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Arguments to handle deployments"""
        return {
            **super().get_arguments(),
            **{
                ("--dictionary",): {
                    "dest": "dictionary",
                    "action": "store",
                    "default": None,
                    "required": False,
                    "type": str,
                    "help": "Path to dictionary. Overrides automatic dictionary detection.",
                },
                ("--packet-spec",): {
                    "dest": "packet_spec",
                    "action": "store",
                    "default": None,
                    "required": False,
                    "type": str,
                    "help": "Path to packet specification.",
                },
            },
        }

    def handle_arguments(self, args, **kwargs):
        """Handle arguments as parsed"""
        # Find dictionary setting via "dictionary" argument or the "deploy" argument
        if args.dictionary is not None and not os.path.exists(args.dictionary):
            msg = f"Dictionary file {args.dictionary} does not exist"
            raise ValueError(msg)
        elif args.dictionary is None:
            args = super().handle_arguments(args, **kwargs)
            args.dictionary = find_dict(args.deployment)
        return args


class FileHandlingParser(ParserBase):
    """Parser for deployments"""

    DESCRIPTION = "File handling options"

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Arguments to handle deployments"""

        username = getpass.getuser()

        return {
            ("--file-storage-directory",): {
                "dest": "files_storage_directory",
                "action": "store",
                "default": "/tmp/" + username,
                "required": False,
                "type": str,
                "help": "Directory to store uplink and downlink files. Default: %(default)s",
            },
            ("--remote-sequence-directory",): {
                "dest": "remote_sequence_directory",
                "action": "store",
                "default": "/seq",
                "required": False,
                "type": str,
                "help": "Directory to save command sequence binaries, on the remote FSW. Default: %(default)s",
            },
        }

    def handle_arguments(self, args, **kwargs):
        """Handle arguments as parsed"""
        try:
            Path(args.files_storage_directory).mkdir(parents=True, exist_ok=True)
        except PermissionError:
            raise PermissionError(
                f"{args.files_storage_directory} is not writable. Fix permissions or change storage directory with --file-storage-directory."
            )
        return args


class StandardPipelineParser(CompositeParser):
    """Standard pipeline argument parser: combination of MiddleWare and"""

    CONSTITUENTS = [
        DictionaryParser,
        FileHandlingParser,
        MiddleWareParser,
        LogDeployParser,
    ]

    def __init__(self):
        """Initialization"""
        super().__init__(
            constituents=self.CONSTITUENTS, description="Standard pipeline setup"
        )

    @staticmethod
    def pipeline_factory(args_ns, pipeline=None) -> StandardPipeline:
        """A factory of the standard pipeline given the handled arguments"""
        pipeline_arguments = {
            "config": ConfigManager(),
            "dictionary": args_ns.dictionary,
            "file_store": args_ns.files_storage_directory,
            "packet_spec": args_ns.packet_spec,
            "logging_prefix": args_ns.logs,
        }
        pipeline = pipeline if pipeline else StandardPipeline()
        pipeline.transport_implementation = args_ns.connection_transport
        try:
            pipeline.setup(**pipeline_arguments)
            pipeline.connect(args_ns.connection_uri)
        except Exception:
            # In all error cases, pipeline should be shutdown before continuing with exception handling
            try:
                pipeline.disconnect()
            finally:
                raise
        return pipeline


class CommParser(CompositeParser):
    """Comm Executable Parser"""

    CONSTITUENTS = [
        CommExtraParser,
        MiddleWareParser,
        LogDeployParser,
        PluginArgumentParser,
    ]

    def __init__(self):
        """Initialization"""
        super().__init__(
            constituents=self.CONSTITUENTS,
            description="Communications bridge application",
        )


class GdsParser(ParserBase):
    """
    Provides a parser for the following arguments:

    - dictionary: path to dictionary, either a folder for py_dicts, or a file for XML dicts
    - logs: path to logging path
    - config: configuration for GDS.

    Note: deployment can help in setting both dictionary and logs, but isn't strictly required.
    """

    DESCRIPTION = "GUI options"

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Return arguments necessary to run a binary deployment via the GDS"""
        return {
            ("-g", "--gui"): {
                "choices": GUIS,
                "dest": "gui",
                "type": str,
                "help": "Set the desired GUI system for running the deployment. [default: %(default)s]",
                "default": "html",
            },
            ("--gui-addr",): {
                "dest": "gui_addr",
                "action": "store",
                "default": "127.0.0.1",
                "required": False,
                "type": str,
                "help": "Set the GUI server address [default: %(default)s]",
            },
            ("--gui-port",): {
                "dest": "gui_port",
                "action": "store",
                "default": "5000",
                "required": False,
                "type": str,
                "help": "Set the GUI server address [default: %(default)s]",
            },
        }

    def handle_arguments(self, args, **kwargs):
        """
        Takes the arguments from the parser, and processes them into the needed map of key to dictionaries for the
        program. This will throw if there is an error.

        :param args: parsed args into a namespace
        :return: args namespace
        """
        return args


class BinaryDeployment(DetectionParser):
    """
    Parsing subclass used to read the arguments of the binary application. This derives functionality from a comm parser
    and represents the flight-side of the equation.
    """

    DESCRIPTION = "FPrime binary options"

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Return arguments necessary to run a binary deployment via the GDS"""
        return {
            **super().get_arguments(),
            **{
                ("-n", "--no-app"): {
                    "dest": "noapp",
                    "action": "store_true",
                    "default": False,
                    "help": "Do not run deployment binary. Overrides --app.",
                },
                ("--app",): {
                    "dest": "app",
                    "action": "store",
                    "required": False,
                    "type": str,
                    "help": "Path to app to run. Overrides automatic app detection.",
                },
            },
        }

    def handle_arguments(self, args, **kwargs):
        """
        Takes the arguments from the parser, and processes them into the needed map of key to dictionaries for the
        program. This will throw if there is an error.

        :param args: parsed arguments in namespace
        :return: args namespaces
        """
        # No app, stop processing now
        if args.noapp:
            return args
        args = super().handle_arguments(args, **kwargs)
        args.app = Path(args.app) if args.app else Path(find_app(args.deployment))
        if not args.app.is_file():
            msg = f"F prime binary '{args.app}' does not exist or is not a file"
            raise ValueError(msg)
        return args


class SearchArgumentsParser(ParserBase):
    """Parser for search arguments"""

    DESCRIPTION = (
        "Searching and filtering options"
    )

    def __init__(self, command_name: str) -> None:
        self.command_name = command_name

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Return arguments necessary to search through channels/events/commands"""
        return {
            ("--list",): {
                "dest": "is_printing_list",
                "action": "store_true",
                "help": f"list all possible {self.command_name[:-1]} types the current F Prime instance could produce, based on the {self.command_name} dictionary, sorted by {self.command_name[:-1]} type ID",
            },
            ("-i", "--ids"): {
                "dest": "ids",
                "action": "store",
                "required": False,
                "type": int,
                "nargs": "+",
                "help": f"only show {self.command_name} matching the given type ID(s) 'ID'; can provide multiple IDs to show all given types",
                "metavar": "ID",
            },
            ("-c", "--components"): {
                "dest": "components",
                "nargs": "+",
                "required": False,
                "type": str,
                "help": f"only show {self.command_name} from the given component name 'COMP'; can provide multiple components to show {self.command_name} from all components given",
                "metavar": "COMP",
            },
            ("-s", "--search"): {
                "dest": "search",
                "required": False,
                "type": str,
                "help": f'only show {self.command_name} whose name or output string exactly matches or contains the entire given string "STRING"',
            },
        }

    def handle_arguments(self, args, **kwargs):
        return args


class RetrievalArgumentsParser(ParserBase):
    """Parser for retrieval arguments"""

    DESCRIPTION = "Data retrieval options"

    def __init__(self, command_name: str) -> None:
        self.command_name = command_name

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Return arguments to retrieve channels/events/commands in specific ways"""
        return {
            ("-t", "--timeout"): {
                "dest": "timeout",
                "action": "store",
                "required": False,
                "type": float,
                "help": f"wait at most SECONDS seconds for a single new {self.command_name[:-1]}, then exit (defaults to listening until the user exits via CTRL+C, and logging all {self.command_name})",
                "metavar": "SECONDS",
                "default": 0.0,
            },
            ("-j", "--json"): {
                "dest": "json",
                "action": "store_true",
                "required": False,
                "help": "returns response in JSON format",
            },
        }

    def handle_arguments(self, args, **kwargs):
        return args
