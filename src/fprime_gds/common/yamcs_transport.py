"""fprime_gds.common.yamcs_transport

YAMCS-backed transport for the F Prime GDS. Subscribes to YAMCS WebSocket
streams for telemetry and events, issues commands via the YAMCS REST API,
and routes file uplink/downlink through YAMCS's FileTransferService.

@author yuktiv
"""

import datetime
import logging
import time

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
FILE_TRANSFER_POLL_INTERVAL = 2
FILE_TRANSFER_SERVICE_NAME = "FprimeFilePacketService"
FILE_TRANSFER_BUCKET = "fprimeFilesIn"


class YamcsWrapper:
    """Low-level handle to the yamcs-client library.

    Separates configuration from connection so the wrapper can be set up
    before the thread that will use it exists.
    """

    def __init__(self):
        super().__init__()
        self.yamcs_client = None
        self.processor = None
        self.subscriptions = []
        self.yamcs_url = None
        self.instance = None
        self.processor_name = None

    def configure(self, yamcs_url, instance, processor_name):
        """Store connection parameters without connecting."""
        self.yamcs_url = yamcs_url
        self.instance = instance
        self.processor_name = processor_name

    def connect(self):
        """Create the YAMCS client and processor handles."""
        assert self.yamcs_url is not None, "Must configure before connecting"
        assert self.yamcs_client is None, "Cannot connect multiple times"
        LOGGER.info(
            "Connecting to YAMCS: %s, instance=%s, processor=%s",
            self.yamcs_url, self.instance, self.processor_name,
        )
        self.yamcs_client = YamcsLibClient(self.yamcs_url)
        self.processor = self.yamcs_client.get_processor(
            instance=self.instance, processor=self.processor_name
        )

    def subscribe(self, parameter_names, on_parameter_callback, on_event_callback):
        """Subscribe to YAMCS parameter and event WebSocket streams."""
        assert self.processor is not None, "Must connect before subscribing"
        if parameter_names:
            LOGGER.info("Subscribing to %d YAMCS parameters", len(parameter_names))
            self.subscriptions.append(
                self.processor.create_parameter_subscription(
                    parameters=parameter_names, on_data=on_parameter_callback
                )
            )
        LOGGER.info("Subscribing to YAMCS event stream")
        self.subscriptions.append(
            self.yamcs_client.create_event_subscription(
                instance=self.instance, on_data=on_event_callback
            )
        )

    def disconnect(self):
        """Cancel all subscriptions and release handles."""
        for subscription in self.subscriptions:
            try:
                subscription.cancel()
            except Exception as exc:
                LOGGER.warning("Error canceling subscription: %s", exc)
        self.subscriptions.clear()
        self.yamcs_client = None
        self.processor = None

    def list_parameter_qualified_names(self):
        """Return all MDB parameter qualified names for the connected instance."""
        mdb = self.yamcs_client.get_mdb(instance=self.instance)
        return [param.qualified_name for param in mdb.list_parameters()]

    def issue_command(self, cmd_name, cmd_args):
        """Issue a command through the YAMCS processor."""
        assert self.processor is not None, "Must connect before sending commands"
        return self.processor.issue_command(command=cmd_name, args=cmd_args)

    def get_file_transfer_service(self, service_name=FILE_TRANSFER_SERVICE_NAME):
        """Return a handle to the named YAMCS FileTransferService."""
        ft_client = self.yamcs_client.get_file_transfer_client(instance=self.instance)
        return ft_client.get_service(service_name)

    def get_storage_client(self):
        """Return a YAMCS storage client for bucket operations."""
        return self.yamcs_client.get_storage_client()


