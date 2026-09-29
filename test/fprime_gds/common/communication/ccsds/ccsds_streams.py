"""Deterministic Space Packet streams and TM frame sequences shared by the CCSDS framing chain tests

The generated data is seeded so that outputs can be pinned against reference digests.
"""
import hashlib
import random
import struct

from fprime_gds.common.communication.ccsds.space_data_link import SpaceDataLinkFramerDeframer

IDLE_APID = 0x7FF
SCID = 0x77
VCID = 5
FRAME_SIZE = 512
DATA_FIELD_SIZE = FRAME_SIZE - SpaceDataLinkFramerDeframer.TM_HEADER_SIZE - SpaceDataLinkFramerDeframer.TM_TRAILER_SIZE
# 0xFF bytes can never start a version-0 telemetry Space Packet header
GARBAGE = b"\xFF"


def make_space_packet(apid, seq_count, payload):
    """Build a version-0 TM Space Packet (unsegmented) with the given APID, sequence count, and payload"""
    return struct.pack(">HHH", apid & 0x7FF, 0xC000 | (seq_count & 0x3FFF), len(payload) - 1) + payload


def make_tm_frame(field, first_header_pointer, vc_count):
    """Build a valid TM frame around the given data field"""
    assert len(field) == DATA_FIELD_SIZE
    header = struct.pack(
        ">HBBH", (SCID << 4) | (VCID << 1), 0, vc_count, (0x3 << 11) | first_header_pointer
    )
    frame_no_crc = header + field
    return frame_no_crc + struct.pack(">H", SpaceDataLinkFramerDeframer.CCITT_CRC_FUNCTION(frame_no_crc))


def make_packet_sequence(seed, count, apids, max_payload):
    """Generate packets (some idle) with occasional sequence count gaps

    Return:
        list of (apid, packet bytes, payload bytes)
    """
    rng = random.Random(seed)
    sequence_counts = {}
    packets = []
    for _ in range(count):
        apid = rng.choice(apids)
        payload = bytes(rng.randrange(256) for _ in range(rng.randint(1, max_payload)))
        seq_count = sequence_counts.get(apid, 0)
        if rng.random() < 0.2:
            seq_count += rng.randint(1, 5)
        sequence_counts[apid] = seq_count + 1
        packets.append((apid, make_space_packet(apid, seq_count, payload), payload))
    return packets


def expected_payloads(packets):
    """Payloads of the non-idle packets, in order"""
    return [payload for apid, _, payload in packets if apid != IDLE_APID]


def chunk(data, seed, max_chunk):
    """Split data into pseudo-random sized chunks"""
    rng = random.Random(seed)
    chunks = []
    while data:
        size = rng.randint(1, max_chunk)
        chunks.append(data[:size])
        data = data[size:]
    return chunks


def build_stream():
    """Byte stream of packets with garbage between some packets

    Return:
        (packets as from make_packet_sequence, stream bytes, chunks of the stream)
    """
    packets = make_packet_sequence(seed=0xF9, count=40, apids=[0x100, 0x101, IDLE_APID], max_payload=60)
    raw = [packet for _, packet, _ in packets]
    stream = GARBAGE * 3 + b"".join(raw[:10]) + GARBAGE * 2 + b"".join(raw[10:25]) + GARBAGE + b"".join(raw[25:])
    return packets, stream, chunk(stream, seed=0xF9, max_chunk=45)


def build_frames():
    """TM frames carrying a packet sequence, packets spanning frames as needed, idle padding the last frame

    Return:
        (packets as from make_packet_sequence, list of TM frames)
    """
    packets = make_packet_sequence(seed=0xA7, count=30, apids=[0x200, 0x201, IDLE_APID], max_payload=700)
    data = b"".join(packet for _, packet, _ in packets)
    # Offsets at which a packet header starts, used to compute each frame's First Header Pointer
    header_offsets = set()
    offset = 0
    for _, packet, _ in packets:
        header_offsets.add(offset)
        offset += len(packet)
    if len(data) % DATA_FIELD_SIZE:
        padding = DATA_FIELD_SIZE - (len(data) % DATA_FIELD_SIZE)
        if padding < SpaceDataLinkFramerDeframer.SPACE_PACKET_HEADER_SIZE:
            padding += DATA_FIELD_SIZE
        header_offsets.add(len(data))
        data += make_space_packet(IDLE_APID, 0, bytes(padding - SpaceDataLinkFramerDeframer.SPACE_PACKET_HEADER_SIZE))
    frames = []
    for vc_count, start in enumerate(range(0, len(data), DATA_FIELD_SIZE)):
        field = data[start : start + DATA_FIELD_SIZE]
        headers_in_frame = [head - start for head in header_offsets if start <= head < start + DATA_FIELD_SIZE]
        first_header_pointer = min(headers_in_frame) if headers_in_frame else SpaceDataLinkFramerDeframer.FHP_NO_PACKET_START
        frames.append(make_tm_frame(field, first_header_pointer, vc_count % 256))
    return packets, frames


def digest(items):
    """Length-prefixed SHA-256 digest of a sequence of byte strings"""
    hasher = hashlib.sha256()
    for item in items:
        hasher.update(len(item).to_bytes(4, "big") + item)
    return hasher.hexdigest()
