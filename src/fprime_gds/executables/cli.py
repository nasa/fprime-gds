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
import functools
import getpass
import itertools
import os
import platform
import re
import sys

import yaml

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Required to set the checksum as a module variable
import fprime_gds.common.logger
from fprime_gds.common.communication.adapters.ip import check_port
from fprime_gds.common.models.dictionaries import Dictionaries
from fprime_gds.common.pipeline.standard import StandardPipeline
from fprime_gds.common.transport import ThreadedTCPSocketClient
from fprime_gds.common.utils.config_manager import ConfigManager
from fprime_gds.executables.utils import find_app, find_dict, get_artifacts_root
from fprime_gds.plugin.definitions import PluginType
from fprime_gds.plugin.system import Plugins, PluginsNotLoadedException
from fprime_gds.common.zmq_transport import ZmqClient


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

    @staticmethod
    def safe_add_argument(parser, *flags, **keywords):
        """Add an argument allowing duplicates

        Add arguments to the parser (passes through *flags and **keywords) to the supplied parser. This method traps
        errors to prevent duplicates from crashing the system when two plugins use the same flags.

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

    @classmethod
    def add_arguments_from_specification(cls, parser, arguments):
        """Safely add arguments to parser

        In parsers and plugins, arguments are represented as a map of flag tuples to argparse keyword arguments. This
        function will add arguments of that representation supplied as `arguments` to the supplied parser in a safe
        collision-avoidant manner.

        Args:
            parser: argparse Parser or ArgumentGroup, or anything with an `add_argument` function
            arguments: arguments specification

        """
        for flags, keywords in arguments.items():
            cls.safe_add_argument(parser, *flags, **keywords)

    def fill_parser(self, parser):
        """Fill supplied parser with arguments

        Fills the supplied parser with the arguments returned via the `get_arguments` method invocation. This
        implementation adds the arguments directly to the parser.

        Args:
            parser: parser to fill with arguments

        """
        self.add_arguments_from_specification(parser, self.get_arguments())

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

    def handle_values(self, values: Dict[str, Any]):
        """Post-process the parser's arguments in dictionary form

        Handle arguments from the given parser in dictionary form. This will convert to/from the namespace and then
        delegate to handle_arguments.

        Args:
            args: arguments namespace of processed arguments
        Returns: dictionary with processed results of arguments.
        """
        return vars(self.handle_arguments(args=argparse.Namespace(**values), kwargs={}))

    @abstractmethod
    def handle_arguments(self, args, **kwargs):
        """Post-process the parser's arguments

        Handle arguments from the given parser. The expectation is that the "args" namespace is taken in, processed, and
        a new namespace object is returned with the processed variants of the arguments.

        Args:
            args: arguments namespace of processed arguments
        Returns: namespace with processed results of arguments.
        """

    @classmethod
    def parse_known_args(
        cls,
        parser_classes,
        description="No tool description provided",
        arguments=None,
        **kwargs,
    ):
        """Parse and post-process arguments

        Create a parser for the given application using the description provided. This will then add all specified
        ParserBase subclasses' get_parser output as parent parses for the created parser. Then all of the handle
        arguments methods will be called, and the final namespace will be returned. This will allow unknown arguments
        which are returned as the last tuple result.

        Args:
            parser_classes: a list of ParserBase subclasses that will be used to
            description: description passed ot the argument parser
            arguments: arguments to process, None to use command line input
        Returns: namespace with all parsed arguments from all provided ParserBase subclasses
        """
        return cls._parse_args(
            parser_classes, description, arguments, use_parse_known=True, **kwargs
        )

    @classmethod
    def parse_args(
        cls,
        parser_classes,
        description="No tool description provided",
        arguments=None,
        **kwargs,
    ):
        """Parse and post-process arguments

        Create a parser for the given application using the description provided. This will then add all specified
        ParserBase subclasses' get_parser output as parent parses for the created parser. Then all of the handle
        arguments methods will be called, and the final namespace will be returned. This does not allow unknown
        arguments.

        Args:
            parser_classes: a list of ParserBase subclasses that will be used to
            description: description passed ot the argument parser
            arguments: arguments to process, None to use command line input
        Returns: namespace with all parsed arguments from all provided ParserBase subclasses
        """
        return cls._parse_args(parser_classes, description, arguments, **kwargs)

    @staticmethod
    def _parse_args(
        parser_classes,
        description="No tool description provided",
        arguments=None,
        use_parse_known=False,
        **kwargs,
    ):
        """Parse and post-process arguments helper

        Create a parser for the given application using the description provided. This will then add all specified
        ParserBase subclasses' get_parser output as parent parses for the created parser. Then all of the handle
        arguments methods will be called, and the final namespace will be returned.

        This takes a function that will take in a parser and return the parsing function to call on arguments.

        Args:
            parse_function_processor: takes a parser, returns the parse function to call
            parser_classes: a list of ParserBase subclasses that will be used to
            description: description passed ot the argument parser
            arguments: arguments to process, None to use command line input
            use_parse_known: use parse_known_arguments from argparse

        Returns: namespace with all parsed arguments from all provided ParserBase subclasses
        """
        composition = CompositeParser(parser_classes, description)
        parser = composition.get_parser()
        try:
            if use_parse_known:
                args_ns, *unknowns = parser.parse_known_args(arguments)
            else:
                args_ns = parser.parse_args(arguments)
                unknowns = []
            args_ns = composition.handle_arguments(args_ns, **kwargs)
        except ValueError as ver:
            print(f"[ERROR] Failed to parse arguments: {ver}", file=sys.stderr)
            parser.print_help()
            sys.exit(-1)
        except Exception as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            sys.exit(-1)
        return args_ns, parser, *unknowns

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


class ConfigDrivenParser(ParserBase):
    """Parser that allows options from configuration and command line

    This parser reads a configuration file (if supplied) and uses the values to drive the inputs to arguments. Command
    line arguments will still take precedence over the configured values.
    """

    DEFAULT_CONFIGURATION_PATH = Path("fprime-gds.yml")

    @classmethod
    def set_default_configuration(cls, path: Path):
        """Set path for (global) default configuration file

        Set the path for default configuration file. If unset, will use 'fprime-gds.yml'. Set to None to disable default
        configuration.
        """
        cls.DEFAULT_CONFIGURATION_PATH = path

    @classmethod
    def parse_args(
        cls,
        parser_classes,
        description="No tool description provided",
        arguments=None,
        **kwargs,
    ):
        """Parse and post-process arguments using inputs and config

        Parse the arguments in two stages: first parse the configuration data, ignoring unknown inputs, then parse the
        full argument set with the supplied configuration to fill in additional options.

        Args:
            parser_classes: a list of ParserBase subclasses that will be used to
            description: description passed ot the argument parser
            arguments: arguments to process, None to use command line input
        Returns: namespace with all parsed arguments from all provided ParserBase subclasses
        """
        arguments = sys.argv[1:] if arguments is None else arguments

        # Help should spill all the arguments, so delegate to the normal parsing flow including
        # this and supplied parsers
        if "-h" in arguments or "--help" in arguments:
            parsers = [ConfigDrivenParser] + parser_classes
            ParserBase.parse_args(parsers, description, arguments, **kwargs)
            sys.exit(0)

        # Custom flow involving parsing the arguments of this parser first, then passing the configured values
        # as part of the argument source
        ns_config, _, remaining = ParserBase.parse_known_args(
            [ConfigDrivenParser], description, arguments, **kwargs
        )
        config_options = ns_config.config_values.get("command-line-options", {})
        config_args = cls.flatten_options(config_options)
        # Argparse allows repeated (overridden) arguments, thus the CLI override is accomplished by providing
        # remaining arguments after the configured ones
        ns_full, parser = ParserBase.parse_args(
            parser_classes, description, config_args + remaining, **kwargs
        )
        ns_final = argparse.Namespace(**vars(ns_config), **vars(ns_full))
        return ns_final, parser

    @staticmethod
    def flatten_options(configured_options):
        """Flatten options down to arguments"""
        flattened = []
        if configured_options is None:
            return flattened
        for option, value in configured_options.items():
            flattened.append(f"--{option}")
            if value is not None:
                flattened.extend(
                    value if isinstance(value, (list, tuple)) else [f"{value}"]
                )
        return flattened

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Arguments needed for config processing"""
        return {
            ("-c", "--config"): {
                "dest": "config",
                "required": False,
                "default": self.DEFAULT_CONFIGURATION_PATH,
                "type": Path,
                "help": "Argument configuration file path. [default: %(default)s]",
            }
        }

    def handle_arguments(self, args, **kwargs):
        """Handle the arguments

        Loads the configuration file specified and fills in the `config_values` attribute of the namespace with the
        loaded configuration dictionary.
        """
        args.config_values = {}
        # Specified but non-existent config file is a hard error
        if (
            "-c" in sys.argv[1:] or "--config" in sys.argv[1:]
        ) and not args.config.exists():
            raise ValueError(
                f"Specified configuration file '{args.config}' does not exist"
            )
        # Read configuration if the file was set and exists
        if args.config is not None and args.config.exists():
            print(f"[INFO] Reading command-line configuration from: {args.config}")
            with open(args.config, "r") as file_handle:
                try:
                    relative_base = args.config.parent.absolute()

                    def path_constructor(loader, node):
                        """Processes !PATH annotations as relative to current file"""
                        calculated_path = relative_base / loader.construct_scalar(node)
                        return calculated_path

                    yaml.SafeLoader.add_constructor("!PATH", path_constructor)
                    loaded = yaml.safe_load(file_handle)
                    args.config_values = loaded if loaded is not None else {}
                except Exception as exc:
                    raise ValueError(
                        f"Malformed configuration {args.config}: {exc}", exc
                    )
        return args


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


