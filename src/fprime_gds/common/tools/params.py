# author: zimri.leisher
# created on: Jan 27, 2025

# allow us to use bracketed types
from __future__ import annotations
import json as js
from pathlib import Path
from argparse import ArgumentParser
from typing import Any
from fprime_gds.common.loaders.prm_json_loader import PrmJsonLoader
from fprime_gds.common.templates.prm_template import PrmTemplate
from fprime_gds.common.models.serialize.type_base import BaseType
from fprime_gds.common.models.serialize.array_type import ArrayType
from fprime_gds.common.models.serialize.bool_type import BoolType
from fprime_gds.common.models.serialize.enum_type import EnumType
from fprime_gds.common.models.serialize.numerical_types import (
    F32Type,
    F64Type,
    I8Type,
    I16Type,
    I32Type,
    I64Type,
    U8Type,
    U16Type,
    U32Type,
    U64Type,
)
from fprime_gds.common.models.serialize.serializable_type import SerializableType
from fprime_gds.common.models.serialize.string_type import StringType

FW_PRM_ID_TYPE_SIZE = 4 # serialized size of the FwPrmIdType


def instantiate_prm_type(prm_val_json, prm_type: type[BaseType]):
    """given a parameter type and its value in json form, instantiate the type
    with the value, or raise an exception if the json is not compatible"""
    prm_instance = prm_type()
    if isinstance(prm_instance, BoolType):
        value = str(prm_val_json).lower().strip()
        if value in {"true", "yes"}:
            av = True
        elif value in {"false", "no"}:
            av = False
        else:
            raise RuntimeError("Param value is not a valid boolean")
        prm_instance.val = av
    elif isinstance(prm_instance, EnumType):
        prm_instance.val = prm_val_json
    elif isinstance(prm_instance, (F64Type, F32Type)):
        prm_instance.val = float(prm_val_json)
    elif isinstance(
        prm_instance,
        (I64Type, U64Type, I32Type, U32Type, I16Type, U16Type, I8Type, U8Type),
    ):
        prm_instance.val = int(prm_val_json, 0) if isinstance(prm_val_json, str) else int(prm_val_json)
    elif isinstance(prm_instance, StringType):
        prm_instance.val = prm_val_json
    elif isinstance(prm_instance, (ArrayType, SerializableType)):
        prm_instance.val = prm_val_json
    else:
        raise RuntimeError(
            "Param value could not be converted to type object"
        )
    return prm_instance


def parsed_json_to_dat(templates_and_values: list[tuple[PrmTemplate, Any]]) -> bytes:
    """convert a list of (PrmTemplate, prm value json) to serialized bytes for a PrmDb"""
    serialized = bytes()
    for template_and_value in templates_and_values:
        template, json_value = template_and_value
        prm_instance = instantiate_prm_type(json_value, template.prm_type_obj)

        prm_instance_bytes = prm_instance.serialize()

        # see https://github.com/nasa/fprime/blob/devel/Svc/PrmDb/docs/sdd.md#32-functional-description
        # for an explanation of the binary format of parameters in the .dat file

        # delimiter
        serialized += b"\xA5"

        record_size = FW_PRM_ID_TYPE_SIZE + len(prm_instance_bytes)

        # size of following data
        serialized += record_size.to_bytes(length=4, byteorder="big")
        # id of param
        serialized += template.prm_id.to_bytes(length=4, byteorder="big")
        # value of param
        serialized += prm_instance_bytes
    return serialized


def parsed_json_to_seq(templates_and_values: list[tuple[PrmTemplate, dict]], include_save=False) -> list[str]:
    """convert a list of (PrmTemplate, prm value json) to a command sequence for the CmdSequencer.
    Returns a list of lines in the sequence."""
    cmds = []
    cmds.append("; Autocoded sequence file from JSON")
    for template_and_value in templates_and_values:
        template, json_value = template_and_value
        set_cmd_name = template.comp_name + "." + template.prm_name.upper() + "_PRM_SET"
        cmd = "R00:00:00 " + set_cmd_name + " " + str(json_value)
        cmds.append(cmd)
        if include_save:
            save_cmd = template.comp_name + "." + template.prm_name.upper() + "_PRM_SAVE"
            cmds.append(save_cmd)
    return cmds



