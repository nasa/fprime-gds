""" fprime_gds.test_plugins:

A set of pytest-enabled tests that are used to test the plugin architecture of the fprime_gds. This file defines a
number of plugins, instantiates a non-singleton plugin instance, and registers the plugins to it. These steps are
provided via the `plugins` fixture to tests.

@author lestarch
"""
import os
import signal
import subprocess
import sys
import time

import pytest

from pathlib import Path
from tempfile import NamedTemporaryFile
from fprime_gds.common.communication.adapters.ip import IpAdapter
from fprime_gds.common.communication.adapters.base import NoneAdapter
from fprime_gds.common.communication.adapters.uart import SerialAdapter
from fprime_gds.common.communication.framing import FramerDeframer, FpFramerDeframer
from fprime_gds.executables.cli import ParserBase, PluginArgumentParser
from fprime_gds.executables.apps import GdsFunction, GdsApp
from fprime_gds.plugin.definitions import gds_plugin_implementation
from fprime_gds.plugin.system import Plugins


class BadSuperClass(object):
    """ A bad framing plugin (inappropriate parent)

    This plugin implementation will fail to register as a "framing" plugin because it does not inherit from
    FramerDeframer.
    """

    @classmethod
    @gds_plugin_implementation
    def register_framing_plugin(cls):
        """ Register a bad plugin """
        return cls


class BadImplementation(FramerDeframer):
    """ A bad framing plugin (inappropriate implementation)

    This plugin implementation will fail to register as a "framing" plugin because it does not implement all abstract
    methods required by the `FramerDeframer` class.
    """

    @classmethod
    @gds_plugin_implementation
    def register_framing_plugin(cls):
        """ Register a bad plugin """
        return cls


class Good(FramerDeframer):
    """ A good framing plugin

    This plugin implementation inherits from the correct class and implements abstract functions. Thus, this plugin will
    register correctly as a "framing" plugin.
    """

    def frame(self, data):
        """ Required function: frame data """
        pass

    def deframe(self, data, no_copy=False):
        """ Required function: deframe data """
        pass

    @classmethod
    @gds_plugin_implementation
    def register_framing_plugin(cls):
        """ Register a good plugin """
        return cls


class GoodWithArgs(Good):
    """ A good framing plugin including arguments

    This plugin implementation is the same "good" implementation with the addition of arguments requested from the
    plugin system. This implementation will take and store these arguments to prove the system.

    Additionally, this plugin implementation defines the `get_name` class method to provide a name for the plugin.
    """
    NAMED_PLUGIN_NAME = "good-with-args"

    def __init__(self, my_fancy_arg, fancy_2):
        """ Fancy argument input processing """
        self.my_fancy_arg = my_fancy_arg
        self.fancy_2 = fancy_2

    @classmethod
    def get_name(cls):
        """ Return the name of this function """
        return cls.NAMED_PLUGIN_NAME

    @classmethod
    def get_arguments(cls):
        """ Return some argument specifications """
        return {
            ("--my-fancy-arg", ): {
                "type": str,
                "help": "Some help string"
            },
            ("--my-fancy-arg-with-dest", ): {
                "dest": "fancy_2",
                "type": int,
                "help": "Some help string"
            },
        }

    @classmethod
    def check_arguments(cls, my_fancy_arg, fancy_2):
        """ Check arguments to raise ValueError """
        if fancy_2 < 0:
            raise ValueError("Must be positive")


class StartFunction(GdsFunction):
    """ A plugin implementation that starts a function

    This plugin implementation creates a start-up function that will run on the invocation of the GDS.
    """
    def __init__(self, start_up_file):
        """ Start-Up function file annotation """
        self.start_up_function_file = start_up_file

    def run(self):
        """ Run function """
        with open(self.start_up_function_file, "a+") as file_handle:
            file_handle.write("ACK\n")

    @classmethod
    def get_name(cls):
        """ Get name """
        return "test-start-function"

    @classmethod
    def get_arguments(cls):
        """ Get arguments """
        return {
            ("--start-up-file", ): {
                "type": str,
                "help": "File to run start-up function on",
                "required": True
            }
        }

    @classmethod
    @gds_plugin_implementation
    def register_gds_function_plugin(cls):
        """ Register a good plugin """
        return cls


class StartApp(GdsApp):
    """ A plugin implementation that starts a app in a separate process

    This plugin implementation creates a start-up application that will run in a separate process
    """
    def __init__(self, start_up_file):
        """ Start-Up function file annotation """
        super().__init__()
        self.start_up_app_file = start_up_file

    def get_process_invocation(self):
        """ Process invocation """
        return [sys.executable, __file__, self.start_up_app_file, "ACK-2"]

    @classmethod
    def get_name(cls):
        """ Get name """
        return "test-start-app"

    @classmethod
    def get_arguments(cls):
        """ Get arguments """
        return {
            ("--start-up-file", ): {
                "type": str,
                "help": "File to run start-up function on",
                "required": True
            }
        }

    @classmethod
    @gds_plugin_implementation
    def register_gds_app_plugin(cls):
        """ Register a good plugin """
        return cls


@pytest.fixture()
def plugins():
    """ Register test plugins as fixture for testing

    Create a `plugins` fixture that is a plugin system created to register specifically the test plugins on top of the
    installed and provided plugins.
    """
    system = Plugins(["communication", "framing"])
    system.register_plugin(BadSuperClass)
    system.register_plugin(BadImplementation)
    system.register_plugin(Good)
    system.register_plugin(GoodWithArgs)
    Plugins._singleton = system
    return system


