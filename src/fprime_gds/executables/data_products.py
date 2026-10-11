import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional

from fprime_gds.common.models.dictionaries import Dictionaries
from fprime_gds.common.dp.decoder import DataProductDecoder
from fprime_gds.common.dp.validator import DataProductValidator

# Matches the container id in file names produced by Svc::DpWriter (see DP_FILENAME_FORMAT in
# DpCfg.hpp): Dp_<container id>_<seconds>_<microseconds>.fdp. Searched rather than anchored so that
# downlinked copies, whose names are the sanitized flight path (e.g. ._DpCat_Dp_<id>_...), also match.
DP_CONTAINER_ID_PATTERN = re.compile(r"Dp_(?P<id>\d+)_")


def renamed_output_path(dictionaries: Dictionaries, bin_file: Path) -> Optional[Path]:
    """Compute the output path for --rename-id, replacing the container id with the container name.

    Returns None when the file name does not follow the DpWriter naming convention or the container
    id is not present in the dictionary. The caller falls back to the default output path.
    """
    stem = bin_file.stem
    match = DP_CONTAINER_ID_PATTERN.search(stem)
    if match is None:
        print(f"Warning: {bin_file.name} does not match Dp_<id>_<sec>_<usec> naming, keeping file name", file=sys.stderr)
        return None
    container_id = int(match.group("id"))
    container = dictionaries.dp_container_id.get(container_id)
    if container is None:
        print(f"Warning: container id {container_id} ({bin_file.name}) not found in dictionary, keeping file name", file=sys.stderr)
        return None
    renamed_stem = f"{stem[:match.start()]}Dp_{container.get_name()}_{stem[match.end():]}"
    return bin_file.with_name(f"{renamed_stem}.json")


def decode_files(dictionaries: Dictionaries, bin_files: List[Path], output: Optional[str], disable_decompression: bool, rename_id: bool) -> int:
    """Decode each binary file, continuing past failures. Returns the number of failures."""
    failures = 0
    written = {}
    for bin_file in bin_files:
        output_path = output
        if output_path is None and rename_id:
            renamed = renamed_output_path(dictionaries, bin_file)
            output_path = str(renamed) if renamed is not None else None
        resolved_output = Path(output_path if output_path is not None else bin_file.with_suffix(".json")).resolve()
        if resolved_output in written:
            print(f"Error: skipping {bin_file}: output {resolved_output} already written from {written[resolved_output]}", file=sys.stderr)
            failures += 1
            continue
        written[resolved_output] = bin_file
        try:
            success = DataProductDecoder(dictionaries, str(bin_file), output_path, disable_decompression).process()
        except Exception as e:
            print(f"Error: failed to decode {bin_file}: {e}", file=sys.stderr)
            success = False
        if not success:
            failures += 1
    return failures


def main():
    root_parser = argparse.ArgumentParser(description='Data Product CLI')
    subcommands_parser = root_parser.add_subparsers(dest='command')

    decode_parser = subcommands_parser.add_parser('decode', help='Decode a data product binary into a human-readable format')
    decode_input = decode_parser.add_mutually_exclusive_group(required=True)
    decode_input.add_argument("-b", "--bin-file", help="Path to input data product binary file (.fdp)")
    decode_input.add_argument("-B", "--bin-dir", help="Directory of data product binary files; every *.fdp file in it is decoded to <binFilename>.json")
    decode_parser.add_argument("-d", "--dictionary", required=True, help="Path to F Prime JSON Dictionary")
    decode_parser.add_argument("-o", "--output", required=False, help="Path to output JSON file (defaults to <binFilename>.json). Not allowed with --bin-dir")
    decode_parser.add_argument("-r", "--rename-id", action='store_true', help="Name output files Dp_<containerName>_<sec>_<usec>.json instead of Dp_<containerId>_<sec>_<usec>.json, using the dictionary")
    decode_parser.add_argument("-z", "--disable-decompression", action='store_true', help="Disable automatic decompression of data products")

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
        if args.bin_dir is not None:
            if args.output is not None:
                decode_parser.error("--output cannot be used with --bin-dir")
            bin_dir = Path(args.bin_dir)
            if not bin_dir.is_dir():
                decode_parser.error(f"{args.bin_dir} is not a directory")
            bin_files = sorted(path for path in bin_dir.glob("*.fdp") if path.is_file())
            if not bin_files:
                print(f"No .fdp files found in {bin_dir}", file=sys.stderr)
                return 1
        else:
            bin_files = [Path(args.bin_file)]
        failures = decode_files(args.dictionaries, bin_files, args.output, args.disable_decompression, args.rename_id)
        if args.bin_dir is not None:
            print(f"Decoded {len(bin_files) - failures}/{len(bin_files)} data products")
        return 1 if failures else 0

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
    sys.exit(main())