class YamcsClient(TransportClient):
    """YAMCS-backed GDS transport.

    Pushes telemetry and events via WebSocket callbacks (no poll loop).
    Commands are decoded from the F Prime binary form and re-issued via
    the YAMCS REST API.  File uplink/downlink is routed through YAMCS's
    FileTransferService (FprimeFilePacketService on the Java side).
    """

    def __init__(self):
        super().__init__()
        self.yamcs = YamcsWrapper()
        self.dictionaries = None
        self.channel_decoder = None
        self.event_decoder = None
        self.yamcs_namespace = ""

    # ------------------------------------------------------------------
    # Pipeline integration
    # ------------------------------------------------------------------

    def set_pipeline_references(self, dictionaries, channel_decoder, event_decoder):
        """Receive dictionary and decoder references from StandardPipeline.

        Called after coders are constructed so this transport can bypass the
        binary decode path and dispatch ChData/EventData directly.
        """
        self.dictionaries = dictionaries
        self.channel_decoder = channel_decoder
        self.event_decoder = event_decoder

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self, transport_url, sub_routing=None, pub_routing=None):
        """Connect to YAMCS, auto-discover instance/processor, and subscribe."""
        yamcs_url = self._parse_uri(transport_url)
        instance, processor_name = self._discover_instance_and_processor(yamcs_url)
        self.yamcs.configure(yamcs_url, instance, processor_name)
        self.yamcs.connect()
        self.yamcs_namespace = self._discover_yamcs_namespace()
        self.yamcs.subscribe(
            parameter_names=self._build_parameter_list(),
            on_parameter_callback=self._on_parameter_data,
            on_event_callback=self._on_event_data,
        )

    def disconnect(self):
        """Disconnect from YAMCS and cancel all subscriptions."""
        self.yamcs.disconnect()

    def recv(self, timeout=None):
        """No-op — YAMCS uses push callbacks, not polling."""
        return b""

    # ------------------------------------------------------------------
    # Outbound packet routing
    # ------------------------------------------------------------------

    def send(self, data):
        """Route an outbound F Prime packet to the appropriate YAMCS API.

        CmdEncoder and FileEncoder both register with this transport.
        Packets are distinguished by the ComCfg.Apid field after the
        0x5A5A5A5A descriptor.
        """
        apid = self._peek_packet_apid(data)
        if apid == "FW_PACKET_COMMAND":
            self._send_command(data)
        elif apid == "FW_PACKET_FILE":
            LOGGER.debug("File packet received; file transfer is handled via YAMCS FileTransferService")
        else:
            LOGGER.warning("Unrecognized outbound packet APID %s; dropping", apid)

    def _send_command(self, data):
        """Decode an F Prime command binary and issue it to YAMCS."""
        cmd_name, cmd_args = self._decode_fprime_command(data)
        if cmd_name is None:
            LOGGER.warning("Could not decode command from binary packet")
            return
        yamcs_cmd_name = self.yamcs_namespace + "/" + cmd_name.replace(".", "/")
        try:
            issued = self.yamcs.issue_command(yamcs_cmd_name, cmd_args)
            LOGGER.info("Command issued: %s id=%s", yamcs_cmd_name, getattr(issued, "id", None))
        except Exception as exc:
            LOGGER.error("YAMCS rejected command %s: %s", yamcs_cmd_name, exc)

    # ------------------------------------------------------------------
    # File transfer
    # ------------------------------------------------------------------

    def upload_file(self, local_path, remote_path, bucket_name=FILE_TRANSFER_BUCKET,
                    service_name=FILE_TRANSFER_SERVICE_NAME, timeout=60):
        """Upload a local file to the spacecraft through YAMCS FileTransferService.

        Uploads the file into a YAMCS bucket, then triggers startUpload on the
        FprimeFilePacketService which breaks it into Fw::FilePacket frames and
        sends them to F Prime over the TC link.

        Args:
            local_path: path to the local file to upload
            remote_path: destination path on the spacecraft
            bucket_name: YAMCS bucket to stage the file in
            service_name: name of the YAMCS FileTransferService
            timeout: max seconds to wait for the transfer to complete
        """
        storage = self.yamcs.get_storage_client()
        object_name = local_path.split("/")[-1] if "/" in local_path else local_path

        with open(local_path, "rb") as f:
            storage.upload_object(
                instance=self.yamcs.instance,
                bucket_name=bucket_name,
                object_name=object_name,
                file_obj=f,
            )
        LOGGER.info("Staged %s in bucket %s as %s", local_path, bucket_name, object_name)

        ft_service = self.yamcs.get_file_transfer_service(service_name)
        transfer = ft_service.upload(
            bucket_name=bucket_name,
            object_name=object_name,
            remote_path=remote_path,
        )
        LOGGER.info("Upload transfer started: id=%s", transfer.id)
        return self._await_transfer(ft_service, transfer, timeout)

    def download_file(self, remote_path, bucket_name=FILE_TRANSFER_BUCKET,
                      object_name=None, service_name=FILE_TRANSFER_SERVICE_NAME,
                      timeout=60):
        """Download a file from the spacecraft through YAMCS FileTransferService.

        Triggers startDownload on the FprimeFilePacketService which sends a
        FileDownlink.SendFile command to F Prime. F Prime streams Fw::FilePacket
        frames back; YAMCS reassembles and deposits them in the bucket.

        Args:
            remote_path: path on the spacecraft to download
            bucket_name: YAMCS bucket to receive the file
            object_name: name for the file in the bucket (defaults to basename)
            service_name: name of the YAMCS FileTransferService
            timeout: max seconds to wait for the transfer to complete
        """
        if object_name is None:
            object_name = remote_path.split("/")[-1] if "/" in remote_path else remote_path

        ft_service = self.yamcs.get_file_transfer_service(service_name)
        transfer = ft_service.download(
            bucket_name=bucket_name,
            remote_path=remote_path,
            object_name=object_name,
        )
        LOGGER.info("Download transfer started: id=%s remote=%s", transfer.id, remote_path)
        return self._await_transfer(ft_service, transfer, timeout)

    @staticmethod
    def _await_transfer(ft_service, transfer, timeout):
        """Poll a YAMCS transfer until it reaches a terminal state."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            transfers = list(ft_service.list_transfers())
            current = None
            for t in transfers:
                if t.id == transfer.id:
                    current = t
                    break
            if current is None:
                LOGGER.warning("Transfer %s disappeared from YAMCS", transfer.id)
                return transfer
            state = str(current.state)
            if "COMPLETED" in state:
                LOGGER.info("Transfer %s completed", transfer.id)
                return current
            if "FAILED" in state:
                LOGGER.error("Transfer %s failed", transfer.id)
                return current
            time.sleep(FILE_TRANSFER_POLL_INTERVAL)
        LOGGER.warning("Transfer %s timed out after %ds", transfer.id, timeout)
        return transfer

    # ------------------------------------------------------------------
    # URI parsing and auto-discovery
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_uri(transport_url):
        """Extract the HTTP base URL from a yamcs:// URI."""
        if transport_url.startswith(YAMCS_URI_SCHEME):
            transport_url = transport_url[len(YAMCS_URI_SCHEME):]
        host = transport_url.split("/")[0]
        return "http://" + host

    @staticmethod
    def _discover_instance_and_processor(yamcs_url):
        """Query the YAMCS server for the running instance and processor."""
        client = YamcsLibClient(yamcs_url)
        running = [i for i in client.list_instances() if i.state == "RUNNING"]
        if len(running) == 0:
            raise RuntimeError("No running YAMCS instances found at %s" % yamcs_url)
        if len(running) > 1:
            names = [i.name for i in running]
            raise RuntimeError(
                "Multiple running YAMCS instances found at %s: %s" % (yamcs_url, names)
            )
        instance = running[0].name
        processors = list(client.list_processors(instance=instance))
        realtime = [p for p in processors if p.name == "realtime"]
        processor_name = realtime[0].name if realtime else processors[0].name
        LOGGER.info("Auto-discovered YAMCS instance=%s, processor=%s", instance, processor_name)
        return instance, processor_name

    def _discover_yamcs_namespace(self):
        """Discover the YAMCS namespace prefix from the MDB.

        F Prime uses dot-separated names; YAMCS uses slash-separated names
        under a deployment namespace prefix. This reads the first MDB parameter
        to extract that prefix.
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

    # ------------------------------------------------------------------
    # Telemetry and event subscriptions
    # ------------------------------------------------------------------

    def _build_parameter_list(self):
        """Build YAMCS parameter names from the F Prime channel dictionary."""
        if self.dictionaries is None or not getattr(self.dictionaries, "channel_name", None):
            LOGGER.warning("No channel dictionary available; subscribing to no parameters")
            return []
        return [
            self.yamcs_namespace + "/" + name.replace(".", "/")
            for name in self.dictionaries.channel_name.keys()
        ]

    def _on_parameter_data(self, parameter_data):
        """WebSocket callback — convert YAMCS parameters to ChData."""
        for param_value in parameter_data.parameters:
            try:
                ch_data = self._build_ch_data(param_value)
                if ch_data is not None and self.channel_decoder is not None:
                    self.channel_decoder.send_to_all(ch_data)
            except Exception as exc:
                LOGGER.error("Error processing parameter %s: %s", param_value.name, exc)

    def _on_event_data(self, event):
        """WebSocket callback — convert YAMCS events to EventData."""
        try:
            event_data = self._build_event_data(event)
            if event_data is not None and self.event_decoder is not None:
                self.event_decoder.send_to_all(event_data)
        except Exception as exc:
            LOGGER.error("Error processing event %s: %s", event.event_type, exc)

    # ------------------------------------------------------------------
    # Data object construction
    # ------------------------------------------------------------------

    def _build_ch_data(self, param_value):
        """Convert a YAMCS ParameterValue to an F Prime ChData object."""
        channel_dict = getattr(self.dictionaries, "channel_name", None)
        if channel_dict is None:
            return None
        template = self._lookup_template_by_yamcs_name(param_value.name, channel_dict)
        if template is None:
            return None
        value = getattr(param_value, "eng_value", None)
        if value is None:
            value = getattr(param_value, "raw_value", None)
        if value is None:
            return None
        val_obj = self._build_value_object(value, template.get_type_obj())
        ch_time = self._build_time_type(param_value.generation_time)
        return ChData(val_obj, ch_time, template)

    def _build_event_data(self, event):
        """Convert a YAMCS Event to an F Prime EventData object."""
        event_dict = getattr(self.dictionaries, "event_name", None)
        if event_dict is None:
            return None
        template = self._lookup_template_by_yamcs_name(event.event_type, event_dict)
        if template is None:
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
        """Wrap a Python value in an F Prime serializable type.

        Coerces string values from YAMCS event extras to the numeric or
        boolean type that the F Prime template expects.
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
        """Convert a YAMCS timestamp to an F Prime TimeType.

        Strips timezone info and stamps as TB_WORKSTATION_TIME since the
        original F Prime TimeBase is not preserved through YAMCS.
        """
        if yamcs_timestamp is None:
            return TimeType()
        if isinstance(yamcs_timestamp, str):
            yamcs_timestamp = datetime.datetime.fromisoformat(
                yamcs_timestamp.replace("Z", "+00:00")
            )
        if yamcs_timestamp.tzinfo is not None:
            yamcs_timestamp = yamcs_timestamp.astimezone(
                datetime.timezone.utc
            ).replace(tzinfo=None)
        time_obj = TimeType()
        time_obj.set_datetime(yamcs_timestamp, TimeType.TimeBase("TB_WORKSTATION_TIME"))
        return time_obj

    # ------------------------------------------------------------------
    # Name resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _lookup_template_by_yamcs_name(yamcs_name, fprime_dict):
        """Resolve a YAMCS qualified name to an F Prime dictionary template.

        Tries progressively shorter slash-to-dot conversions. Falls back to
        leaf-name matching when only one candidate exists.
        """
        parts = yamcs_name.lstrip("/").split("/")
        for start in range(len(parts)):
            candidate = ".".join(parts[start:])
            if candidate in fprime_dict:
                return fprime_dict[candidate]
        leaf = parts[-1]
        suffix_matches = [
            tmpl for name, tmpl in fprime_dict.items()
            if name.split(".")[-1] == leaf
        ]
        if len(suffix_matches) == 1:
            return suffix_matches[0]
        if len(suffix_matches) > 1:
            LOGGER.warning(
                "Ambiguous YAMCS name %s matches %d entries by leaf; not resolving",
                yamcs_name, len(suffix_matches),
            )
        return None

    # ------------------------------------------------------------------
    # Command decoding
    # ------------------------------------------------------------------

    def _decode_fprime_command(self, binary_data):
        """Reverse CmdEncoder.encode_api to extract (command_name, args_dict).

        Packet layout: U32(0x5A5A5A5A) | msg_len | ComCfg.Apid | FwOpcodeType | args...
        """
        if self.dictionaries is None:
            return None, None
        try:
            offset = 0
            desc_obj = U32Type()
            desc_obj.deserialize(binary_data, offset)
            offset += desc_obj.getSize()
            if desc_obj.val != COMMAND_DESCRIPTOR_VAL:
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

    @staticmethod
    def _peek_packet_apid(data):
        """Read the APID enum name from an outbound packet header."""
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

    def _lookup_command_by_opcode(self, opcode):
        """Find the command template matching the given opcode."""
        if self.dictionaries is None:
            return None
        command_id_map = getattr(self.dictionaries, "command_id", None)
        if not command_id_map:
            return None
        for tmpl in command_id_map.values():
            if tmpl.get_op_code() == opcode:
                return tmpl
        return None
