"""
fprime_gds.common.yamcs_transport:

YAMCS-backed transport for the F Prime GDS.

@author yuktiv
"""

import datetime
import logging
import time

from yamcs.client import YamcsClient as YamcsLibClient

from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.data_types.cmd_data import CmdData
from fprime_gds.common.data_types.event_data import EventData
from fprime_gds.common.models.serialize.numerical_types import (
    FloatType,
    IntegerType,
)
from fprime_gds.common.models.serialize.bool_type import BoolType
from fprime_gds.common.models.serialize.string_type import StringType
from fprime_gds.common.models.serialize.time_type import TimeType
from fprime_gds.common.transport import TransportClient

LOGGER = logging.getLogger("transport")

YAMCS_URI_SCHEME = "yamcs://"
FILE_TRANSFER_POLL_INTERVAL = 2
FILE_TRANSFER_SERVICE_NAME = "FprimeFilePacketService"
FILE_TRANSFER_BUCKET = "fprimeFilesIn"


class YamcsWrapper:

    def __init__(self):
        self.yamcs_client = None
        self.processor = None
        self.subscriptions = []
        self.instance = None
        self.namespace = ""

    def configure(self, yamcs_url, instance, processor_name):
        self.instance = instance
        LOGGER.info("Connecting to YAMCS: %s, instance=%s, processor=%s", yamcs_url, instance, processor_name)
        self.yamcs_client = YamcsLibClient(yamcs_url)
        self.processor = self.yamcs_client.get_processor(instance=instance, processor=processor_name)
        self.namespace = self._discover_namespace()

    def subscribe(self, parameter_names, on_parameter_callback, on_event_callback):
        if parameter_names:
            LOGGER.info("Subscribing to %d YAMCS parameters", len(parameter_names))
            self.subscriptions.append(
                self.processor.create_parameter_subscription(
                    parameters=parameter_names,
                    on_data=on_parameter_callback,
                    send_from_cache=True,
                    update_on_expiration=False
                )
            )
        LOGGER.info("Subscribing to YAMCS event stream")
        self.subscriptions.append(
            self.yamcs_client.create_event_subscription(
                instance=self.instance, on_data=on_event_callback
            )
        )

    def disconnect(self):
        for subscription in self.subscriptions:
            try:
                subscription.cancel()
            except Exception as exc:
                LOGGER.warning("Error canceling subscription: %s", exc)
        self.subscriptions.clear()
        self.yamcs_client = None
        self.processor = None
        self.instance = None

    def issue_command(self, cmd_name, cmd_args):
        return self.processor.issue_command(command=cmd_name, args=cmd_args)

    def get_file_transfer_service(self, service_name=FILE_TRANSFER_SERVICE_NAME):
        ft_client = self.yamcs_client.get_file_transfer_client(instance=self.instance)
        return ft_client.get_service(service_name)

    def get_storage_client(self):
        return self.yamcs_client.get_storage_client()

    def _discover_namespace(self):
        try:
            mdb = self.yamcs_client.get_mdb(instance=self.instance)
            for param in mdb.list_parameters():
                parts = param.qualified_name.split("/")
                if len(parts) >= 3 and parts[1] not in ("yamcs", "system"):
                    namespace = "/" + parts[1]
                    LOGGER.info("Discovered YAMCS namespace: %s", namespace)
                    return namespace
        except Exception as exc:
            LOGGER.warning("Could not discover YAMCS namespace: %s", exc)
        return ""

    def to_yamcs_param_name(self, fprime_name):
        return self.namespace + "/" + fprime_name.replace(".", "/")

    def to_yamcs_cmd_name(self, fprime_name):
        return self.namespace + "/" + fprime_name.replace(".", "/")

    def to_yamcs_qualified_arg(self, yamcs_cmd_name, arg_name):
        leaf = yamcs_cmd_name.lstrip("/")
        if "/" in leaf:
            leaf = leaf.split("/", 1)[1]
        return leaf + "|" + arg_name

    def to_fprime_name(self, yamcs_name):
        name = yamcs_name.lstrip("/")
        prefix = self.namespace.lstrip("/")
        if prefix and name.startswith(prefix + "/"):
            name = name[len(prefix) + 1:]
        return name.replace("/", ".")