class BareArgumentParser(ParserBase):
    """Takes in the argument specification (used in plugins and get_arguments) to parse args

    This parser takes in and uses a raw specification of arguments as seen in plugins and arguments to perform argument
    parsing. The spec is a map of flag tuples to argparse kwargs.

    Argument handling only validates using the checking_function which is a function taking in keyword arguments for
    each cli argument specified. This function will be called as such: `checking_function(**args)`. Use None to skip
    argument checking.  checking_function should raise ValueError to indicate an error with an argument.
    """

    def __init__(self, specification, checking_function=None):
        """Initialize this parser with the provided specification"""
        self.specification = specification
        self.checking_function = checking_function

    def get_arguments(self):
        """Raw specification is returned immediately"""
        return self.specification

    def handle_arguments(self, args, **kwargs):
        """Handle argument calls checking function to validate"""
        if self.checking_function is not None:
            self.checking_function(**self.extract_arguments(args))
        return args

    def extract_arguments(self, args) -> Dict[str, Any]:
        """Extract argument values from the args namespace into a map matching the original specification

        This function extracts arguments matching the original specification and returns them as a dictionary of key-
        value pairs.

        Return:
            filled arguments dictionary
        """
        expected_args = self.specification
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
        return filled_arguments


class IndividualPluginParser(BareArgumentParser):
    """Parser for an individual plugin's command line

    A CLI parser for an individual plugin. This handles all the functions and arguments that apply to the parsing of a
    single plugin's arguments. It also handles FEATURE plugin disable flags.
    """

    def __init__(self, plugin_system: Plugins, plugin_class: type):
        """Initialize the plugin parser

        Args:
            plugin_system: Plugins object used to work with the plugin system
            plugin_class: plugin class used for this specific parser
        """
        # Add disable flags for feature type plugins
        super().__init__(plugin_class.get_arguments(), plugin_class.check_arguments)
        self.disable_flag_destination = (
            f"disable-{plugin_class.get_name()}".lower().replace("-", "_")
        )
        self.plugin_class = plugin_class
        self.plugin_system = plugin_system

    def get_arguments(self):
        """Get the arguments for this plugin

        The individual plugin parser will read the arguments from the supplied plugin class. Additionally, if the
        plugin_class's plugin_type is FEATURE then this parser will add an disable flag to allow users to turn disable
        the plugin feature.
        """
        arguments = {}
        if self.plugin_class.type == PluginType.FEATURE:
            arguments.update(
                {
                    (f"--disable-{self.plugin_class.get_name()}",): {
                        "action": "store_true",
                        "default": False,
                        "dest": self.disable_flag_destination,
                        "help": f"Disable the {self.plugin_class.category} plugin '{self.plugin_class.get_name()}'",
                    }
                }
            )
        arguments.update(super().get_arguments())
        return arguments

    def handle_arguments(self, args, **kwargs):
        """Handle the given arguments for a plugin

        This will process the arguments for a given plugin. Additionally, it will construct the plugin object and
        supply the constructed object to the plugin system if the plugin is a selection or is enabled.

        Args:
            args: argparse namespace
        """
        arguments = super().handle_arguments(
            args, **kwargs
        )  # Perform argument checking first
        if not getattr(args, self.disable_flag_destination, False):
            # Remove the disable flag from the arguments
            plugin_arguments = {
                key: value
                for key, value in self.extract_arguments(arguments).items()
                if key != self.disable_flag_destination
            }

            plugin_zero_argument_class = functools.partial(
                self.plugin_class.get_implementor(), **plugin_arguments
            )
            self.plugin_system.add_bound_class(
                self.plugin_class.category, plugin_zero_argument_class
            )
        return arguments

    def get_plugin_class(self):
        """Plugin class accessor"""
        return self.plugin_class


