from __future__ import annotations
from dataclasses import astuple
import inspect
import json
from pathlib import Path
from argparse import ArgumentParser
import struct
import zlib
from fprime_gds.common.fpy.types import (
    StatementTemplate,
    StatementData,
    Header,
    Footer,
    HEADER_FORMAT,
    FOOTER_FORMAT,
    StatementType,
    FPY_DIRECTIVES,
    BytecodeParseContext,
    get_type_obj_for,
)
from fprime_gds.common.loaders.ch_json_loader import ChJsonLoader
from fprime_gds.common.loaders.cmd_json_loader import CmdJsonLoader
from fprime.common.models.serialize.numerical_types import (
    U8Type,
)

from fprime_gds.common.loaders.prm_json_loader import PrmJsonLoader


def serialize_statement(stmt: StatementData) -> bytes:
    """converts a StatementData object into bytes that the FpySequencer can read"""
    # see https://github.com/nasa/fprime/issues/3023#issuecomment-2693051677
    # TODO replace this with actual documentation

    # type: U8 (0 if directive, 1 if cmd)
    # opcode: FwOpcodeType (default U32)
    # argBufSize: FwSizeStoreType (default U16)
    # argBuf: X bytes

    output = bytes()
    output += U8Type(stmt.template.statement_type.value).serialize()
    output += get_type_obj_for("FwOpcodeType")(stmt.template.opcode).serialize()

    arg_bytes = bytes()
    for arg in stmt.arg_values:
        arg_bytes += arg.serialize()

    output += get_type_obj_for("FwSizeStoreType")(len(arg_bytes)).serialize()
    output += arg_bytes

    return output


def parse_str_as_statement(
    stmt: str, templates: list[StatementTemplate], context: BytecodeParseContext
) -> StatementData:
    """Converts a human-readable line of bytecode into a StatementData instance, given a list of
    possible statement templates"""
    name = stmt.split()[0]
    args = stmt[len(name) :]

    args = json.loads("[" + args + "]")

    matching_template = [t for t in templates if t.name == name]
    if len(matching_template) != 1:
        # no unique match
        if len(matching_template) == 0:
            raise RuntimeError("Could not find command or directive " + str(name))
        raise RuntimeError(
            "Found multiple commands or directives with name " + str(name)
        )
    matching_template = matching_template[0]

    arg_values = []
    if len(args) < len(matching_template.args):
        raise RuntimeError(
            "Missing arguments for statement "
            + str(matching_template.name)
            + ": "
            + str(matching_template.args[len(args) :])
        )
    if len(args) > len(matching_template.args):
        raise RuntimeError(
            "Extra arguments for"
            + str(matching_template.name)
            + ": "
            + str(args[len(matching_template.args) :])
        )
    for index, arg_json in enumerate(args):
        arg_type = matching_template.args[index]
        if inspect.isclass(arg_type):
            # it's a type. instantiate it with the json
            arg_value = arg_type(arg_json)
        else:
            # it's a function. give it the json and the ctx
            arg_value = arg_type(arg_json, context)
        arg_values.append(arg_value)

    return StatementData(matching_template, arg_values)


def main():
    arg_parser = ArgumentParser()
    arg_parser.add_argument(
        "input", type=Path, help="The path to the input .fpybc file"
    )

    arg_parser.add_argument(
        "-d",
        "--dictionary",
        type=Path,
        help="The JSON topology dictionary to compile against",
        required=True,
    )

    arg_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="The output .bin file path. Defaults to the input file path with a .bin extension",
        default=None,
    )

    args = arg_parser.parse_args()

    if not args.input.exists():
        print("Input file", args.input, "does not exist")
        exit(1)

    if not args.dictionary.exists():
        print("Dictionary file", args.dictionary, "does not exist")
        exit(1)

    serialize_bytecode(args.input, args.dictionary, args.output)


def serialize_bytecode(input: Path, dictionary: Path, output: Path = None):
    """Given an input .fpybc file, and a dictionary .json file, converts the
    bytecode file into binary and writes it to the output file. If the output file
    is None, writes it to the input file with a .bin extension"""
    cmd_json_dict_loader = CmdJsonLoader(str(dictionary))
    (_, cmd_name_dict, _) = cmd_json_dict_loader.construct_dicts(
        str(dictionary)
    )

    stmt_templates = []
    stmt_templates.extend(FPY_DIRECTIVES)
    for cmd_template in cmd_name_dict.values():
        stmt_template = StatementTemplate(
            StatementType.CMD,
            cmd_template.opcode,
            cmd_template.get_full_name(),
            [arg[2] for arg in cmd_template.arguments],
        )
        stmt_templates.append(stmt_template)

    tlm_json_loader = ChJsonLoader(str(dictionary))
    (_, tlm_name_dict, _) = tlm_json_loader.construct_dicts(
        str(dictionary)
    )

    prm_json_loader = PrmJsonLoader(str(dictionary))
    (_, prm_name_dict, _) = prm_json_loader.construct_dicts(
        str(dictionary)
    )

    context = BytecodeParseContext()
    context.types = cmd_json_dict_loader.parsed_types
    context.channels = tlm_name_dict
    context.params = prm_name_dict

    input_lines = input.read_text().splitlines()
    input_lines = [line.strip() for line in input_lines]
    # remove comments and empty lines
    input_lines = [
        line for line in input_lines if not line.startswith(";") and len(line) > 0
    ]

    goto_tags = {}
    stmt_idx = 0
    statement_strs: list[str] = []
    for stmt in input_lines:
        if stmt.endswith(":"):
            # it's a goto tag
            goto_tags[stmt[:-1]] = stmt_idx
        else:
            statement_strs.append(stmt)
            stmt_idx += 1

    context.goto_tags = goto_tags

    statements: list[StatementData] = []
    for stmt_idx, stmt in enumerate(statement_strs):
        try:
            stmt_data = parse_str_as_statement(stmt, stmt_templates, context)
            statements.append(stmt_data)
        except BaseException as e:
            raise RuntimeError(
                "Exception while parsing statement index " + str(stmt_idx) + ": " + stmt
            ) from e

    # perform some checks for things we know will fail
    for stmt in statements:
        if stmt.template.name == "GOTO":
            if stmt.arg_values[0].val > len(statements):
                raise RuntimeError(
                    f"GOTO index is outside the valid range for this sequence (was {stmt.arg_values[0].val}, should be <{len(statements)})"
                )

    output_bytes = bytes()

    for stmt in statements:
        output_bytes += serialize_statement(stmt)

    header = Header(0, 0, 0, 1, 0, len(statements), len(output_bytes))
    output_bytes = struct.pack(HEADER_FORMAT, *astuple(header)) + output_bytes

    crc = zlib.crc32(output_bytes) % (1 << 32)
    footer = Footer(crc)
    output_bytes += struct.pack(FOOTER_FORMAT, *astuple(footer))

    if output is None:
        output = input.with_suffix(".bin")

    output.write_bytes(output_bytes)


if __name__ == "__main__":
    main()
