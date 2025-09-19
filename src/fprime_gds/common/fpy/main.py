import argparse
from pathlib import Path

from fprime_gds.common.fpy.bytecode.assembler import deserialize_directives
import fprime_gds.common.fpy.model
from fprime_gds.common.fpy.model import DirectiveErrorCode, FpySequencerModel
from fprime_gds.common.fpy.parser import parse
from fprime_gds.common.fpy.codegen import compile, serialize_directives
import fprime_gds.common.fpy.error

def human_readable_size(size_bytes, decimal_places=2):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if size_bytes < 1024.0:
            break
        size_bytes /= 1024.0
    size_bytes = int(size_bytes)
    return f"{size_bytes} {unit}"

def compile_main():
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
        "--debug",
        action="store_true",
        default=False,
        help="Pass this to print out compiler debugging information",
    )

    args = arg_parser.parse_args()

    if args.debug:
        fprime_gds.common.fpy.error.debug = True

    if not args.input.exists():
        print(f"Input file {args.input} does not exist")
        exit(-1)

    fprime_gds.common.fpy.error.file_name = str(args.input)
    body = parse(args.input.read_text())
    directives = compile(body, args.dictionary)
    output = args.output
    if output is None:
        output = args.input.with_suffix(".bin")
    output_bytes, crc = serialize_directives(directives)
    output.write_bytes(output_bytes)
    print(f"{output}\nCRC {hex(crc)} size {human_readable_size(len(output_bytes))}")



def model_main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("input", type=Path, help="The input .bin file")
    arg_parser.add_argument(
        "--debug",
        action="store_true",
        help="Whether or not to print debug info during sequence execution",
    )

    args = arg_parser.parse_args()

    if not args.input.exists():
        print(f"Input file {args.input} does not exist")
        exit(-1)

    if args.debug:
        fprime_gds.common.fpy.model.debug = True

    directives = deserialize_directives(args.input.read_bytes())
    model = FpySequencerModel()
    ret = model.run(directives)
    if ret != DirectiveErrorCode.NO_ERROR:
        print("Sequence failed with " + str(ret))
