"""
Unit tests for the YAMCS-backed GDS transport (fprime_gds.common.yamcs_transport)
"""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("yamcs.client")

from fprime_gds.common.models.serialize.bool_type import BoolType
from fprime_gds.common.models.serialize.numerical_types import F64Type, I32Type
from fprime_gds.common.models.serialize.string_type import StringType
from fprime_gds.common.transport import TransportationException
from fprime_gds.common.yamcs_transport import (
    TRANSFER_STATE_COMPLETED,
    TRANSFER_STATE_FAILED,
    YamcsClient,
    YamcsWrapper,
)

StringArgType = StringType.construct_type("StringArgType", max_length=40)


class TestNameMapping:
    def make_wrapper(self, namespace="/MyDeployment"):
        wrapper = YamcsWrapper()
        wrapper.namespace = namespace
        return wrapper

    def test_to_yamcs_param_name(self):
        wrapper = self.make_wrapper()
        assert (
            wrapper.to_yamcs_param_name("Ref.blockDrv.BD_Cycles")
            == "/MyDeployment/Ref/blockDrv/BD_Cycles"
        )

    def test_to_yamcs_cmd_name_matches_param_name(self):
        wrapper = self.make_wrapper()
        name = "Ref.cmdDisp.CMD_NO_OP"
        assert wrapper.to_yamcs_cmd_name(name) == wrapper.to_yamcs_param_name(name)

    def test_to_fprime_name_strips_namespace(self):
        wrapper = self.make_wrapper()
        assert (
            wrapper.to_fprime_name("/MyDeployment/Ref/blockDrv/BD_Cycles")
            == "Ref.blockDrv.BD_Cycles"
        )

    def test_to_fprime_name_no_namespace(self):
        wrapper = self.make_wrapper(namespace="")
        assert wrapper.to_fprime_name("/Ref/blockDrv/BD_Cycles") == "Ref.blockDrv.BD_Cycles"

    def test_roundtrip(self):
        wrapper = self.make_wrapper()
        original = "Ref.sendBuffComp.SendState"
        assert wrapper.to_fprime_name(wrapper.to_yamcs_param_name(original)) == original

    def test_to_yamcs_qualified_arg(self):
        wrapper = self.make_wrapper()
        assert (
            wrapper.to_yamcs_qualified_arg("/MyDeployment/Ref/cmdDisp/CMD_NO_OP_STRING", "arg1")
            == "Ref/cmdDisp/CMD_NO_OP_STRING|arg1"
        )

    def test_disconnect_resets_state(self):
        wrapper = self.make_wrapper()
        wrapper.instance = "instance"
        wrapper.disconnect()
        assert wrapper.namespace == ""
        assert wrapper.instance is None
        assert wrapper.yamcs_client is None
        assert wrapper.subscriptions == []


class TestParseUri:
    def test_plain_host_port(self):
        assert YamcsClient._parse_uri("yamcs://localhost:8090") == "http://localhost:8090"

    def test_no_scheme(self):
        assert YamcsClient._parse_uri("localhost:8090") == "http://localhost:8090"

    def test_secure_scheme(self):
        assert YamcsClient._parse_uri("yamcs+https://yamcs.example.com:443") == (
            "https://yamcs.example.com:443"
        )

    def test_trailing_path_stripped(self):
        assert YamcsClient._parse_uri("yamcs://host:8090/some/path") == "http://host:8090"


class TestBuildValueObject:
    def test_bool_from_string(self):
        obj = YamcsClient._build_value_object("True", BoolType)
        assert obj.val is True
        obj = YamcsClient._build_value_object("false", BoolType)
        assert obj.val is False

    def test_bool_from_number(self):
        assert YamcsClient._build_value_object(1, BoolType).val is True
        assert YamcsClient._build_value_object(0, BoolType).val is False

    def test_integer_from_string(self):
        assert YamcsClient._build_value_object("42", I32Type).val == 42

    def test_float_from_string(self):
        assert YamcsClient._build_value_object("3.5", F64Type).val == 3.5

    def test_string_passthrough(self):
        assert YamcsClient._build_value_object("hello", StringArgType).val == "hello"