class PluginArgumentParser(ParserBase):
    """Parser for arguments coming from plugins"""

    DESCRIPTION = "Plugin options"
    # Defaults:
    FPRIME_CHOICES = {
        "framing": "space-packet-space-data-link",
        "communication": "ip",
    }

    def __init__(self, plugin_system: Plugins = None):
        """Initialize the plugin information for this parser

        This will initialize this plugin argument parser with the supplied plugin system. If not supplied this will use
        the system plugin singleton, which is configured elsewhere.
        """
        # Accept the supplied plugin system defaulting to the global singleton
        self.plugin_system = plugin_system if plugin_system else Plugins.system()
        self._plugin_map = {
            category: [
                IndividualPluginParser(self.plugin_system, plugin)
                for plugin in self.plugin_system.get_plugins(category)
            ]
            for category in self.plugin_system.get_categories()
        }

    def fill_parser(self, parser):
        """Fill supplied parser with grouped arguments

        Fill the supplied parser with arguments from the `get_arguments` method invocation. This implementation groups
        arguments based on the constituent parser that the argument comes from. Category specific arguments are also
        added (i.e. SELECTION type selection arguments).

        Args:
            parser: parser to fill
        """
        for category, plugin_parsers in self._plugin_map.items():
            # Add category specific flags (selection flags, etc)
            argument_group = parser.add_argument_group(
                title=f"{category.title()} Plugin Options"
            )
            self.add_arguments_from_specification(
                argument_group, self.get_category_arguments(category)
            )

            # Handle the individual plugin parsers
            for plugin_parser in plugin_parsers:
                plugin = plugin_parser.get_plugin_class()
                argument_group = parser.add_argument_group(
                    title=f"{category.title()} Plugin '{plugin.get_name()}' Options"
                )
                plugin_parser.fill_parser(argument_group)

    def get_category_arguments(self, category):
        """Get category arguments for a given plugin category

        This function will generate category arguments for the supplied category. These arguments will follow the
        standard argument specification of a dictionary of flag tuples to argparse keyword arguments.

        Currently category specific arguments are just selection flags for SELECTION type plugins.

        Args:
            category: category arguments
        """
        plugin_type = self.plugin_system.get_category_plugin_type(category)
        plugins = [
            plugin_parser.get_plugin_class()
            for plugin_parser in self._plugin_map[category]
        ]

        arguments: Dict[Tuple[str, ...], Dict[str, Any]] = {}

        # Add category options: SELECTION plugins add a selection flag
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
        """Return arguments to used in plugin system

        This will return the command line arguments all the plugins contained within the supplied plugin system. This
        will recursively return plugins from all of the IndividualPluginParser objects composing this plugin argument
        parser. Arguments are returned in the standard specification form of tuple of flags mapped to a dictionary of
        argparse kwarg inputs.
        """
        arguments: Dict[Tuple[str, ...], Dict[str, Any]] = {}
        for category, plugin_parsers in self._plugin_map.items():
            arguments.update(self.get_category_arguments(category))
            [
                arguments.update(plugin_parser.get_arguments())
                for plugin_parser in plugin_parsers
            ]
        return arguments

    def handle_arguments(self, args, **kwargs):
        """Handle the plugin arguments

        This will handle the plugin arguments delegating each to the IndividualPluginParser. For SELECTION plugins this
        will bind a single instance of the selected plugin to its arguments. For FEATURE plugins it will bind arguments
        to every enabled plugin. Bound plugins are registered with the plugin system.
        """
        for category, plugin_parsers in self._plugin_map.items():
            plugin_type = self.plugin_system.get_category_plugin_type(category)
            self.plugin_system.start_loading(category)
            # Selection plugins choose one plugin and instantiate it
            if plugin_type == PluginType.SELECTION:
                try:
                    self.plugin_system.get_selected_class(category)
                except PluginsNotLoadedException:
                    selection_string = getattr(args, f"{category}_selection")
                    matching_plugin_parsers = [
                        plugin_parser
                        for plugin_parser in plugin_parsers
                        if plugin_parser.get_plugin_class().get_name()
                        == selection_string
                    ]
                    assert (
                        len(matching_plugin_parsers) == 1
                    ), "Plugin selection system failed"
                    args = matching_plugin_parsers[0].handle_arguments(args, **kwargs)
            # Feature plugins instantiate all enabled plugins
            elif plugin_type == PluginType.FEATURE:
                for plugin_parser in plugin_parsers:
                    args = plugin_parser.handle_arguments(args, **kwargs)
        return args


