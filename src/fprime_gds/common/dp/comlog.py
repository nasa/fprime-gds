"""
fprime_gds.common.dp.comlog: decode Svc.ComLoggerDp data products

Svc.ComLoggerDp stores every Com buffer it receives as a ComBufferRecord: a U32 sentry (ComLoggerDpSentry,
0xDEADBEEF unless the project overrides it) followed by the raw Com buffer, i.e. a packet descriptor and one
event or telemetry packet. This module turns those records back into events and channel samples with the
decoders the live GDS uses, formats them as JSON or text, merges a directory of products into GDS-style
channel/event logs, and recovers records from damaged files by scanning for the sentry.
"""
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.data_types.event_data import EventData
from fprime_gds.common.decoders.ch_decoder import ChDecoder
from fprime_gds.common.decoders.event_decoder import EventDecoder
from fprime_gds.common.dp.decoder import DataProductDecoder, DataProductError
from fprime_gds.common.models.dictionaries import Dictionaries
from fprime_gds.common.models.serialize.numerical_types import U32Type
from fprime_gds.common.utils.config_manager import ConfigManager

DEFAULT_SENTRY = 0xDEADBEEF
COM_BUFFER_RECORD_SUFFIX = ".ComBufferRecord"
CHANNEL_LOG_NAME = "channels-dp.log"
EVENT_LOG_NAME = "events-dp.log"


class ComLoggerDpDecoder:
    """Decodes the ComBufferRecords of ComLoggerDp data products into events and channel samples.

    Assumes the dictionary has been loaded into the ConfigManager (see Dictionaries.load_dictionaries_into_config).
    """

    def __init__(self, dictionaries: Dictionaries, sentry: int = DEFAULT_SENTRY, validate_sentry: bool = True,
                 validate_crc: bool = True):
        self.dictionaries = dictionaries
        self.sentry = U32Type(sentry).serialize()
        self.validate_sentry = validate_sentry
        self.validate_crc = validate_crc
        self.channel_decoder = ChDecoder(dictionaries.channel_id)
        self.event_decoder = EventDecoder(dictionaries.event_id)

    def decode_com_buffer(self, data: bytes) -> Tuple[str, list]:
        """Decode one Com buffer (packet descriptor followed by a packet) into its ChData or EventData objects"""
        descriptor = ConfigManager().get_type("FwPacketDescriptorType")()
        descriptor.deserialize(data, 0)
        try:
            packet_type = ConfigManager().get_type("ComCfg.Apid").from_int(descriptor.val).val
        except Exception:
            raise DataProductError(f"Unknown packet descriptor {descriptor.val:#x}")
        payload = data[descriptor.getSize():]
        if packet_type == "FW_PACKET_TELEM":
            return packet_type, self.channel_decoder.decode_api(payload)
        if packet_type == "FW_PACKET_LOG":
            return packet_type, self.event_decoder.decode_api(payload)
        raise DataProductError(f"Unsupported packet type {packet_type}")

    def decode_record_data(self, data: bytes) -> Dict[str, Any]:
        """Decode the data of one ComBufferRecord: the sentry followed by the Com buffer"""
        sentry_size = len(self.sentry)
        if len(data) < sentry_size:
            raise DataProductError(f"Record of {len(data)} bytes is too short to hold a sentry")
        if self.validate_sentry and data[:sentry_size] != self.sentry:
            raise DataProductError(f"Sentry mismatch: expected 0x{self.sentry.hex()}, got 0x{data[:sentry_size].hex()}")
        packet_type, packets = self.decode_com_buffer(data[sentry_size:])
        return {"PacketType": packet_type, "Packets": packets}

    def decode(self, path) -> Dict[str, Any]:
        """Decode a data product file; ComBufferRecords get their packets in place of the raw bytes"""
        result = DataProductDecoder(self.dictionaries, str(path), validate_crc=self.validate_crc).decode()
        for record in result["Records"]:
            if not record["Record"]["record_name"].endswith(COM_BUFFER_RECORD_SUFFIX):
                continue
            data = bytes(record.pop("Data")["values"])
            try:
                record.update(self.decode_record_data(data))
            except Exception as exc:
                record["Error"] = str(exc)
        result["Statistics"] = statistics(result["Records"])
        return result

    def reconstruct(self, path) -> Dict[str, Any]:
        """Recover the records of a damaged file by scanning for the sentry instead of trusting the header"""
        data = Path(path).read_bytes()
        positions = []
        position = data.find(self.sentry)
        while position != -1:
            positions.append(position)
            position = data.find(self.sentry, position + 1)

        records = []
        for index, position in enumerate(positions):
            end = positions[index + 1] if index + 1 < len(positions) else len(data)
            size = self.record_size(data, position, end, has_next=index + 1 < len(positions))
            record = {"Record": {"offset": position, "size": size}}
            try:
                record.update(self.decode_record_data(data[position:position + size]))
            except Exception as exc:
                record["Error"] = str(exc)
            records.append(record)
        return {
            "File": {"path": str(path), "size": len(data), "sentries_found": len(positions)},
            "Records": records,
            "Statistics": statistics(records),
        }

    @staticmethod
    def record_size(data: bytes, position: int, end: int, has_next: bool) -> int:
        """Size of the record data starting at a sentry.

        In an intact record the FwSizeStoreType length prefix just before the sentry covers the sentry and the Com
        buffer; it is used when it fits before the next sentry. Otherwise the gap to the next sentry is used, minus
        the record ID and length prefix that precede the next sentry.
        """
        size_type = ConfigManager().get_type("FwSizeStoreType")
        prefix_size = size_type.getSize()
        if position >= prefix_size:
            size_obj = size_type()
            size_obj.deserialize(data, position - prefix_size)
            if U32Type.getSize() < size_obj.val <= end - position:
                return size_obj.val
        if has_next:
            return max(end - position - prefix_size - ConfigManager().get_type("FwDpIdType").getSize(), 0)
        return end - position


