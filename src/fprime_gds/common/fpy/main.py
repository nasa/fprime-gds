from __future__ import annotations

import argparse
from pathlib import Path
import sys

from fprime_gds.common.fpy.bytecode.assembler import (
    assemble,
    directives_to_fpybc,
    parse as fpybc_parse,
)
import fprime_gds.common.fpy.error
from fprime_gds.common.fpy.types import (
    MAJOR_VERSION,
    MINOR_VERSION,
    PATCH_VERSION,
    SCHEMA_VERSION,
    deserialize_directives,
    serialize_directives,
)
import fprime_gds.common.fpy.model
from fprime_gds.common.fpy.model import DirectiveErrorCode, FpySequencerModel
from fprime_gds.common.fpy.compiler import text_to_ast, ast_to_directives


def human_readable_size(size_bytes):
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    unit_idx = 0
    while size_bytes >= 1024.0 and unit_idx < len(units) - 1:
        size_bytes /= 1024.0
        unit_idx += 1
    size_bytes = int(size_bytes)
    return f"{size_bytes} {units[unit_idx]}"

def get_description() -> str:
    return f"fprime-fpyc version {MAJOR_VERSION}.{MINOR_VERSION}.{PATCH_VERSION} schema {SCHEMA_VERSION}"


def compile_main(args: list[str] = None):
    arg_parser = argparse.ArgumentParser(description=get_description())
    arg_parser.add_argument("input", type=Path, help="The input .fpy file")
    arg_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=False,
        default=None,
        help="The output .bin path",
    )
    arg_parser.add_argument(
        "-d",
        "--dictionary",
        type=Path,
        required=True,
        help="The FPrime dictionary .json file",
    )
    arg_parser.add_argument(
        "-b",
        "--bytecode",
        action="store_true",
        default=False,
        help="Whether to output human-readable bytecode to stdout instead of binary",
    )
    arg_parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Pass this to print out compiler debugging information",
    )

    if args is not None:
        parsed_args = arg_parser.parse_args(args)
    else:
        parsed_args = arg_parser.parse_args()

    if parsed_args.debug:
        fprime_gds.common.fpy.error.debug = True

    if not parsed_args.input.exists():
        print(f"Input file {parsed_args.input} does not exist")
        sys.exit(1)
    fprime_gds.common.fpy.error.file_name = str(parsed_args.input)
    try:
        body = text_to_ast(parsed_args.input.read_text())
    except RecursionError:
        print("Recursion limit exceeded in parsing")
        sys.exit(1)
    try:
        directives = ast_to_directives(body, parsed_args.dictionary)
    except RecursionError:
        print("Recursion limit exceeded in compiling")
        sys.exit(1)
    if isinstance(
        directives,
        (
            fprime_gds.common.fpy.error.CompileError,
            fprime_gds.common.fpy.error.BackendError,
        ),
    ):
        print(directives)  # directives is an error
        sys.exit(1)

    output = parsed_args.output
    if output is None:
        output = parsed_args.input.with_suffix(".bin")
    if parsed_args.bytecode:
        fpybc = directives_to_fpybc(directives)
        print(fpybc)
    else:
        output_bytes, crc = serialize_directives(directives)
        output.write_bytes(output_bytes)
        print(f"{output}\nCRC {hex(crc)} size {human_readable_size(len(output_bytes))}")


def model_main(args: list[str] = None):
    arg_parser = argparse.ArgumentParser(description=get_description())
    arg_parser.add_argument("input", type=Path, help="The input .bin file")
    arg_parser.add_argument(
        "--debug",
        action="store_true",
        help="Whether or not to print debug info during sequence execution",
    )

    if args is not None:
        args = arg_parser.parse_args(args)
    else:
        args = arg_parser.parse_args()

    if not args.input.exists():
        print(f"Input file {args.input} does not exist")
        sys.exit(1)

    if args.debug:
        fprime_gds.common.fpy.model.debug = True

    directives = deserialize_directives(args.input.read_bytes())
    model = FpySequencerModel()
    ret = model.run(directives)
    if ret != DirectiveErrorCode.NO_ERROR:
        print("Sequence failed with " + str(ret))
        exit(1)


def assemble_main(args: list[str] = None):
    arg_parser = argparse.ArgumentParser(description=get_description())
    arg_parser.add_argument("input", type=Path, help="The input .fpybc file")
    arg_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=False,
        default=None,
        help="The output .bin path",
    )

    if args is not None:
        args = arg_parser.parse_args(args)
    else:
        args = arg_parser.parse_args()

    if not args.input.exists():
        print(f"Input file {args.input} does not exist")
        exit(1)

    body = fpybc_parse(args.input.read_text())
    directives = assemble(body)
    output = args.output
    if output is None:
        output = args.input.with_suffix(".bin")
    output_bytes, crc = serialize_directives(directives)
    output.write_bytes(output_bytes)
    print(f"{output}\nCRC {hex(crc)} size {human_readable_size(len(output_bytes))}")


def disassemble_main(args: list[str] = None):
    arg_parser = argparse.ArgumentParser(description=get_description())
    arg_parser.add_argument("input", type=Path, help="The input .bin file")
    arg_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=False,
        default=None,
        help="The output .fpybc path",
    )

    if args is not None:
        args = arg_parser.parse_args(args)
    else:
        args = arg_parser.parse_args()

    if not args.input.exists():
        print(f"Input file {args.input} does not exist")
        exit(1)

    dirs = deserialize_directives(args.input.read_bytes())
    fpybc = directives_to_fpybc(dirs)
    output = args.output
    if output is None:
        output = args.input.with_suffix(".fpybc")
    output.write_text(fpybc)
    print("Done")
