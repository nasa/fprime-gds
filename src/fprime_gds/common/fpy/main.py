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
    CompileArg,
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


_TRUE_STRINGS = {"1", "true", "yes", "on"}
_FALSE_STRINGS = {"0", "false", "no", "off", ""}


def _coerce_flag_value(raw_value: str | None) -> object:
    if raw_value is None:
        return True
    normalized = raw_value.strip().lower()
    if normalized in _TRUE_STRINGS:
        return True
    if normalized in _FALSE_STRINGS:
        return False
    return raw_value


def _normalize_flag_name(name: str) -> CompileArg | str:
    candidate = name.strip()
    if candidate == "":
        raise ValueError("Compile flag name cannot be empty")
    candidate_normalized = candidate.replace("-", "_")
    try:
        return CompileArg[candidate_normalized]
    except KeyError:
        try:
            return CompileArg[candidate_normalized.upper()]
        except KeyError:
            try:
                return CompileArg(candidate_normalized)
            except ValueError:
                return candidate


def _build_compile_args(entries: list[str] | None) -> dict:
    compile_args = {}
    if not entries:
        return compile_args

    for entry in entries:
        name, value = entry, None
        if "=" in entry:
            name, value = entry.split("=", 1)
        normalized_flag = _normalize_flag_name(name)
        coerced_value = _coerce_flag_value(value)
        compile_args[normalized_flag] = coerced_value

    return compile_args


def compile_main(args: list[str] = None):
    arg_parser = argparse.ArgumentParser()
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
    arg_parser.add_argument(
        "--flag",
        metavar="NAME[=VALUE]",
        action="append",
        default=[],
        help="Set a compiler flag (repeatable). Recognized: NO_OPERATOR_CONST_FOLDING.",
    )

    if args is not None:
        parsed_args = arg_parser.parse_args(args)
    else:
        parsed_args = arg_parser.parse_args()

    if parsed_args.debug:
        fprime_gds.common.fpy.error.debug = True

    if not parsed_args.input.exists():
        print(f"Input file {parsed_args.input} does not exist")
        sys.exit(-1)

    try:
        compile_args = _build_compile_args(parsed_args.flag)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        sys.exit(2)

    fprime_gds.common.fpy.error.file_name = str(parsed_args.input)
    body = text_to_ast(parsed_args.input.read_text())
    directives = ast_to_directives(body, parsed_args.dictionary, compile_args)
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
    arg_parser = argparse.ArgumentParser()
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
        sys.exit(-1)

    if args.debug:
        fprime_gds.common.fpy.model.debug = True

    directives = deserialize_directives(args.input.read_bytes())
    model = FpySequencerModel()
    ret = model.run(directives)
    if ret != DirectiveErrorCode.NO_ERROR:
        print("Sequence failed with " + str(ret))
        exit(1)


def assemble_main(args: list[str] = None):
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

    if args is not None:
        args = arg_parser.parse_args(args)
    else:
        args = arg_parser.parse_args()

    if not args.input.exists():
        print(f"Input file {args.input} does not exist")
        exit(-1)

    body = fpybc_parse(args.input.read_text())
    directives = assemble(body)
    output = args.output
    if output is None:
        output = args.input.with_suffix(".bin")
    output_bytes, crc = serialize_directives(directives)
    output.write_bytes(output_bytes)
    print(f"{output}\nCRC {hex(crc)} size {human_readable_size(len(output_bytes))}")


def disassemble_main(args: list[str] = None):
    arg_parser = argparse.ArgumentParser()
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
        exit(-1)

    dirs = deserialize_directives(args.input.read_bytes())
    fpybc = directives_to_fpybc(dirs)
    output = args.output
    if output is None:
        output = args.input.with_suffix(".fpybc")
    output.write_text(fpybc)
    print("Done")
