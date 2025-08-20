from dataclasses import astuple, dataclass
import struct
import zlib
from fprime_gds.common.fpy.bytecode.directives import Directive
from fprime_gds.common.fpy.bytecode.parser import (
    AstBody,
    AstDirStmt,
    AstGotoTagStmt,
    parse,
)
import argparse
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


@dataclass
class Footer:
    crc: int

def serialize_directives(dirs: list[Directive], output: Path):
    output_bytes = bytes()

    for dir in dirs:
        output_bytes += dir.serialize()

    header = Header(0, 0, 0, 1, 0, len(dirs), len(output_bytes))
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


def assemble(body: AstBody):
    directive_idx = 0
    gotos: dict[str, int] = {}
    for stmt in body:
        if isinstance(stmt, AstGotoTagStmt):
            gotos[stmt.tag] = directive_idx + 1
        else:
            assert isinstance(stmt, AstDirStmt), stmt
            directive_idx += 1


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("input", type=Path, help="The input .fpybc file")
    arg_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=False,
        default=None,
        help="The output .bin path",
    )

    args = arg_parser.parse_args()

    if not args.input.exists():
        print(f"Input file {args.input} does not exist")
        exit(-1)

    body = parse(args.input.read_text())
    directives = assemble(body)
    output = args.output
    if output is None:
        output = args.input.with_suffix(".bin")
    serialize_directives(directives, output)
