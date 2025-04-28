from __future__ import annotations
from dataclasses import astuple
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
    FPY_DIRECTIVES
)
from fprime_gds.common.loaders.cmd_json_loader import CmdJsonLoader
from fprime.common.models.serialize.numerical_types import (
    U8Type,
    U16Type,
    U32Type,
)
from fprime.common.models.serialize.type_base import ValueType


def get_type_obj_for(type: str) -> type[ValueType]:
    """returns a type object representing the ValueType that corresponds to a type alias"""
    if type == "FwOpcodeType":
        return U32Type
    elif type == "FwSizeStoreType":
        return U16Type

    raise RuntimeError("Unknown FPrime type alias " + str(type))


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
    stmt: str, templates: list[StatementTemplate]
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
        arg_value = arg_type(arg_json)
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
        required=True
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

def serialize_bytecode(input: Path, dictionary: Path, output: Path=None):
    """Given an input .fpybc file, and a dictionary .json file, converts the 
    bytecode file into binary and writes it to the output file. If the output file 
    is None, writes it to the input file with a .bin extension"""
    cmd_json_dict_loader = CmdJsonLoader(str(dictionary))
    (cmd_id_dict, cmd_name_dict, versions) = cmd_json_dict_loader.construct_dicts(
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

    stmts = []

    for line_idx, line in enumerate(input.read_text().splitlines()):
        line = line.strip()
        if line.startswith(";") or len(line) == 0:
            # ignore comments, empty lines
            continue
        try:
            stmt_data = parse_str_as_statement(line, stmt_templates)
            stmts.append(stmt_data)
        except BaseException as e:
            raise RuntimeError(
                "Exception while parsing line " + str(line_idx + 1)
            ) from e

    output_bytes = bytes()

    for stmt in stmts:
        output_bytes += serialize_statement(stmt)

    header = Header(0, 0, 0, 1, 0, len(stmts), len(output_bytes))
    output_bytes = struct.pack(HEADER_FORMAT, *astuple(header)) + output_bytes

    crc = zlib.crc32(output_bytes) % (1 << 32)
    footer = Footer(crc)
    output_bytes += struct.pack(FOOTER_FORMAT, *astuple(footer))

    if output is None:
        output = input.with_suffix(".bin")

    output.write_bytes(output_bytes)


if __name__ == "__main__":
    main()
