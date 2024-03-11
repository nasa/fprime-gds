import pytest
from fprime_gds.common.communication.adapters.ip import IpAdapter
from fprime_gds.common.communication.adapters.base import NoneAdapter
from fprime_gds.common.communication.adapters.uart import SerialAdapter
from fprime_gds.common.communication.framing import FramerDeframer, FpFramerDeframer
from fprime_gds.executables.cli import ParserBase, PluginArgumentParser
from fprime_gds.plugin.definitions import gds_plugin_implementation
from fprime_gds.plugin.system import Plugins


class BadSuperClass(object):
    """ A bad framing plugin (inappropriate parent) """

    @classmethod
    @gds_plugin_implementation
    def register_framing_plugin(cls):
        """ Register a bad plugin """
        return cls


class BadImplementation(FramerDeframer):
    """ A bad framing plugin (inappropriate parent) """

    @classmethod
    @gds_plugin_implementation
    def register_framing_plugin(cls):
        """ Register a bad plugin """
        return cls


class Good(FramerDeframer):
    """ A good framing plugin """

    def frame(self, data):
        pass

    def deframe(self, data, no_copy=False):
        pass

    @classmethod
    @gds_plugin_implementation
    def register_framing_plugin(cls):
        """ Register a bad plugin """
        return cls


class GoodWithArgs(FramerDeframer):
    """ A good framing plugin """
    NAMED_PLUGIN_NAME = "good-with-args"

    def __init__(self, my_fancy_arg, fancy_2):
        """ Fancy argument input processing """
        self.my_fancy_arg = my_fancy_arg
        self.fancy_2 = fancy_2

    def frame(self, data):
        pass

    def deframe(self, data, no_copy=False):
        pass

    @classmethod
    def get_name(cls):
        """ Return the name of this function """
        return cls.NAMED_PLUGIN_NAME

    @classmethod
    def get_arguments(cls):
        """ Return the name of this function """
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
    @gds_plugin_implementation
    def register_framing_plugin(cls):
        """ Register a bad plugin """
        return cls


@pytest.fixture()
def plugins():
    """ Register test plugins as fixture for testing """
    system = Plugins()
    system.register_plugin(BadSuperClass)
    system.register_plugin(BadImplementation)
    system.register_plugin(Good)
    system.register_plugin(GoodWithArgs)
    Plugins._singleton = system
    return system


def test_base_plugin(plugins):
    """ Tests good framing plugins are returned """
    plugin_options = plugins.get_selections("framing")
    assert Good in plugin_options, "Good plugin not registered as expected"


def test_framing_builtin_plugins(plugins):
    """ Tests good framing plugins are returned """
    plugin_options = plugins.get_selections("framing")
    assert FpFramerDeframer in plugin_options, "FpFramerDeframer plugin not registered as expected"


def test_communication_builtin_plugins(plugins):
    """ Tests good framing plugins are returned """
    plugin_options = plugins.get_selections("communication")
    for expected in [IpAdapter, NoneAdapter, SerialAdapter]:
        assert expected in plugin_options, f"{expected.__name__} plugin not registered as expected"


def test_plugin_categories(plugins):
    """ Tests plugin categories """
    plugin_categories = plugins.get_categories()
    assert sorted(plugin_categories) == sorted(["communication", "framing"]), "Detected plugin categories incorrect"


def test_plugin_validation(plugins):
    """ Tests good framing plugins are returned """
    plugin_options = plugins.get_selections("framing")
    assert BadSuperClass not in plugin_options, "Plugin with bad parent class not excluded as expected"
    assert BadImplementation not in plugin_options, "Plugin with abstract implementation not excluded as expected"


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