class YamcsClient(TransportClient):

    def __init__(self):
        super().__init__()
        self.yamcs = YamcsWrapper()
        self.dictionaries = None
        self.channel_decoder = None
        self.event_decoder = None
        self._pending_cmd = None
        self._event_by_leaf = {}

    def set_pipeline_references(self, dictionaries, channel_decoder, event_decoder):
        self.dictionaries = dictionaries
        self.channel_decoder = channel_decoder
        self.event_decoder = event_decoder
        self._event_by_leaf = {}
        if dictionaries and getattr(dictionaries, "event_name", None):
            for full_name, template in dictionaries.event_name.items():
                self._event_by_leaf[template.get_name()] = template

    def connect(self, connection_uri, incoming_routing=None, outgoing_routing=None):
        yamcs_url = self._parse_uri(connection_uri)
        instance, processor_name = self._discover_instance_and_processor(yamcs_url)
        self.yamcs.configure(yamcs_url, instance, processor_name)
        self.yamcs.subscribe(
            parameter_names=self._build_parameter_list(),
            on_parameter_callback=self._on_parameter_data,
            on_event_callback=self._on_event_data,
        )

    def disconnect(self):
        self.yamcs.disconnect()

    def send(self, data):
        if self._pending_cmd:
            self._pending_cmd = None
            return
        LOGGER.debug("Binary packet received; not routed (YAMCS uses structured APIs)")

    def recv(self, timeout=None):
        return b""

    def data_callback(self, data, sender=None):
        if isinstance(data, CmdData):
            self._issue_command(data)
            self._pending_cmd = True
            return
        super().data_callback(data, sender)

    def _issue_command(self, cmd_data):
        template = cmd_data.get_template()
        arg_vals = cmd_data.get_args()
        yamcs_cmd_name = self.yamcs.to_yamcs_cmd_name(template.get_full_name())
        args_dict = {}
        for i, spec in enumerate(template.get_args()):
            val = arg_vals[i].val
            if isinstance(val, bool):
                val = 1 if val else 0
            args_dict[spec[0]] = val
        try:
            issued = self.yamcs.issue_command(yamcs_cmd_name, args_dict)
            LOGGER.info("Command issued: %s id=%s", yamcs_cmd_name, getattr(issued, "id", None))
        except Exception as exc:
            LOGGER.error("YAMCS rejected command %s: %s", yamcs_cmd_name, exc)
            raise

    def _on_parameter_data(self, parameter_data):
        for param_value in parameter_data.parameters:
            try:
                ch_data = self._build_ch_data(param_value)
                if ch_data is not None and self.channel_decoder is not None:
                    self.channel_decoder.send_to_all(ch_data)
            except Exception as exc:
                LOGGER.error("Error processing parameter %s: %s", param_value.name, exc)

    def _on_event_data(self, event):
        try:
            event_data = self._build_event_data(event)
            if event_data is not None and self.event_decoder is not None:
                self.event_decoder.send_to_all(event_data)
        except Exception as exc:
            LOGGER.error("Error processing event %s: %s", event.event_type, exc)

    def _build_ch_data(self, param_value):
        fprime_name = self.yamcs.to_fprime_name(param_value.name)
        template = self.dictionaries.channel_name.get(fprime_name)
        if template is None:
            LOGGER.debug("No channel template for %s", fprime_name)
            return None
        if param_value.eng_value is None:
            return None
        val_obj = self._build_value_object(param_value.eng_value, template.get_type_obj())
        ch_time = self._build_time_type(param_value.generation_time)
        return ChData(val_obj, ch_time, template)

    def _build_event_data(self, event):
        template = self.dictionaries.event_name.get(event.event_type) or self._event_by_leaf.get(event.event_type)
        if template is None:
            LOGGER.debug("No event template for %s", event.event_type)
            return None

        # Extract event arguments from YAMCS event
        extra = getattr(event, "extra", None) or {}
        template_args = template.get_args()

        # Check if event has no arguments (some events don't have args)
        if not template_args:
            return EventData(tuple(), self._build_time_type(event.generation_time), template)

        # Build argument objects, handling missing data
        arg_objs = []
        for arg_spec in template_args:
            arg_name, _, arg_type_class = arg_spec
            arg_value = extra.get(arg_name)

            if arg_value is None:
                # Log warning for missing event argument
                LOGGER.warning(
                    "Event %s missing expected argument '%s'. "
                    "Event may not display correctly. Extra fields: %s",
                    event.event_type, arg_name, list(extra.keys())
                )
                # Create empty value object - will cause format string to show None or empty
                arg_obj = arg_type_class()
                arg_obj.val = "" if isinstance(arg_obj, StringType) else None
            else:
                arg_obj = self._build_value_object(arg_value, arg_type_class)

            arg_objs.append(arg_obj)

        return EventData(tuple(arg_objs), self._build_time_type(event.generation_time), template)

    def upload_file(self, local_path, remote_path, bucket_name=FILE_TRANSFER_BUCKET,
                    service_name=FILE_TRANSFER_SERVICE_NAME, timeout=120):
        storage = self.yamcs.get_storage_client()
        object_name = local_path.split("/")[-1] if "/" in local_path else local_path
        with open(local_path, "rb") as f:
            storage.upload_object(
                bucket_name=bucket_name,
                object_name=object_name,
                file_obj=f,
            )
        LOGGER.info("Staged %s in bucket %s as %s", local_path, bucket_name, object_name)
        ft_service = self.yamcs.get_file_transfer_service(service_name)
        transfer = ft_service.upload(
            bucket_name=bucket_name, object_name=object_name, remote_path=remote_path,
        )
        LOGGER.info("Upload transfer started: id=%s remote=%s", transfer.id, remote_path)
        return self._await_transfer(ft_service, transfer, timeout)

    def download_file(self, remote_path, bucket_name=FILE_TRANSFER_BUCKET,
                      object_name=None, service_name=FILE_TRANSFER_SERVICE_NAME, timeout=60):
        if object_name is None:
            object_name = remote_path.split("/")[-1] if "/" in remote_path else remote_path
        ft_service = self.yamcs.get_file_transfer_service(service_name)
        transfer = ft_service.download(
            bucket_name=bucket_name, remote_path=remote_path, object_name=object_name,
        )
        LOGGER.info("Download transfer started: id=%s remote=%s", transfer.id, remote_path)
        return self._await_transfer(ft_service, transfer, timeout)

    @staticmethod
    def _await_transfer(ft_service, transfer, timeout):
        subscription = ft_service.create_transfer_subscription()
        deadline = time.time() + timeout
        try:
            while time.time() < deadline:
                current = subscription.get_transfer(transfer.id)
                if current is not None:
                    state = str(current.state)
                    if "COMPLETED" in state:
                        LOGGER.info("Transfer %s completed", transfer.id)
                        return current
                    if "FAILED" in state:
                        LOGGER.error("Transfer %s failed", transfer.id)
                        return current
                time.sleep(FILE_TRANSFER_POLL_INTERVAL)
        finally:
            subscription.cancel()
        LOGGER.warning("Transfer %s timed out after %ds", transfer.id, timeout)
        return transfer

    @staticmethod
    def _parse_uri(transport_url):
        if transport_url.startswith(YAMCS_URI_SCHEME):
            transport_url = transport_url[len(YAMCS_URI_SCHEME):]
        return "http://" + transport_url.split("/")[0]

    @staticmethod
    def _discover_instance_and_processor(yamcs_url):
        client = YamcsLibClient(yamcs_url)
        running = [i for i in client.list_instances() if i.state == "RUNNING"]
        if len(running) == 0:
            raise RuntimeError("No running YAMCS instances found at %s" % yamcs_url)
        if len(running) > 1:
            names = [i.name for i in running]
            raise RuntimeError("Multiple running YAMCS instances found at %s: %s" % (yamcs_url, names))
        instance = running[0].name
        processors = list(client.list_processors(instance=instance))
        realtime = [p for p in processors if p.name == "realtime"]
        processor_name = realtime[0].name if realtime else processors[0].name
        LOGGER.info("Auto-discovered YAMCS instance=%s, processor=%s", instance, processor_name)
        return instance, processor_name

    def _build_parameter_list(self):
        if self.dictionaries is None or not getattr(self.dictionaries, "channel_name", None):
            LOGGER.warning("No channel dictionary available; subscribing to no parameters")
            return []
        return [self.yamcs.to_yamcs_param_name(name) for name in self.dictionaries.channel_name.keys()]

    @staticmethod
    def _build_value_object(value, type_class):
        obj = type_class()
        if isinstance(obj, BoolType):
            if isinstance(value, str):
                value = value.lower() in ("true", "1", "yes")
            elif isinstance(value, (int, float)):
                value = value != 0
        elif isinstance(value, str) and not isinstance(obj, StringType):
            if isinstance(obj, IntegerType):
                value = int(value)
            elif isinstance(obj, FloatType):
                value = float(value)
        obj.val = value
        return obj

    @staticmethod
    def _build_time_type(yamcs_timestamp):
        if yamcs_timestamp is None:
            return TimeType()
        if yamcs_timestamp.tzinfo is not None:
            yamcs_timestamp = yamcs_timestamp.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        time_obj = TimeType()
        time_obj.set_datetime(yamcs_timestamp, TimeType.TimeBase("TB_WORKSTATION_TIME"))
        return time_obj
