import argparse
import os

from fprime_gds.executables.cli import DictionaryParser
from fprime_gds.common.dp.new_parser import DataProductParser
from fprime_gds.common.dp.parser import DataProductParser as DataProductParserOld
from fprime_gds.common.dp.validator import DataProductValidator


def main():
    root_parser = argparse.ArgumentParser(description='Data Product CLI')
    subcommands_parser = root_parser.add_subparsers(dest='command')

    write_parser = subcommands_parser.add_parser('parse', help='Parse a data product binary into a human-readable format')
    write_parser.add_argument("-b", "--binFile", required=True, help="Path to input data product binary file (.fdp)")
    write_parser.add_argument("-d", "--dictionary", required=True, help="Path to F Prime JSON Dictionary")
    write_parser.add_argument("-o", "--output", required=False, help="Path to output JSON file (defaults to <binFilename>.json)")
    write_parser.add_argument("--old", required=False, action="store_true")

    validate_parser = subcommands_parser.add_parser('validate', help='Validate a data product')
    validate_parser.add_argument("-b", "--binFile", required=True, help="Path to input data product binary file (.fdp)")
    validate_parser.add_argument("-d", "--dictionary", required=False, help="Path to F Prime JSON Dictionary")
    validate_parser.add_argument("-s", "--header-size", type=int, default=0, help="Use the provided value as the header size for the data product")
    validate_parser.add_argument("-g", "--guess-size", action="store_true", help="Guess at the header size")
    validate_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = root_parser.parse_args()

    # If a dictionary is passed, load it into ConfigManager
    if args.dictionary:
        DictionaryParser().handle_arguments(args)

    if args.command == "parse":
        if args.old:
            DataProductParserOld(args.dictionary, args.binFile, args.output).process()
        else:
            DataProductParser(args.binFile, args.output).parse()


    elif args.command == "validate":
        success = DataProductValidator(
            dictionary=args.dictionary,
            header_size=args.header_size if args.header_size > 0 else None,
            guess_size=args.guess_size,
            verbose=args.verbose
        ).process(args.binFile)

        return 0 if success else 1

    return 0


# For debugging
if __name__ == "__main__":
    import sys
    sys.exit(main())