def parse_json(param_value_json, name_dict: dict[str, PrmTemplate], include_implicit_defaults=False) -> list[tuple[PrmTemplate, dict]]:
    """
    param_value_json: the json object read from the .json file
    name_dict: a dictionary of (fqn param name, PrmTemplate) pairs
    include_implicit_defaults: whether or not to also include default values from the name dict
                               if no value was specified in the json
    @return a list of tuple of param template and the intended param value (in form of json dict)
    """
    # first, check the json for errors
    for component_name in param_value_json:
        for param_name in param_value_json[component_name]:
            fqn_param_name = component_name + "." + param_name
            param_temp: PrmTemplate = name_dict.get(fqn_param_name, None)
            if not param_temp:
                raise RuntimeError(
                    "Unable to find param "
                    + fqn_param_name
                    + " in dictionary"
                )

    # okay, now iterate over the dict
    templates_to_values = []
    for fqn_param_name, prm_template in name_dict.items():

        prm_val = None

        if include_implicit_defaults:
            # there is a default value
            prm_val = prm_template.prm_default_val
        
        comp_json = param_value_json.get(prm_template.comp_name, None)
        if comp_json:
            # if there is an entry for the component
            if prm_template.prm_name in comp_json:
                # if there is an entry for this param
                # get the value
                prm_val = comp_json[prm_template.prm_name]
        
        if not prm_val:
            # not writing a val for this prm
            continue

        templates_to_values.append((prm_template, prm_val))

    return templates_to_values


def main_encode():
    """CLI entry point for fprime-prm-write (encoding).

    Encodes parameter JSON files into binary .dat files or command sequence .seq files.
    This is the inverse operation of fprime-prm-decode.
    """
    arg_parser = ArgumentParser()
    subparsers = arg_parser.add_subparsers(dest="subcmd", required=True)


    json_to_dat = subparsers.add_parser("dat", help="Compiles .json files into param DB .dat files")
    json_to_dat.add_argument(
        "json_file", type=Path, help="The .json file to turn into a .dat file", default=None
    )
    json_to_dat.add_argument(
        "--dictionary",
        "-d",
        type=Path,
        help="The dictionary file of the FSW",
        required=True,
    )
    json_to_dat.add_argument("--defaults", action="store_true", help="Whether or not to implicitly include default parameter values in the output")
    json_to_dat.add_argument("--output", "-o", type=Path, help="The output file", default=None)


    json_to_seq = subparsers.add_parser("seq", help="Converts .json files into command sequence .seq files")
    json_to_seq.add_argument(
        "json_file", type=Path, help="The .json file to turn into a .seq file", default=None
    )
    json_to_seq.add_argument(
        "--dictionary",
        "-d",
        type=Path,
        help="The dictionary file of the FSW",
        required=True,
    )
    json_to_seq.add_argument("--defaults", action="store_true", help="Whether or not to implicitly include default parameter values in the output")
    json_to_seq.add_argument("--save", action="store_true", help="Whether or not to include the PRM_SAVE cmd in the output")
    json_to_seq.add_argument("--output", "-o", type=Path, help="The output file", default=None)


    args = arg_parser.parse_args()

    if args.json_file is None or not args.json_file.exists():
        print("Unable to find", args.json_file)
        exit(1)

    if args.json_file.is_dir():
        print("json-file is a dir", args.json_file)
        exit(1)

    if not args.dictionary.exists():
        print("Unable to find", args.dictionary)
        exit(1)

    output_format = args.subcmd

    # just compile the one file in place
    if args.output is None:
        output_path = args.json_file.with_suffix("." + output_format)
    else:
        output_path = args.output

    # when using dat need a save attribute
    if not hasattr(args, "save"):
        args.save = False
    
    convert_json(args.json_file, args.dictionary, output_path, output_format, args.defaults, args.save)


def convert_json(json_file: Path, dictionary: Path, output: Path, output_format: str, implicit_defaults=False, include_save_cmd=False):

    print("Converting", json_file, "to", output, "(format: ." + output_format + ")")
    output.parent.mkdir(parents=True, exist_ok=True)

    json = js.loads(json_file.read_text())

    dict_parser = PrmJsonLoader(str(dictionary.resolve()))
    id_dict, name_dict, versions = dict_parser.construct_dicts(
        str(dictionary.resolve())
    )

    templates_to_values = parse_json(json, name_dict, implicit_defaults)

    if output_format == "dat":
        serialized_values = parsed_json_to_dat(templates_to_values)

        print("Done, writing to", output.resolve())
        output.write_bytes(serialized_values)
    elif output_format == "seq":
        sequence_cmds = parsed_json_to_seq(templates_to_values, include_save_cmd)
        print("Done, writing to", output.resolve())
        output.write_text("\n".join(sequence_cmds))
    else:
        raise RuntimeError("Invalid output format " + str(output_format))


