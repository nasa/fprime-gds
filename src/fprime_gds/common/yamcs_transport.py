""" fprime_gds.common.yamcs_transport:

A transport implementation backed by a YAMCS server. YAMCS exposes telemetry parameters and events over a WebSocket
push subscription, so this transport does not run a recv-poll loop. Instead, on connect it subscribes to YAMCS streams
and dispatches incoming data directly to the channel and event decoders' registrants as ChData/EventData objects,
bypassing the binary encode/decode round-trip used by the standard TCP path.

@author yuktiv
"""

import datetime
import logging

from yamcs.client import YamcsClient as YamcsLibClient

from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.data_types.event_data import EventData
from fprime_gds.common.models.serialize.numerical_types import (
    FloatType,
    IntegerType,
    U32Type,
)
from fprime_gds.common.models.serialize.bool_type import BoolType
from fprime_gds.common.models.serialize.string_type import StringType
from fprime_gds.common.models.serialize.time_type import TimeType
from fprime_gds.common.transport import TransportClient
from fprime_gds.common.utils.config_manager import ConfigManager

LOGGER = logging.getLogger("transport")

YAMCS_URI_SCHEME = "yamcs://"
COMMAND_DESCRIPTOR_VAL = 0x5A5A5A5A


class YamcsWrapper:
    """Handler for YAMCS API calls for use in other objects

    Encapsulates the yamcs-client library so the rest of this module deals with simple method calls. Configuration is
    separated from connection so the client object can be created on the same thread that will use it.
    """

    def __init__(self):
        """Initialize the YAMCS handles"""
        super().__init__()
        self.yamcs_client = None
        self.processor = None
        self.subscriptions = []
        self.yamcs_url = None
        self.instance = None
        self.processor_name = None

    def configure(self, yamcs_url, instance, processor_name):
        """Configure the YAMCS wrapper

        Configures the wrapper but does not connect. Separated so the wrapper can be set up before the connection
        thread exists.

        Args:
            yamcs_url: URL of the YAMCS server (e.g. 'http://localhost:8090')
            instance: YAMCS instance name
            processor_name: YAMCS processor name (typically 'realtime')
        """
        self.yamcs_url = yamcs_url
        self.instance = instance
        self.processor_name = processor_name

    def connect(self):
        """Create the YAMCS client and processor handles"""
        assert self.yamcs_url is not None, "Must configure before connecting"
        assert self.instance is not None, "Must configure before connecting"
        assert self.processor_name is not None, "Must configure before connecting"
        assert self.yamcs_client is None, "Cannot connect multiple times"
        LOGGER.info(
            "Connecting to YAMCS: %s, instance=%s, processor=%s",
            self.yamcs_url,
            self.instance,
            self.processor_name,
        )
        self.yamcs_client = YamcsLibClient(self.yamcs_url)
        self.processor = self.yamcs_client.get_processor(
            instance=self.instance, processor=self.processor_name
        )

    def subscribe(self, parameter_names, on_parameter_callback, on_event_callback):
        """Subscribe to YAMCS parameter and event streams

        Args:
            parameter_names: list of fully-qualified YAMCS parameter names
            on_parameter_callback: callback for parameter updates
            on_event_callback: callback for event updates
        """
        assert self.processor is not None, "Must connect before subscribing"
        if parameter_names:
            LOGGER.info("Subscribing to %d YAMCS parameters", len(parameter_names))
            self.subscriptions.append(
                self.processor.create_parameter_subscription(
                    parameters=parameter_names, on_data=on_parameter_callback
                )
            )
        LOGGER.info("Subscribing to YAMCS event stream")
        assert self.yamcs_client is not None, "Must connect before subscribing"
        assert self.instance is not None, "Must configure before subscribing"
        self.subscriptions.append(
            self.yamcs_client.create_event_subscription(
                instance=self.instance, on_data=on_event_callback
            )
        )

    def disconnect(self):
        """Cancel all subscriptions and drop the YAMCS client handles"""
        for subscription in self.subscriptions:
            try:
                subscription.cancel()
            except Exception as exc:
                LOGGER.warning("Error canceling subscription: %s", exc)
        self.subscriptions.clear()
        self.yamcs_client = None
        self.processor = None

    def list_parameter_qualified_names(self):
        """Return the qualified names of all parameters in the connected instance's MDB"""
        assert self.yamcs_client is not None, "Must connect before listing parameters"
        assert self.instance is not None, "Must configure before listing parameters"
        mdb = self.yamcs_client.get_mdb(instance=self.instance)
        return [param.qualified_name for param in mdb.list_parameters()]

    def issue_command(self, cmd_name, cmd_args):
        """Issue a command to the YAMCS processor

        Args:
            cmd_name: fully-qualified XTCE command name (slash-separated, namespace-prefixed)
            cmd_args: command arguments as a dict
        Returns:
            the IssuedCommand object returned by yamcs-client
        """
        assert self.processor is not None, "Must connect before sending commands"
        return self.processor.issue_command(command=cmd_name, args=cmd_args)


