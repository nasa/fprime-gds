import argparse
from pathlib import Path

from fprime_gds.common.fpy.parser import parse
from fprime_gds.common.fpy.codegen import compile
from fprime_gds.common.fpy.bytecode.directives import serialize_directives


def main():
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

    args = arg_parser.parse_args()

    if not args.input.exists():
        print(f"Input file {args.input} does not exist")
        exit(-1)

    body = parse(args.input.read_text())
    directives = compile(body, args.dictionary)
    output = args.output
    if output is None:
        output = args.input.with_suffix(".bin")
    serialize_directives(directives, output)
    print("Done")