def decode_dat_to_params(dat_bytes: bytes, id_dict: dict[int, PrmTemplate]) -> list[tuple[PrmTemplate, Any]]:
    """Decode a binary .dat file into a list of (PrmTemplate, value) tuples.

    Args:
        dat_bytes: The binary data from a .dat file
        id_dict: Dictionary mapping parameter IDs to PrmTemplate objects

    Returns:
        List of (PrmTemplate, value) tuples where value is in JSON-compatible format

    Raises:
        RuntimeError: If the file format is invalid or parameters cannot be decoded
    """
    params = []
    offset = 0

    while offset < len(dat_bytes):
        # Check for delimiter
        if dat_bytes[offset] != 0xA5:
            raise RuntimeError(
                f"Invalid delimiter at offset {offset}: expected 0xA5, got {dat_bytes[offset]:#x}"
            )
        offset += 1

        # Read record size (4 bytes, big endian)
        if offset + 4 > len(dat_bytes):
            raise RuntimeError(
                f"Incomplete record size at offset {offset}: expected 4 bytes, got {len(dat_bytes) - offset}"
            )
        record_size = int.from_bytes(dat_bytes[offset:offset+4], byteorder="big")
        offset += 4

        # Read parameter ID (4 bytes, big endian)
        if offset + 4 > len(dat_bytes):
            raise RuntimeError(
                f"Incomplete parameter ID at offset {offset}: expected 4 bytes, got {len(dat_bytes) - offset}"
            )
        param_id = int.from_bytes(dat_bytes[offset:offset+4], byteorder="big")
        offset += 4

        # Look up parameter template
        prm_template = id_dict.get(param_id, None)
        if not prm_template:
            raise RuntimeError(
                f"Unknown parameter ID {param_id} (0x{param_id:x}) at offset {offset-4}"
            )

        # Calculate the value size
        value_size = record_size - FW_PRM_ID_TYPE_SIZE

        # Check if we have enough data
        if offset + value_size > len(dat_bytes):
            raise RuntimeError(
                f"Incomplete parameter value for {prm_template.get_full_name()} at offset {offset}: "
                f"expected {value_size} bytes, got {len(dat_bytes) - offset}"
            )

        # Deserialize the value
        prm_instance = prm_template.prm_type_obj()
        try:
            prm_instance.deserialize(dat_bytes, offset)
        except Exception as e:
            raise RuntimeError(
                f"Failed to deserialize parameter {prm_template.get_full_name()} "
                f"(id={param_id}, type={prm_template.prm_type_obj.__name__}): {str(e)}"
            )

        # Get the raw value - use .val for simple types
        # For complex types (arrays, structs), to_jsonable() provides the correct format
        if isinstance(prm_instance, (ArrayType, SerializableType)):
            value = prm_instance.to_jsonable()
        else:
            # For simple types (string, bool, numbers, enums), use the raw value
            value = prm_instance.val

        params.append((prm_template, value))

        offset += value_size

    return params


def params_to_json(params: list[tuple[PrmTemplate, Any]]) -> dict:
    """Convert a list of (PrmTemplate, value) tuples to JSON format.

    The output format matches the input format expected by fprime-prm-write:
    {
        "componentName": {
            "paramName": value,
            ...
        },
        ...
    }

    Complex types from to_jsonable() are converted to simple format that
    instantiate_prm_type() expects for round-trip compatibility.

    Args:
        params: List of (PrmTemplate, value) tuples

    Returns:
        Dictionary in the JSON format used by fprime-prm-write
    """
    def to_encoder_format(value):
        """Convert to_jsonable() output to format expected by instantiate_prm_type()."""
        if value is None:
            return None

        # Handle lists recursively
        if isinstance(value, list):
            return [to_encoder_format(v) for v in value]

        # Only process dicts from here
        if not isinstance(value, dict):
            return value

        # Array: {"values": [...]} -> [...]
        if "values" in value and isinstance(value.get("values"), list):
            return [to_encoder_format(v) for v in value["values"]]

        # Any dict with "value" key (primitive wrapper or struct member) -> extract value
        if "value" in value:
            return to_encoder_format(value["value"])

        # Plain dict (struct without metadata): recursively process all fields
        return {k: to_encoder_format(v) for k, v in value.items()}

    result = {}

    for prm_template, value in params:
        comp_name = prm_template.comp_name
        prm_name = prm_template.prm_name

        # Create component entry if it doesn't exist
        if comp_name not in result:
            result[comp_name] = {}

        # Add parameter to component with encoder-compatible format
        result[comp_name][prm_name] = to_encoder_format(value)

    return result