class TestBuildEventDataMissingArgs:
    def make_client(self, arg_specs, extra):
        client = YamcsClient.__new__(YamcsClient)
        client.yamcs = YamcsWrapper()
        client._event_by_leaf = {}
        template = MagicMock()
        template.get_args.return_value = arg_specs
        client.dictionaries = MagicMock()
        client.dictionaries.event_name = {"Ref.event": template}
        event = MagicMock()
        event.event_type = "Ref.event"
        event.extra = extra
        event.generation_time = None
        return client, event

    def test_missing_numeric_arg_defaults_to_zero(self):
        client, event = self.make_client([("count", "", I32Type)], {})
        event_data = client._build_event_data(event)
        assert event_data.args[0].val == 0

    def test_missing_string_arg_defaults_to_empty(self):
        client, event = self.make_client([("name", "", StringArgType)], {})
        event_data = client._build_event_data(event)
        assert event_data.args[0].val == ""

    def test_missing_bool_arg_defaults_to_false(self):
        client, event = self.make_client([("flag", "", BoolType)], {})
        event_data = client._build_event_data(event)
        assert event_data.args[0].val is False


def make_transfer_service(states):
    """Build a mock file transfer service whose subscription yields the given states"""
    service = MagicMock()
    subscription = MagicMock()
    transfers = []
    for state in states:
        current = MagicMock()
        current.state = state
        current.failure_reason = "simulated failure"
        transfers.append(current)
    subscription.get_transfer.side_effect = transfers
    service.create_transfer_subscription.return_value = subscription
    return service, subscription


class TestAwaitTransfer:
    def test_completed_transfer_returned(self):
        service, subscription = make_transfer_service([TRANSFER_STATE_COMPLETED])
        transfer = MagicMock()
        transfer.id = "transfer-1"
        result = YamcsClient._await_transfer(service, transfer, timeout=5)
        assert str(result.state) == TRANSFER_STATE_COMPLETED
        subscription.cancel.assert_called_once()

    def test_failed_transfer_raises(self):
        service, subscription = make_transfer_service([TRANSFER_STATE_FAILED])
        transfer = MagicMock()
        transfer.id = "transfer-2"
        with pytest.raises(TransportationException, match="failed"):
            YamcsClient._await_transfer(service, transfer, timeout=5)
        subscription.cancel.assert_called_once()

    def test_timeout_raises(self):
        service, subscription = make_transfer_service([])
        transfer = MagicMock()
        transfer.id = "transfer-3"
        with pytest.raises(TransportationException, match="timed out"):
            YamcsClient._await_transfer(service, transfer, timeout=0)
        subscription.cancel.assert_called_once()


class TestDiscoverInstanceAndProcessor:
    def make_lib_client(self, mocker, instances, processors):
        lib_client = MagicMock()
        lib_client.list_instances.return_value = instances
        lib_client.list_processors.return_value = processors
        mocker.patch(
            "fprime_gds.common.yamcs_transport.YamcsLibClient", return_value=lib_client
        )
        return lib_client

    @staticmethod
    def named(name, state=None):
        obj = MagicMock()
        obj.name = name
        if state is not None:
            obj.state = state
        return obj

    def test_no_running_instances_raises(self, mocker):
        self.make_lib_client(mocker, [self.named("a", "STOPPED")], [])
        with pytest.raises(RuntimeError, match="No running YAMCS instances"):
            YamcsClient._discover_instance_and_processor("http://localhost:8090")

    def test_multiple_running_instances_raises(self, mocker):
        instances = [self.named("a", "RUNNING"), self.named("b", "RUNNING")]
        self.make_lib_client(mocker, instances, [])
        with pytest.raises(RuntimeError, match="Multiple running YAMCS instances"):
            YamcsClient._discover_instance_and_processor("http://localhost:8090")

    def test_no_processors_raises(self, mocker):
        self.make_lib_client(mocker, [self.named("a", "RUNNING")], [])
        with pytest.raises(RuntimeError, match="No processors found"):
            YamcsClient._discover_instance_and_processor("http://localhost:8090")

    def test_prefers_realtime_processor(self, mocker):
        processors = [self.named("replay"), self.named("realtime")]
        self.make_lib_client(mocker, [self.named("a", "RUNNING")], processors)
        instance, processor = YamcsClient._discover_instance_and_processor(
            "http://localhost:8090"
        )
        assert instance == "a"
        assert processor == "realtime"

    def test_falls_back_to_first_processor(self, mocker):
        processors = [self.named("replay")]
        self.make_lib_client(mocker, [self.named("a", "RUNNING")], processors)
        _, processor = YamcsClient._discover_instance_and_processor("http://localhost:8090")
        assert processor == "replay"