def statistics(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count the records, decoded events and channels, and failed records"""
    stats = {"Records": len(records), "Events": 0, "Channels": 0, "Errors": 0}
    for record in records:
        if "Error" in record:
            stats["Errors"] += 1
        for packet in record.get("Packets", []):
            stats["Events" if isinstance(packet, EventData) else "Channels"] += 1
    return stats


def packet_to_jsonable(packet) -> Dict[str, Any]:
    """JSON-ready form of one decoded event or channel sample"""
    item = {"type": "event" if isinstance(packet, EventData) else "channel"}
    item.update(packet.get_dict())
    if isinstance(packet, EventData):
        item["args"] = [
            {"name": arg_name, "value": arg.val}
            for (arg_name, _, _), arg in zip(packet.template.get_args(), packet.get_args())
        ]
    else:
        item["value"] = packet.get_val()
    return item


def to_jsonable(result: Dict[str, Any]) -> Dict[str, Any]:
    """JSON-ready form of a decode or reconstruct result"""
    jsonable = dict(result)
    jsonable["Records"] = [
        {**record, "Packets": [packet_to_jsonable(packet) for packet in record["Packets"]]}
        if "Packets" in record else record
        for record in result["Records"]
    ]
    return jsonable


def write_json(result: Dict[str, Any], path: Path):
    with open(path, "w") as file_handle:
        json.dump(to_jsonable(result), file_handle, indent=2, default=str)


def format_text(result: Dict[str, Any], source: str) -> str:
    """Human-readable form of a decode or reconstruct result"""
    lines = [f"ComLoggerDp data product: {source}"]
    for section in ("Header", "File"):
        for name, field in result.get(section, {}).items():
            value = field["value"] if isinstance(field, dict) and "value" in field else field
            lines.append(f"  {name}: {json.dumps(value, default=str)}")
    stats = result["Statistics"]
    lines.append(f"Records: {stats['Records']} ({stats['Events']} events, {stats['Channels']} channels, {stats['Errors']} errors)")
    for index, record in enumerate(result["Records"]):
        label = f"Record {index}" + (f" @ {record['Record']['offset']}" if "offset" in record["Record"] else "")
        if "Error" in record:
            lines.append(f"[{label}] ERROR: {record['Error']}")
        elif "Packets" in record:
            lines.append(f"[{label}] {record['PacketType']}")
            lines.extend(f"  {packet.get_str(verbose=True)}" for packet in record["Packets"])
        else:
            lines.append(f"[{label}] {record['Record']['record_name']}: {json.dumps(record['Data'], default=str)}")
    return "\n".join(lines) + "\n"


def write_text(result: Dict[str, Any], path: Path):
    with open(path, "w") as file_handle:
        file_handle.write(format_text(result, str(path)))


def write_collected_logs(results: Iterable[Dict[str, Any]], output_dir: Path) -> Tuple[int, int]:
    """Merge the packets of several products into time-sorted GDS-style channel and event logs.

    Returns the number of channel samples and events written.
    """
    channels, events = [], []
    for result in results:
        for record in result["Records"]:
            for packet in record.get("Packets", []):
                (events if isinstance(packet, EventData) else channels).append(packet)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, packets, data_type in ((CHANNEL_LOG_NAME, channels, ChData), (EVENT_LOG_NAME, events, EventData)):
        with open(output_dir / name, "w") as file_handle:
            file_handle.write(data_type.get_csv_header(verbose=True))
            for packet in sorted(packets, key=lambda packet: packet.time):
                file_handle.write(packet.get_str(verbose=True, csv=True) + "\n")
    return len(channels), len(events)