def params_to_text(params: list[tuple[PrmTemplate, Any]]) -> str:
    """Convert a list of (PrmTemplate, value) tuples to human-readable text format.

    Args:
        params: List of (PrmTemplate, value) tuples

    Returns:
        Human-readable text string
    """
    lines = []
    current_component = None

    for prm_template, value in params:
        comp_name = prm_template.comp_name
        prm_name = prm_template.prm_name
        prm_id = prm_template.prm_id
        type_name = prm_template.prm_type_obj.__name__.replace("Type", "")

        # Add component header if this is a new component
        if comp_name != current_component:
            if current_component is not None:
                lines.append("")  # Blank line between components
            lines.append(f"Component: {comp_name}")
            current_component = comp_name

        # Format the value
        if isinstance(value, str):
            value_str = f'"{value}"'
        elif isinstance(value, (list, dict)):
            value_str = js.dumps(value)
        else:
            value_str = str(value)

        lines.append(f"  {prm_name} = {value_str} (type: {type_name}, id: {prm_id})")

    return "\n".join(lines)


def params_to_csv(params: list[tuple[PrmTemplate, Any]]) -> str:
    """Convert a list of (PrmTemplate, value) tuples to CSV format.

    Args:
        params: List of (PrmTemplate, value) tuples

    Returns:
        CSV string with columns: Component,Parameter,Value,Type,ID
    """
    lines = []
    lines.append("Component,Parameter,Value,Type,ID")

    for prm_template, value in params:
        comp_name = prm_template.comp_name
        prm_name = prm_template.prm_name
        prm_id = prm_template.prm_id
        type_name = prm_template.prm_type_obj.__name__.replace("Type", "")

        # Format the value for CSV
        # For complex types (arrays, structs), convert to JSON string
        if isinstance(value, (list, dict)):
            value_str = js.dumps(value)
        elif isinstance(value, str):
            # Escape quotes in strings
            value_str = value.replace('"', '""')
        else:
            value_str = str(value)

        # Escape any commas or quotes in the value
        if ',' in value_str or '"' in value_str or '\n' in value_str:
            value_str = f'"{value_str}"'

        lines.append(f"{comp_name},{prm_name},{value_str},{type_name},{prm_id}")

    return "\n".join(lines)


def main_decode():
    """CLI entry point for fprime-prm-decode (decoding).

    Decodes binary parameter database (.dat) files into human-readable formats.
    This is the inverse operation of fprime-prm-write.
    """
    arg_parser = ArgumentParser()

    arg_parser.add_argument(
        "dat_file", type=Path, help="The .dat file to decode", default=None
    )
    arg_parser.add_argument(
        "--dictionary",
        "-d",
        type=Path,
        help="The dictionary file of the FSW",
        required=True,
    )
    arg_parser.add_argument("--format", "-f", type=str, choices=["json", "text", "csv"], default="json", help="Output format (default: json)")
    arg_parser.add_argument("--output", "-o", type=Path, help="The output file", default=None)


    args = arg_parser.parse_args()

    if args.dat_file is None or not args.dat_file.exists():
        print("Unable to find", args.dat_file)
        exit(1)

    if args.dat_file.is_dir():
        print("dat-file is a dir", args.dat_file)
        exit(1)

    if not args.dictionary.exists():
        print("Unable to find", args.dictionary)
        exit(1)

    output_format = args.format

    # determine output path
    if args.output is None:
        output_path = args.dat_file.with_suffix("." + output_format)
    else:
        output_path = args.output

    print("Decoding", args.dat_file, "to", output_path, "(format: ." + output_format + ")")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load dictionary
    dict_parser = PrmJsonLoader(str(args.dictionary.resolve()))
    id_dict, name_dict, versions = dict_parser.construct_dicts(
        str(args.dictionary.resolve())
    )

    # Read and decode .dat file
    dat_bytes = args.dat_file.read_bytes()
    params = decode_dat_to_params(dat_bytes, id_dict)

    # Format output based on requested format
    if output_format == "json":
        output_data = params_to_json(params)
        output_content = js.dumps(output_data, indent=4)
    elif output_format == "text":
        output_content = params_to_text(params)
    elif output_format == "csv":
        output_content = params_to_csv(params)
    else:
        raise RuntimeError("Invalid output format " + str(output_format))

    # Write output
    print("Done, writing to", output_path.resolve())
    output_path.write_text(output_content)


if __name__ == "__main__":
    # This file was originally created to encode parameter database files
    # Keep this backwards compatibility
    main_encode()
