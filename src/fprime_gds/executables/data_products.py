import argparse

from fprime_gds.common.models.dictionaries import Dictionaries
from fprime_gds.common.dp.decoder import DataProductDecoder
from fprime_gds.common.dp.validator import DataProductValidator


def main():
    root_parser = argparse.ArgumentParser(description='Data Product CLI')
    subcommands_parser = root_parser.add_subparsers(dest='command')

    decode_parser = subcommands_parser.add_parser('decode', help='Decode a data product binary into a human-readable format')
    decode_parser.add_argument("-b", "--bin-file", required=True, help="Path to input data product binary file (.fdp)")
    decode_parser.add_argument("-d", "--dictionary", required=True, help="Path to F Prime JSON Dictionary")
    decode_parser.add_argument("-o", "--output", required=False, help="Path to output JSON file (defaults to <binFilename>.json)")

    validate_parser = subcommands_parser.add_parser('validate', help='Validate a data product')
    validate_parser.add_argument("-b", "--bin-file", required=True, help="Path to input data product binary file (.fdp)")
    validate_parser.add_argument("-d", "--dictionary", required=False, help="Path to F Prime JSON Dictionary")
    validate_parser.add_argument("-s", "--header-size", type=int, default=0, help="Use the provided value as the header size for the data product")
    validate_parser.add_argument("-g", "--guess-size", action="store_true", help="Guess at the header size")
    validate_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = root_parser.parse_args()

    # If a dictionary is passed, load it into ConfigManager and add to args for convenient access
    if args.dictionary:
        args.dictionaries = Dictionaries.load_dictionaries_into_config(args.dictionary)

    if args.command == "decode":
        assert args.dictionaries is not None, "Dictionaries must be loaded"
        DataProductDecoder(args.dictionaries, args.bin_file, args.output).process()

    elif args.command == "validate":
        success = DataProductValidator(
            dictionary=args.dictionary,
            header_size=args.header_size if args.header_size > 0 else None,
            guess_size=args.guess_size,
            verbose=args.verbose
        ).process(args.bin_file)

        return 0 if success else 1

    return 0


# For debugging
if __name__ == "__main__":
    import sys
    sys.exit(main())
