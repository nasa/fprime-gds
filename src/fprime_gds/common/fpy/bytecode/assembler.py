from dataclasses import astuple, dataclass
import struct
import zlib
from fprime_gds.common.fpy.bytecode.directives import Directive
from pathlib import Path

HEADER_FORMAT = "!BBBBBHI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


@dataclass
class Header:
    majorVersion: int
    minorVersion: int
    patchVersion: int
    schemaVersion: int
    argumentCount: int
    statementCount: int
    bodySize: int


FOOTER_FORMAT = "!I"
FOOTER_SIZE = struct.calcsize(FOOTER_FORMAT)

SCHEMA_VERSION = 2


@dataclass
class Footer:
    crc: int


def serialize_directives(dirs: list[Directive], output: Path):
    output_bytes = bytes()

    for dir in dirs:
        output_bytes += dir.serialize()

    header = Header(0, 0, 0, SCHEMA_VERSION, 0, len(dirs), len(output_bytes))
    output_bytes = struct.pack(HEADER_FORMAT, *astuple(header)) + output_bytes

    crc = zlib.crc32(output_bytes) % (1 << 32)
    footer = Footer(crc)
    output_bytes += struct.pack(FOOTER_FORMAT, *astuple(footer))
    output.write_bytes(output_bytes)


def deserialize_directives(bytes: bytes) -> list[Directive]:
    header = Header(*struct.unpack_from(HEADER_FORMAT, bytes))

    dirs = []
    idx = 0
    offset = HEADER_SIZE
    while idx < header.statementCount:
        offset_and_dir = Directive.deserialize(bytes, offset)
        if offset_and_dir is None:
            raise RuntimeError("Unable to deserialize sequence")
        offset, dir = offset_and_dir
        dirs.append(dir)
        idx += 1

    return dirs