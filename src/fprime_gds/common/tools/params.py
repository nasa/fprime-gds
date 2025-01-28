# author: zimri.leisher
# created on: Jan 27, 2025

# allow us to use bracketed types
from __future__ import annotations
import json as js
from pathlib import Path
from argparse import ArgumentParser
from fprime_gds.common.loaders.prm_json_loader import PrmJsonLoader
from fprime_gds.common.templates.prm_template import PrmTemplate
from fprime.common.models.serialize.type_base import BaseType
from fprime.common.models.serialize.array_type import ArrayType
from fprime.common.models.serialize.bool_type import BoolType
from fprime.common.models.serialize.enum_type import EnumType
from fprime.common.models.serialize.numerical_types import (
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
from fprime.common.models.serialize.serializable_type import SerializableType
from fprime.common.models.serialize.string_type import StringType


def instantiate_prm_type(prm_val_json, prm_type):
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


def parsed_json_to_dat(templates_and_values: list[tuple[PrmTemplate, dict]]) -> bytes:
    serialized = bytes()
    for template_and_value in templates_and_values:
        template, json_value = template_and_value
        prm_instance = instantiate_prm_type(json_value, template.prm_type_obj)

        prm_instance_bytes = prm_instance.serialize()

        # delimiter
        serialized += b"\xA5"

        record_size = 4 + len(prm_instance_bytes)

        # size of following data
        serialized += record_size.to_bytes(length=4, byteorder="big")
        # id of param
        serialized += template.prm_id.to_bytes(length=4, byteorder="big")
        # value of param
        serialized += prm_instance_bytes
    return serialized


def parsed_json_to_seq(templates_and_values: list[tuple[PrmTemplate, dict]], include_save=False) -> list[str]:
    cmds = []
    cmds.append("; Autocoded sequence file from JSON")
    for template_and_value in templates_and_values:
        template, json_value = template_and_value
        set_cmd_name = template.comp_name + "." + template.prm_name.upper() + "_PARAM_SET"
        cmd = "R00:00:00 " + set_cmd_name + " " + str(json_value)
        cmds.append(cmd)
        if include_save:
            save_cmd = template.comp_name + "." + template.prm_name.upper() + "_PARAM_SAVE"
            cmds.append(save_cmd)
    return cmds



def parse_json(json, name_dict: dict[str, PrmTemplate], include_implicit_defaults=False) -> list[tuple[PrmTemplate, dict]]:
    """
    json: the json object read from the .json file
    name_dict: a dictionary of (fqn param name, PrmTemplate) pairs
    include_implicit_defaults: whether or not to also include default values from the name dict
                               if no value was specified in the json
    @return a list of tuple of param template and the intended param value (in form of json dict)
    """
    # first, check the json for errors
    for component_name in json:
        for param_name in json[component_name]:
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
        
        comp_json = json.get(prm_template.comp_name, None)
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


def main():
    arg_parser = ArgumentParser()
    subparsers = arg_parser.add_subparsers(dest="subcmd")


    json_to_dat = subparsers.add_parser("json-to-dat", description="Compiles .json files into param DB .dat files")
    json_to_dat.add_argument(
        "json_file", type=Path, help="The .json file to turn into a .dat file"
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


    json_to_seq = subparsers.add_parser("json-to-seq", description="Converts .json files into command sequence .seq files")
    json_to_seq.add_argument(
        "json_file", type=Path, help="The .json file to turn into a .seq file"
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

    if not args.json_file.exists():
        print("Unable to find", args.json_file)
        exit(1)

    if args.json_file.is_dir():
        print("json-file is a dir", args.json_file)
        exit(1)

    if not args.dictionary.exists():
        print("Unable to find", args.dictionary)
        exit(1)

    output_format = "dat" if args.subcmd == "json-to-dat" else "seq"

    # just compile the one file in place
    if args.output is None:
        output_path = args.json_file.with_suffix("." + output_format)
    else:
        output_path = args.output
    
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


if __name__ == "__main__":
    main()