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
import itertools
import os
import re
import platform
import sys

import fprime_gds.common.logger

# Required to set the checksum as a module variable
import fprime_gds.common.communication.checksum

from abc import abstractmethod, ABC
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fprime_gds.common.communication.adapters.base import BaseAdapter
from fprime_gds.common.communication.adapters.ip import check_port
from fprime_gds.common.pipeline.standard import StandardPipeline
from fprime_gds.common.transport import ThreadedTCPSocketClient
from fprime_gds.executables.utils import get_artifacts_root, find_dict, find_app
from fprime_gds.common.utils.config_manager import ConfigManager

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
        parser = argparse.ArgumentParser(description=self.description, add_help=True)
        for flags, keywords in self.get_arguments().items():
            parser.add_argument(*flags, **keywords)
        return parser

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
                [str(value)]
                if not isinstance(value, list)
                else [str(item) for item in value]
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
            ("-r", "--root"): {
                "dest": "root_input",
                "action": "store",
                "required": False,
                "type": str,
                "help": "Root directory of build artifacts, used to automatically find app and dictionary. [default: install_dest field in settings.ini]",
            }
        }

    def handle_arguments(self, args, **kwargs):
        """Handle the root, detecting it if necessary"""
        args.root_directory = (
            Path(args.root_input) if args.root_input else get_artifacts_root()
        ) / platform.system()
        if not args.root_directory.exists():
            raise ValueError(
                f"F prime artifacts root directory '{args.root_directory}' does not exist"
            )
        return args


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


class CommAdapterParser(ParserBase):
    """
    Handles parsing of all of the comm-layer arguments. This means selecting a comm adapter, and passing the arguments
    required to setup that comm adapter. In addition, this parser uses the import parser to import modules such that a
    user may import other adapter implementation files.
    """

    DESCRIPTION = "Process arguments needed to specify a comm-adapter"

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Get arguments for the comm-layer parser"""
        adapter_definition_dictionaries = BaseAdapter.get_adapters()
        adapter_arguments = {}
        for name, adapter in adapter_definition_dictionaries.items():
            adapter_arguments_callable = getattr(adapter, "get_arguments", None)
            if not callable(adapter_arguments_callable):
                print(
                    f"[WARNING] '{name}' does not have 'get_arguments' method, skipping.",
                    file=sys.stderr,
                )
                continue
            adapter_arguments.update(adapter.get_arguments())
        com_arguments = {
            ("--comm-adapter",): {
                "dest": "adapter",
                "action": "store",
                "type": str,
                "help": "Adapter for communicating to flight deployment. [default: %(default)s]",
                "choices": ["none"]
                + [name for name in adapter_definition_dictionaries.keys()],
                "default": "ip",
            },
            ("--comm-checksum-type",): {
                "dest": "checksum_type",
                "action": "store",
                "type": str,
                "help": "Setup the checksum algorithm. [default: %(default)s]",
                "choices": [
                    item
                    for item in fprime_gds.common.communication.checksum.CHECKSUM_MAPPING.keys()
                    if item != "default"
                ],
                "default": fprime_gds.common.communication.checksum.CHECKSUM_SELECTION,
            },
        }
        return {**adapter_arguments, **com_arguments}

    def handle_arguments(self, args, **kwargs):
        """
        Handle the input arguments for the parser. This will help setup the adapter with its expected arguments.

        :param args: parsed arguments in namespace format
        :return: namespace with "comm_adapter" value added
        """
        args.comm_adapter = BaseAdapter.construct_adapter(args.adapter, args)
        fprime_gds.common.communication.checksum.CHECKSUM_SELECTION = args.checksum_type
        return args


class LogDeployParser(ParserBase):
    """
    A parser that handles log files by reading in a '--logs' directory or a '--deploy' directory to put the logs into
    as a default. This is useful as a parsing fragment for any application that produces log files and needs these logs
    to end up in the proper place.
    """

    DESCRIPTION = "Process arguments needed to specify a logging"

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

    DESCRIPTION = "Process arguments needed to specify a tool using the middleware"

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
                ("--zmq-server",): {
                    "dest": "zmq_server",
                    "action": "store_true",
                    "help": "Sets the ZMQ connection to be a server. Default: false (client)",
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
            raise ValueError(f"Dictionary file {args.dictionary} does not exist")
        elif args.dictionary is None:
            args = super().handle_arguments(args, **kwargs)
            args.dictionary = find_dict(args.root_directory)
        return args


class FileHandlingParser(ParserBase):
    """Parser for deployments"""

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Arguments to handle deployments"""
        return {
            ("--file-storage-directory",): {
                "dest": "files_directory",
                "action": "store",
                "default": "/tmp/fprime-downlink/",
                "required": False,
                "type": str,
                "help": "File to store uplink and downlink files. Default: %(default)s",
            }
        }

    def handle_arguments(self, args, **kwargs):
        """Handle arguments as parsed"""
        os.makedirs(args.files_directory, exist_ok=True)
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
            "down_store": args_ns.files_directory,
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

    CONSTITUENTS = [CommAdapterParser, MiddleWareParser, LogDeployParser]

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

    DESCRIPTION = "Process arguments needed to specify a tool using the GDS"

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

    DESCRIPTION = "Process arguments needed for running F prime binary"

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
        args.app = Path(args.app) if args.app else Path(find_app(args.root_directory))
        if not args.app.is_file():
            raise ValueError(
                f"F prime binary '{args.app}' does not exist or is not a file"
            )
        return args


class SearchArgumentsParser(ParserBase):
    """Parser for search arguments"""

    DESCRIPTION = (
        "Process arguments relevant to searching/filtering Channels/Events/Commands"
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

    DESCRIPTION = "Process arguments relevant to retrieving Channels/Events"

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
                "help": f"returns response in JSON format",
            },
        }

    def handle_arguments(self, args, **kwargs):
        return args