class YamcsClient(TransportClient):
    """YAMCS-backed implementation of the GDS transport interface

    Inherits TransportClient (not ThreadedTransportClient) because YAMCS pushes data via WebSocket callbacks; there is
    no poll loop to run. Incoming data is constructed directly as ChData/EventData and dispatched through the channel
    and event decoders' registrants. Outgoing commands are decoded from the F Prime binary form produced by CmdEncoder
    and re-issued via the YAMCS REST API.

    The transport requires a few references from the pipeline (dictionaries, decoders) which are not available through
    the TransportClient interface; the standard pipeline supplies them via set_pipeline_references after coders are
    set up.
    """

    def __init__(self):
        """Set up the wrapper and clear pipeline references"""
        super().__init__()
        self.yamcs = YamcsWrapper()
        self.dictionaries = None
        self.channel_decoder = None
        self.event_decoder = None
        self.yamcs_namespace = ""

    def set_pipeline_references(self, dictionaries, channel_decoder, event_decoder):
        """Receive the dictionary and decoder references this transport needs to operate

        Called by StandardPipeline.setup after coders are constructed. The transport bypasses the binary decode path,
        so it needs the loaded Dictionaries object to look up templates and the decoder objects to dispatch through.

        Args:
            dictionaries: loaded Dictionaries with channel_name, event_name, and command_id maps
            channel_decoder: ChDecoder whose registrants will receive ChData
            event_decoder: EventDecoder whose registrants will receive EventData
        """
        self.dictionaries = dictionaries
        self.channel_decoder = channel_decoder
        self.event_decoder = event_decoder

    def connect(self, transport_url, sub_routing=None, pub_routing=None):
        """Connect to YAMCS and start subscriptions

        Args:
            transport_url: yamcs://host:port/instance/processor
            sub_routing: ignored (TransportClient compatibility)
            pub_routing: ignored (TransportClient compatibility)
        """
        yamcs_url, instance, processor_name = self._parse_uri(transport_url)
        self.yamcs.configure(yamcs_url, instance, processor_name)
        self.yamcs.connect()
        self.yamcs_namespace = self._discover_yamcs_namespace()
        self.yamcs.subscribe(
            parameter_names=self._build_parameter_list(),
            on_parameter_callback=self._on_parameter_data,
            on_event_callback=self._on_event_data,
        )

    def disconnect(self):
        """Disconnect from YAMCS"""
        self.yamcs.disconnect()

    def send(self, data):
        """Send an outbound packet to YAMCS

        Both CmdEncoder and FileEncoder register with this transport, so this method receives both command and file
        uplink packets. They share the same 0x5A5A5A5A descriptor and are distinguished by the APID field. Only
        commands are supported today; file uplink would need a YAMCS file transfer integration that this MVP does
        not provide.

        Args:
            data: serialized packet bytes from CmdEncoder or FileEncoder
        """
        apid = self._peek_packet_apid(data)
        if apid == "FW_PACKET_COMMAND":
            self._send_command(data)
        elif apid == "FW_PACKET_FILE":
            LOGGER.error("File uplink is not supported by the YAMCS transport; dropping packet")
        else:
            LOGGER.warning("Unrecognized outbound packet APID %s; dropping", apid)

    def _send_command(self, data):
        """Decode an F Prime command packet and issue it to YAMCS"""
        cmd_name, cmd_args = self._decode_fprime_command(data)
        if cmd_name is None:
            LOGGER.warning("Could not decode command from binary packet")
            return
        yamcs_cmd_name = self.yamcs_namespace + "/" + cmd_name.replace(".", "/")
        try:
            issued = self.yamcs.issue_command(yamcs_cmd_name, cmd_args)
            LOGGER.info("Command issued to YAMCS: %s id=%s", yamcs_cmd_name, getattr(issued, "id", None))
        except Exception as exc:
            LOGGER.error("YAMCS rejected command %s: %s", yamcs_cmd_name, exc)

    @staticmethod
    def _peek_packet_apid(data):
        """Read the APID name out of an outbound packet without consuming it

        The packet layout is U32(0x5A5A5A5A) | msg_len | ComCfg.Apid | ...; this reads enough to extract the APID
        and returns its enumeration name (e.g. 'FW_PACKET_COMMAND'), or None if the descriptor is wrong.
        """
        offset = 0
        desc_obj = U32Type()
        desc_obj.deserialize(data, offset)
        offset += desc_obj.getSize()
        if desc_obj.val != COMMAND_DESCRIPTOR_VAL:
            return None
        len_obj = ConfigManager().get_config("msg_len")()
        len_obj.deserialize(data, offset)
        offset += len_obj.getSize()
        apid_obj = ConfigManager().get_type("ComCfg.Apid")()
        apid_obj.deserialize(data, offset)
        return apid_obj.val

    def recv(self, timeout=None):
        """Required by the TransportClient ABC; YAMCS uses callbacks so this is never invoked"""
        return b""

    @staticmethod
    def _parse_uri(transport_url):
        """Parse a yamcs:// URI into (yamcs_url, instance, processor_name)"""
        if transport_url.startswith(YAMCS_URI_SCHEME):
            transport_url = transport_url[len(YAMCS_URI_SCHEME):]
        parts = transport_url.split("/")
        if len(parts) < 2:
            raise ValueError(
                "Invalid YAMCS URI. Expected yamcs://host:port/instance/processor, got: %s" % transport_url
            )
        yamcs_url = "http://" + parts[0]
        instance = parts[1]
        processor_name = parts[2] if len(parts) > 2 else "realtime"
        return yamcs_url, instance, processor_name

    def _discover_yamcs_namespace(self):
        """Return the namespace prefix YAMCS uses for parameters in this instance

        F Prime dictionaries use unprefixed dot-separated names ('CdhCore.cmdDisp.CommandsDispatched') but YAMCS
        namespaces them under the deployment name ('/FprimeYamcsReference_YamcsDeployment/CdhCore/cmdDisp/...'). The
        prefix is taken from the first parameter returned by the MDB. Returns '' if discovery fails so subscriptions
        and commands degrade to unprefixed names.
        """
        try:
            for qualified_name in self.yamcs.list_parameter_qualified_names():
                parts = qualified_name.split("/")
                if len(parts) >= 3:
                    namespace = "/" + parts[1]
                    LOGGER.info("Discovered YAMCS namespace: %s", namespace)
                    return namespace
                break
        except Exception as exc:
            LOGGER.warning("Could not discover YAMCS namespace: %s", exc)
        return ""

    def _build_parameter_list(self):
        """Build the list of YAMCS parameter names from the F Prime channel dictionary"""
        if self.dictionaries is None or not getattr(self.dictionaries, "channel_name", None):
            LOGGER.warning("No channel dictionary available; subscribing to no parameters")
            return []
        return [
            self.yamcs_namespace + "/" + name.replace(".", "/")
            for name in self.dictionaries.channel_name.keys()
        ]

    def _on_parameter_data(self, parameter_data):
        """WebSocket callback for parameter updates

        Constructs ChData objects and dispatches them through the channel decoder's registrants. Exceptions are caught
        per-parameter so a single bad sample does not kill the WebSocket thread.
        """
        for param_value in parameter_data.parameters:
            try:
                ch_data = self._build_ch_data(param_value)
                if ch_data is not None and self.channel_decoder is not None:
                    self.channel_decoder.send_to_all(ch_data)
            except Exception as exc:
                LOGGER.error("Error processing parameter %s: %s", param_value.name, exc)

    def _on_event_data(self, event):
        """WebSocket callback for event updates

        Constructs an EventData and dispatches it through the event decoder's registrants. Exceptions are caught so a
        single bad event does not kill the WebSocket thread.
        """
        try:
            event_data = self._build_event_data(event)
            if event_data is not None and self.event_decoder is not None:
                self.event_decoder.send_to_all(event_data)
        except Exception as exc:
            LOGGER.error("Error processing event %s: %s", event.event_type, exc)

    def _build_ch_data(self, param_value):
        """Build a ChData object from a YAMCS ParameterValue

        Returns None if the parameter is not in the F Prime dictionary or has no readable value. Prefers the
        engineering value when available; falls back to the raw value otherwise.
        """
        channel_dict = getattr(self.dictionaries, "channel_name", None)
        if channel_dict is None:
            LOGGER.warning("No channel dictionary available; cannot resolve parameter %s", param_value.name)
            return None
        template = self._lookup_template_by_yamcs_name(param_value.name, channel_dict)
        if template is None:
            LOGGER.warning("Unknown parameter in F Prime dictionary: %s", param_value.name)
            return None
        value = getattr(param_value, "eng_value", None)
        if value is None:
            value = getattr(param_value, "raw_value", None)
        if value is None:
            LOGGER.warning("Parameter %s has no value", param_value.name)
            return None
        val_obj = self._build_value_object(value, template.get_type_obj())
        ch_time = self._build_time_type(param_value.generation_time)
        return ChData(val_obj, ch_time, template)

    def _build_event_data(self, event):
        """Build an EventData object from a YAMCS Event

        The fprime-yamcs event processor publishes the F Prime arg names directly into the YAMCS event 'extra' dict,
        so a direct key lookup matches.
        """
        event_dict = getattr(self.dictionaries, "event_name", None)
        if event_dict is None:
            LOGGER.warning("No event dictionary available; cannot resolve event %s", event.event_type)
            return None
        template = self._lookup_template_by_yamcs_name(event.event_type, event_dict)
        if template is None:
            LOGGER.warning("Unknown event in F Prime dictionary: %s", event.event_type)
            return None
        extra = getattr(event, "extra", None) or {}
        arg_objs = []
        for arg_spec in template.get_args():
            arg_name, _arg_desc, arg_type = arg_spec[0], arg_spec[1], arg_spec[2]
            arg_objs.append(self._build_value_object(extra.get(arg_name), arg_type))
        event_time = self._build_time_type(event.generation_time)
        return EventData(tuple(arg_objs), event_time, template)

    @staticmethod
    def _build_value_object(value, type_class):
        """Wrap a Python value in an F Prime type object so consumers can read it via .val

        YAMCS event 'extra' values arrive as strings (the YAMCS API requires Mapping[str, str]). F Prime numerical
        types validate the assigned type strictly, so this coerces strings to the type the F Prime template expects
        before assignment.
        """
        obj = type_class()
        if isinstance(value, str) and not isinstance(obj, StringType):
            if isinstance(obj, IntegerType):
                value = int(value)
            elif isinstance(obj, FloatType):
                value = float(value)
            elif isinstance(obj, BoolType):
                value = value.lower() in ("true", "1", "yes")
        obj.val = value
        return obj

    @staticmethod
    def _build_time_type(yamcs_timestamp):
        """Convert a YAMCS timestamp to an F Prime TimeType

        For parameters and events sourced from the FSW, generation_time carries the FSW packet time (see
        yamcs.client.tmtc.model.ParameterValue.generation_time). The original F Prime TimeBase enum value is not
        preserved through YAMCS extraction, so this stamps the result as TB_WORKSTATION_TIME. The seconds and
        microseconds are accurate; only the time-base label is approximate.

        TimeType.set_datetime subtracts a naive epoch internally, so the input must be naive. YAMCS returns tz-aware
        UTC datetimes; convert to UTC and strip tzinfo before handing off.
        """
        if yamcs_timestamp is None:
            return TimeType()
        if isinstance(yamcs_timestamp, str):
            yamcs_timestamp = datetime.datetime.fromisoformat(yamcs_timestamp.replace("Z", "+00:00"))
        if yamcs_timestamp.tzinfo is not None:
            yamcs_timestamp = yamcs_timestamp.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        time_obj = TimeType()
        time_obj.set_datetime(yamcs_timestamp, TimeType.TimeBase("TB_WORKSTATION_TIME"))
        return time_obj

    @staticmethod
    def _lookup_template_by_yamcs_name(yamcs_name, fprime_dict):
        """Resolve a slash-separated YAMCS qualified name to an F Prime template

        Channels arrive fully qualified (e.g. '/Deployment/Comp/Inst/Chan'); progressively shorter prefixes of the
        name are tried, stripping one leading namespace component at a time, until a match is found in the F Prime
        dictionary's dot-separated keys. Events arrive with only the leaf name (e.g. 'OpCodeDispatched') because
        YAMCS does not namespace event types, so the leaf is also matched against the suffix of dictionary entries.
        Suffix matching only succeeds when exactly one candidate is found; ambiguous matches return None.
        """
        parts = yamcs_name.lstrip("/").split("/")
        for start in range(len(parts)):
            candidate = ".".join(parts[start:])
            if candidate in fprime_dict:
                return fprime_dict[candidate]
        leaf = parts[-1]
        suffix_matches = [tmpl for name, tmpl in fprime_dict.items() if name.split(".")[-1] == leaf]
        if len(suffix_matches) == 1:
            return suffix_matches[0]
        if len(suffix_matches) > 1:
            LOGGER.warning(
                "Ambiguous YAMCS name %s matches %d F Prime entries by leaf name; not resolving",
                yamcs_name, len(suffix_matches),
            )
        return None

    def _decode_fprime_command(self, binary_data):
        """Reverse CmdEncoder.encode_api to extract (command_name, args_dict)

        The encoder produces (see fprime_gds.common.encoders.cmd_encoder):
            U32(0x5A5A5A5A) | msg_len | ComCfg.Apid | FwOpcodeType | args...

        Length and APID widths come from ConfigManager and may differ across configurations, so this uses the same
        type objects the encoder used rather than fixed offsets.
        """
        if self.dictionaries is None:
            LOGGER.warning("No dictionaries available for command decoding")
            return None, None
        try:
            offset = 0
            desc_obj = U32Type()
            desc_obj.deserialize(binary_data, offset)
            offset += desc_obj.getSize()
            if desc_obj.val != COMMAND_DESCRIPTOR_VAL:
                desc_val = hex(desc_obj.val) if isinstance(desc_obj.val, int) else str(desc_obj.val)
                LOGGER.warning("Invalid command descriptor: %s", desc_val)
                return None, None
            len_obj = ConfigManager().get_config("msg_len")()
            len_obj.deserialize(binary_data, offset)
            offset += len_obj.getSize()
            apid_obj = ConfigManager().get_type("ComCfg.Apid")()
            apid_obj.deserialize(binary_data, offset)
            offset += apid_obj.getSize()
            opcode_obj = ConfigManager().get_type("FwOpcodeType")()
            opcode_obj.deserialize(binary_data, offset)
            offset += opcode_obj.getSize()
            cmd_template = self._lookup_command_by_opcode(opcode_obj.val)
            if cmd_template is None:
                opcode_val = hex(opcode_obj.val) if isinstance(opcode_obj.val, int) else str(opcode_obj.val)
                LOGGER.warning("Unknown opcode: %s", opcode_val)
                return None, None
            args_dict = {}
            for arg_spec in cmd_template.get_args():
                arg_name, _arg_desc, arg_type = arg_spec[0], arg_spec[1], arg_spec[2]
                arg_obj = arg_type()
                arg_obj.deserialize(binary_data, offset)
                args_dict[arg_name] = arg_obj.val
                offset += arg_obj.getSize()
            return cmd_template.get_full_name(), args_dict
        except Exception as exc:
            LOGGER.error("Error decoding F Prime command: %s", exc, exc_info=True)
            return None, None

    def _lookup_command_by_opcode(self, opcode):
        """Find the command template whose opcode matches"""
        if self.dictionaries is None:
            return None
        command_id_map = getattr(self.dictionaries, "command_id", None)
        if not command_id_map:
            return None
        for tmpl in command_id_map.values():
            if tmpl.get_op_code() == opcode:
                return tmpl
        return None