class CompositeParser(ParserBase):
    """Composite parser handles parsing as a composition of multiple other parsers"""

    def __init__(self, constituents, description=None):
        """Construct this parser by instantiating the sub-parsers"""
        self.given = description
        constructed = [
            constituent() if callable(constituent) else constituent
            for constituent in constituents
        ]
        # Check to ensure everything passed in became a ParserBase after construction
        for i, construct in enumerate(constructed):
            assert isinstance(
                construct, ParserBase
            ), f"{construct.__class__.__name__} ({i}) not a ParserBase child"
        flattened = [
            item.constituents if isinstance(item, CompositeParser) else [item]
            for item in constructed
        ]
        self.constituent_parsers = {*itertools.chain.from_iterable(flattened)}

    def fill_parser(self, parser):
        """File supplied parser with grouped arguments

        Fill the supplied parser with arguments from the `get_arguments` method invocation. This implementation groups
        arguments based on the constituent that sources the argument.

        Args:
            parser: parser to fill
        """
        for constituent in sorted(self.constituents, key=lambda x: x.description):
            if isinstance(constituent, (PluginArgumentParser, CompositeParser)):
                constituent.fill_parser(parser)
            else:
                argument_group = parser.add_argument_group(
                    title=constituent.description
                )
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
            ("--log-level-gds",): {
                "action": "store",
                "dest": "log_level_gds",
                "choices": ["DEBUG", "INFO", "WARNING", "ERROR"],
                "default": "INFO",
                "help": "Set the logging level of GDS processes [default: %(default)s]",
            },
            ("--disable-data-logging",): {
                "action": "store_true",
                "default": False,
                "help": "Disable logging of each data item",
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
            args.logs, mirror_to_stdout=args.log_to_stdout, log_level=args.log_level_gds
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
        zmq_arguments = {
            ("--no-zmq",): {
                "dest": "zmq",
                "action": "store_false",
                "help": "Disable ZMQ transportation layer, falling back to TCP socket server.",
                "default": True,
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
                "help": "Set the threaded TCP socket server port when ZMQ is not used [default: %(default)s]",
                "default": 50050,
            },
            ("--tts-addr",): {
                "dest": "tts_addr",
                "action": "store",
                "type": str,
                "help": "Set the threaded TCP socket server address when ZMQ is not used [default: %(default)s]",
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
    """Parser for locating and loading dictionary information

    IMPORTANT: Since this parser loads global configuration that other parsers may depend on
    (only framing plugin at this time), it is recommended to list it first in any CompositeParser
    Not doing so would mean other parsers don't have access to dictionary config at handle_arguments time.

    This parser loads all dictionary elements and make them available for later use.
    It also updates the global ConfigManager with all type and constant definitions found
    in the dictionary.
    """

    DESCRIPTION = "Dictionary options"

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        """Arguments to handle dictionary."""
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
                    "help": "Path to packet XML specification (should not be used if JSON packet definitions are used).",
                },
                ("--packet-set-name",): {
                    "dest": "packet_set_name",
                    "action": "store",
                    "default": None,
                    "required": False,
                    "type": str,
                    "help": "Name of packet set defined in the JSON dictionary.",
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

        # Setup dictionaries encoders and decoders
        dictionaries = Dictionaries()

        dictionaries.load_dictionaries(
            args.dictionary, args.packet_spec, args.packet_set_name
        )
        config = ConfigManager.get_instance()
        # Update config to use type definitions defined in the JSON dictionary
        if dictionaries.typedefs_name:
            for type_name, type_dict in dictionaries.typedefs_name.items():
                config.set_type(type_name, type_dict)
        if dictionaries.constant_name:
            for name, value in dictionaries.constant_name.items():
                config.set_constant(name, value)
        args.dictionaries = dictionaries
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
            "config": ConfigManager.get_instance(),
            "dictionaries": args_ns.dictionaries,
            "file_store": args_ns.files_storage_directory,
            "logging_prefix": args_ns.logs,
            "data_logging_enabled": not args_ns.disable_data_logging,
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
        DictionaryParser,  # needed to get types from dictionary for framing
        CommExtraParser,
        MiddleWareParser,
        LogDeployParser,
    ]

    def __init__(self):
        """Initialization"""
        # Added here to ensure the call to Plugins does not interfere with the full plugin system
        comm_plugin_parser_instance = PluginArgumentParser(
            Plugins(["communication", "framing"])
        )
        super().__init__(
            constituents=self.CONSTITUENTS + [comm_plugin_parser_instance],
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

    DESCRIPTION = "Searching and filtering options"

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