@pytest.fixture()
def start_up(request):
    """ Register test start up plugins as a fixture for testing

    """
    parent_path = Path(__file__).parent
    extra_plugins, flags = request.param

    command_arguments = ["fprime-gds", "-n", "--dictionary", str( parent_path / "sample" / "dictionary.xml"),
                         "--zmq", "--zmq-transport", "ipc:///tmp/fprime-test-in",  "ipc:///tmp/fprime-test-out",
                         "-g", "none"] + flags

    # Update the environment to side-load python
    environment = os.environ.copy()
    environment[Plugins.PLUGIN_ENVIRONMENT_VARIABLE] = extra_plugins
    environment["PYTHONPATH"] = f"{environment.get('PYTHONPATH', '')}:{parent_path}"
    with NamedTemporaryFile(mode="w+") as temp_file:
        assert "" == temp_file.read(), "Failed to read empty file"
        command_arguments += ["--start-up-file", temp_file.name]
        # Run subprocess for 3 seconds then kill the GDS with 3 seconds to shut down
        process = subprocess.Popen(command_arguments, env=environment)
        time.sleep(3)
        process.send_signal(signal.SIGINT)
        _ = process.communicate(None, 3)
        yield temp_file


def test_base_plugin(plugins):
    """ Tests good framing plugins are returned """
    plugin_options = plugins.get_plugins("framing")
    assert Good in [plugin.plugin_class for plugin in plugin_options], "Good plugin not registered as expected"


def test_framing_builtin_plugins(plugins):
    """ Tests good framing plugins are returned """
    plugin_options = plugins.get_plugins("framing")
    assert FpFramerDeframer in [plugin.plugin_class for plugin in plugin_options], "FpFramerDeframer plugin not registered as expected"


def test_communication_builtin_plugins(plugins):
    """ Tests good framing plugins are returned """
    plugin_options = plugins.get_plugins("communication")
    plugin_classes = [plugin.plugin_class for plugin in plugin_options]
    for expected in [IpAdapter, NoneAdapter, SerialAdapter]:
        assert expected in plugin_classes, f"{expected.__name__} plugin not registered as expected"


def test_plugin_categories(plugins):
    """ Tests plugin categories """
    plugin_categories = plugins.get_categories()
    assert sorted(plugin_categories) == sorted(["communication", "framing"]), "Detected plugin categories incorrect"


def test_plugin_validation(plugins):
    """ Tests good framing plugins are returned """
    plugin_options = plugins.get_plugins("framing")
    plugin_classes = [plugin.plugin_class for plugin in plugin_options]
    assert BadSuperClass not in plugin_classes, "Plugin with bad parent class not excluded as expected"
    assert BadImplementation not in plugin_classes, "Plugin with abstract implementation not excluded as expected"


def test_plugin_arguments(plugins):
    """ Tests that arguments can be parsed and supplied to a plugin """
    a_string = "a_string"
    a_number = "201"
    to_parse = ["--framing", "good-with-args", "--my-fancy-arg", a_string, "--my-fancy-arg-with-dest", a_number]
    args, _ = ParserBase.parse_args([PluginArgumentParser,], arguments=to_parse)
    assert args.framing_selection == GoodWithArgs.NAMED_PLUGIN_NAME, "Improper framing selection"
    assert isinstance(args.framing_selection_instance, GoodWithArgs), "Invalid instance created"
    assert args.framing_selection_instance.my_fancy_arg == a_string, "String argument did not process"
    assert args.framing_selection_instance.fancy_2 == int(a_number), "Integer argument did not process"


def test_plugin_check_arguments(plugins):
    """ Tests that arguments are validated in plugins """
    a_string = "a_string"
    a_number = "-20"
    to_parse = ["--framing", "good-with-args", "--my-fancy-arg", a_string, "--my-fancy-arg-with-dest", a_number]
    with pytest.raises(SystemExit):
        args, _ = ParserBase.parse_args([PluginArgumentParser,], arguments=to_parse)


@pytest.mark.parametrize("start_up", [(f"{__name__}:StartFunction", [])], indirect=True)
def test_start_function(start_up):
    """ Test start-up functions """
    assert "ACK\n" == start_up.read(), "Failed to read expected data"


@pytest.mark.parametrize("start_up", [(f"{__name__}:StartFunction", ["--disable-test-start-function"])], indirect=True)
def test_disabled_start_function(start_up):
    """ Test disabled start-up functions """
    assert "" == start_up.read(), "Failed to read empty file"


@pytest.mark.parametrize("start_up", [(f"{__name__}:StartApp", [])], indirect=True)
def test_start_app(start_up):
    """ Test start-up functions """
    assert "ACK-2\n" == start_up.read(), "Failed to read expected data"


@pytest.mark.parametrize("start_up", [(f"{__name__}:StartApp", ["--disable-test-start-app"])], indirect=True)
def test_disabled_start_app(start_up):
    """ Test disabled start-up functions """
    assert "" == start_up.read(), "Failed to read empty file"


def main():
    """ Run main entry point function

    The main function is run when the file is invoked not as a pytest set of test, but rather when it is run as part of
    the StartApp plugin. This main program writes the second argument to the file represented as the first.
    """
    with open(sys.argv[1], "a+") as file_handle:
        file_handle.write(f"{sys.argv[2]}\n")

if __name__ == "__main__":
    main()
