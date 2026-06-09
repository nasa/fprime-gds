"""
transport_yamcs.py

YAMCS WebSocket transport for F Prime GDS pipeline.
Subscribes to YAMCS parameter/event streams and feeds data into standard GDS pipeline.

Current: Converts YAMCS data → F Prime binary format for existing decoders.
Future: Can pass native YAMCS objects directly to enhanced decoders.
"""

import struct
import logging
from typing import Optional
from yamcs.client import YamcsClient

from fprime_gds.common.transport import ThreadedTransportClient
from fprime_gds.common.utils.config_manager import ConfigManager


class YamcsTransportClient(ThreadedTransportClient):
    """
    Transport implementation using YAMCS WebSocket streaming.

    Converts YAMCS ParameterValue/Event objects to F Prime binary packets
    that can be processed by existing GDS decoders.

    Usage:
        transport = YamcsTransportClient('http://localhost:8090', 'fprime-project')
        transport.connect('yamcs://localhost:8090/fprime-project/realtime', ...)
    """

    def __init__(self, yamcs_url='http://localhost:8090', instance='fprime-project'):
        """
        Initialize YAMCS transport client.

        Args:
            yamcs_url: YAMCS server URL (e.g., 'http://localhost:8090')
            instance: YAMCS instance name (e.g., 'fprime-project')
        """
        super().__init__()
        self.logger = logging.getLogger(__name__)

        self.yamcs_url = yamcs_url
        self.instance = instance

        self.yamcs_client = None
        self.processor = None
        self.subscriptions = []

        # Dictionary mappings (set during connect)
        self.channel_dict = None  # For parameter name → template lookup
        self.event_dict = None    # For event name → template lookup

    def connect(self, uri, incoming_tag=None, outgoing_tag=None):
        """
        Connect to YAMCS and subscribe to telemetry/event streams.

        Args:
            uri: Connection URI (e.g., 'yamcs://localhost:8090/fprime-project/realtime')
                 Format: yamcs://<host>:<port>/<instance>/<processor>
            incoming_tag: Ignored (for compatibility with base class)
            outgoing_tag: Ignored (for compatibility with base class)
        """
        # Parse URI: yamcs://localhost:8090/fprime-project/realtime
        if uri.startswith('yamcs://'):
            uri = uri[8:]  # Strip 'yamcs://'

        parts = uri.split('/')
        if len(parts) < 2:
            raise ValueError(f"Invalid YAMCS URI format. Expected: yamcs://host:port/instance/processor, got: {uri}")

        # Extract instance and processor
        self.instance = parts[0].split(':')[0] if ':' not in parts[0] else parts[-2]
        processor_name = parts[-1] if len(parts) > 1 else 'realtime'

        self.logger.info(f"Connecting to YAMCS: {self.yamcs_url}, instance={self.instance}, processor={processor_name}")

        # Initialize YAMCS client
        self.yamcs_client = YamcsClient(self.yamcs_url)
        self.processor = self.yamcs_client.get_processor(
            instance=self.instance,
            processor=processor_name
        )

        # Load dictionaries from ConfigManager
        config = ConfigManager()
        self.channel_dict = config.get_tlm_dict()  # {name: template, ...}
        self.event_dict = config.get_event_dict()  # {name: template, ...}

        # Subscribe to parameter stream (telemetry)
        self.logger.info("Subscribing to YAMCS parameter stream...")
        param_subscription = self.processor.create_parameter_subscription(
            parameters='*',  # Subscribe to all parameters
            on_data=self._on_parameter_data
        )
        self.subscriptions.append(param_subscription)

        # Subscribe to event stream
        self.logger.info("Subscribing to YAMCS event stream...")
        event_subscription = self.yamcs_client.create_event_subscription(
            on_data=self._on_event_data
        )
        self.subscriptions.append(event_subscription)

        self.logger.info("YAMCS subscriptions established")

    def disconnect(self):
        """Disconnect from YAMCS and close subscriptions"""
        self.logger.info("Disconnecting from YAMCS...")

        for subscription in self.subscriptions:
            try:
                subscription.close()
            except Exception as e:
                self.logger.warning(f"Error closing subscription: {e}")

        self.subscriptions.clear()
        self.yamcs_client = None
        self.processor = None

    def send(self, data):
        """
        Send command to YAMCS (uplink).

        Args:
            data: Binary command packet from F Prime encoder
        """
        # MVP: Parse F Prime command binary → issue to YAMCS
        # For now, we'll just log - command support can be added later
        self.logger.warning("Command uplink not yet implemented in YAMCS transport")
        # TODO: Decode binary command packet, extract name/args, call processor.issue_command()

    def recv(self, timeout=None):
        """
        Not used - YAMCS uses WebSocket callbacks instead of polling.
        """
        pass

    # ==================== YAMCS CALLBACKS ====================

    def _on_parameter_data(self, parameter_data):
        """
        Callback when YAMCS sends parameter updates (telemetry).

        Args:
            parameter_data: ParameterData object containing list of ParameterValue objects
        """
        for param_value in parameter_data.parameters:
            try:
                # Convert YAMCS ParameterValue → F Prime binary packet
                binary_packet = self._encode_parameter_as_fprime(param_value)

                if binary_packet:
                    # Feed to distributor (via send_to_all from HandlerRegistrar)
                    self.send_to_all(binary_packet)

            except Exception as e:
                self.logger.error(f"Error processing parameter {param_value.name}: {e}")

    def _on_event_data(self, event):
        """
        Callback when YAMCS sends event updates.

        Args:
            event: Event object from YAMCS
        """
        try:
            # Convert YAMCS Event → F Prime binary packet
            binary_packet = self._encode_event_as_fprime(event)

            if binary_packet:
                self.send_to_all(binary_packet)

        except Exception as e:
            self.logger.error(f"Error processing event {event.type}: {e}")

    # ==================== YAMCS → F PRIME CONVERSION ====================

    def _encode_parameter_as_fprime(self, param_value):
        """
        Convert YAMCS ParameterValue to F Prime channel binary format.

        Args:
            param_value: YAMCS ParameterValue object

        Returns:
            bytes: F Prime binary packet (length + descriptor + payload)

        F Prime packet format:
            [4 bytes: length]
            [4 bytes: descriptor type (FW_PACKET_TELEM = 2)]
            [payload:
                4 bytes: channel ID
                4 bytes: timestamp seconds
                4 bytes: timestamp microseconds
                N bytes: serialized value
            ]
        """
        # Look up F Prime channel template by name
        param_name = param_value.name

        # Try full name first
        template = self.channel_dict.get(param_name)

        # If not found, try stripping component prefix
        if not template:
            short_name = param_name.split('.')[-1]
            # Search for any channel ending with this name
            matches = [t for name, t in self.channel_dict.items() if name.endswith(f'.{short_name}')]
            template = matches[0] if matches else None

        if not template:
            self.logger.warning(f"Unknown parameter in F Prime dictionary: {param_name}")
            return None

        # Extract value (prefer engValue over rawValue)
        if hasattr(param_value, 'eng_value') and param_value.eng_value is not None:
            value = param_value.eng_value
        elif hasattr(param_value, 'raw_value') and param_value.raw_value is not None:
            value = param_value.raw_value
        else:
            self.logger.warning(f"Parameter {param_name} has no value")
            return None

        # Serialize the value according to F Prime type
        serialized_value = self._serialize_value(value, template.get_type())

        # Convert YAMCS timestamp to F Prime format
        timestamp = param_value.generation_time
        if isinstance(timestamp, str):
            from datetime import datetime
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))

        time_seconds = int(timestamp.timestamp())
        time_microseconds = timestamp.microsecond

        # Build payload
        channel_id = template.get_id()
        payload = struct.pack('>III', channel_id, time_seconds, time_microseconds)
        payload += serialized_value

        # Build complete packet
        descriptor = 2  # FW_PACKET_TELEM
        length = len(payload) + 4  # +4 for descriptor

        packet = struct.pack('>II', length, descriptor) + payload

        return packet

    def _encode_event_as_fprime(self, event):
        """
        Convert YAMCS Event to F Prime event binary format.

        Args:
            event: YAMCS Event object

        Returns:
            bytes: F Prime binary packet

        F Prime event packet format:
            [4 bytes: length]
            [4 bytes: descriptor type (FW_PACKET_LOG = 3)]
            [payload:
                4 bytes: event ID
                4 bytes: timestamp seconds
                4 bytes: timestamp microseconds
                N bytes: serialized arguments
            ]
        """
        # Look up F Prime event template by type
        event_type = event.type

        template = self.event_dict.get(event_type)

        if not template:
            # Try to find by short name
            short_name = event_type.split('.')[-1]
            matches = [t for name, t in self.event_dict.items() if name.endswith(f'.{short_name}')]
            template = matches[0] if matches else None

        if not template:
            self.logger.warning(f"Unknown event in F Prime dictionary: {event_type}")
            return None

        # Extract arguments from YAMCS event
        args = []
        if hasattr(event, 'extra') and event.extra:
            # YAMCS stores structured args in 'extra' dict
            # Order them according to template
            for arg_template in template.get_args():
                arg_name = arg_template.get_name()
                arg_value = event.extra.get(arg_name)
                args.append(arg_value if arg_value is not None else 0)

        # Serialize arguments
        serialized_args = b''
        for arg, arg_template in zip(args, template.get_args()):
            serialized_args += self._serialize_value(arg, arg_template.get_type())

        # Convert timestamp
        timestamp = event.generation_time
        if isinstance(timestamp, str):
            from datetime import datetime
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))

        time_seconds = int(timestamp.timestamp())
        time_microseconds = timestamp.microsecond

        # Build payload
        event_id = template.get_id()
        payload = struct.pack('>III', event_id, time_seconds, time_microseconds)
        payload += serialized_args

        # Build complete packet
        descriptor = 3  # FW_PACKET_LOG
        length = len(payload) + 4

        packet = struct.pack('>II', length, descriptor) + payload

        return packet

    def _serialize_value(self, value, fprime_type):
        """
        Serialize a value according to F Prime type.

        Args:
            value: Python value
            fprime_type: F Prime type object

        Returns:
            bytes: Serialized value
        """
        # This is a simplified serialization - real implementation needs
        # to handle all F Prime types properly

        type_name = fprime_type.get_type_name() if hasattr(fprime_type, 'get_type_name') else str(fprime_type)

        # Handle basic types
        if 'U32' in type_name or 'uint32' in type_name.lower():
            return struct.pack('>I', int(value))
        elif 'I32' in type_name or 'int32' in type_name.lower():
            return struct.pack('>i', int(value))
        elif 'U16' in type_name or 'uint16' in type_name.lower():
            return struct.pack('>H', int(value))
        elif 'I16' in type_name or 'int16' in type_name.lower():
            return struct.pack('>h', int(value))
        elif 'U8' in type_name or 'uint8' in type_name.lower():
            return struct.pack('>B', int(value))
        elif 'I8' in type_name or 'int8' in type_name.lower():
            return struct.pack('>b', int(value))
        elif 'F32' in type_name or 'float32' in type_name.lower():
            return struct.pack('>f', float(value))
        elif 'F64' in type_name or 'float64' in type_name.lower():
            return struct.pack('>d', float(value))
        elif 'bool' in type_name.lower():
            return struct.pack('>B', 1 if value else 0)
        elif 'string' in type_name.lower():
            # String format: 2-byte length + string bytes
            encoded = str(value).encode('utf-8')
            return struct.pack('>H', len(encoded)) + encoded
        else:
            # Fallback: try to serialize using F Prime's own serialization
            try:
                # Use the type's serialize method if available
                return fprime_type.serialize(value)
            except:
                self.logger.warning(f"Unknown type serialization: {type_name}, using raw bytes")
                return struct.pack('>I', int(value))  # Assume 32-bit int as fallback
