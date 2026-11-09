import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional

from fprime_gds.common.models.dictionaries import Dictionaries
from fprime_gds.common.dp.comlog import CHANNEL_LOG_NAME, DEFAULT_SENTRY, EVENT_LOG_NAME, ComLoggerDpDecoder, write_collected_logs, write_json, write_text
from fprime_gds.common.dp.decoder import DataProductDecoder
from fprime_gds.common.dp.validator import DataProductValidator

# Matches the container id in file names produced by Svc::DpWriter (see DP_FILENAME_FORMAT in
# DpCfg.hpp): Dp_<container id>_<seconds>_<microseconds>.fdp. Searched rather than anchored so that
# downlinked copies, whose names are the sanitized flight path (e.g. ._DpCat_Dp_<id>_...), also match.
DP_CONTAINER_ID_PATTERN = re.compile(r"Dp_(?P<id>\d+)_")


def renamed_output_path(dictionaries: Dictionaries, bin_file: Path) -> Optional[Path]:
    """Compute the output path for --rename-id, replacing `Dp_<container id>` with the container's short name.

    For `Dp_00002576_01791745803_00594527.fdp` and container `Ref.dpDemo.DpDemoContainer` the output is
    `DpDemoContainer_01791745803_00594527.json`.

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
    short_name = container.get_name().rsplit(".", 1)[-1]
    renamed_stem = f"{stem[:match.start()]}{short_name}_{stem[match.end():]}"
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
        try:
            success = DataProductDecoder(dictionaries, str(bin_file), output_path, disable_decompression).process()
        except Exception as e:
            print(f"Error: failed to decode {bin_file}: {e}", file=sys.stderr)
            success = False
        if success:
            written[resolved_output] = bin_file
        else:
            failures += 1
    return failures


def u32_argument(value: str) -> int:
    """argparse type for a decimal or 0x-prefixed U32"""
    number = int(value, 0)
    if not 0 <= number <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError(f"{value} is not an unsigned 32-bit value")
    return number


def comlog_files(decoder: ComLoggerDpDecoder, bin_files: List[Path], args, output: Optional[Path]) -> int:
    """Decode (or reconstruct) each ComLoggerDp product and write the requested outputs. Returns the number of failures.

    `output` is a directory with --bin-dir or --collect and an output path with --bin-file.
    """
    failures = 0
    skipped = 0
    results = []
    for bin_file in bin_files:
        try:
            result = decoder.reconstruct(bin_file) if args.reconstruct else decoder.decode(bin_file)
        except Exception as e:
            print(f"Error: failed to decode {bin_file}: {e}", file=sys.stderr)
            failures += 1
            continue
        if args.dp_id is not None and result["Header"]["Id"]["value"] != args.dp_id:
            skipped += 1
            continue
        failures += 1 if result["Statistics"]["Errors"] else 0
        results.append((bin_file, result))

    if skipped:
        print(f"Skipped {skipped} data products whose container ID is not {args.dp_id}")
    if args.collect:
        counts = write_collected_logs((result for _, result in results), output)
        print(f"Collected {counts['Channels']} channel samples and {counts['Events']} events "
              f"from {len(results)} data products into {output}")
        return failures

    for bin_file, result in results:
        if output is None:
            base = bin_file
        elif args.bin_dir is not None:
            base = output / bin_file.name
        else:
            base = output
        if args.reconstruct:
            base = base.with_name(f"{base.stem}_reconstructed{base.suffix}")
        if args.format in ("json", "both"):
            write_json(result, base.with_suffix(".json"))
            print(f"Wrote {base.with_suffix('.json')}")
        if args.format in ("text", "both"):
            write_text(result, base.with_suffix(".txt"))
            print(f"Wrote {base.with_suffix('.txt')}")
        stats = result["Statistics"]
        print(f"{bin_file}: {stats['Events']} events, {stats['Channels']} channels, {stats['Errors']} record errors")
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
    decode_parser.add_argument("-r", "--rename-id", action='store_true', help="Name output files <containerName>_<sec>_<usec>.json instead of Dp_<containerId>_<sec>_<usec>.json, using the container's short name from the dictionary")
    decode_parser.add_argument("-z", "--disable-decompression", action='store_true', help="Disable automatic decompression of data products")

    comlog_parser = subcommands_parser.add_parser('comlog', help='Decode Svc.ComLoggerDp data products into the events and telemetry channels they recorded')
    comlog_input = comlog_parser.add_mutually_exclusive_group(required=True)
    comlog_input.add_argument("-b", "--bin-file", help="Path to a ComLoggerDp data product file (.fdp)")
    comlog_input.add_argument("-B", "--bin-dir", help="Directory of data products; every *.fdp and *.bin file in it is decoded")
    comlog_parser.add_argument("-d", "--dictionary", required=True, help="Path to F Prime JSON Dictionary")
    comlog_parser.add_argument("-o", "--output", help="Output path (with --bin-file; the extension is replaced by .json/.txt and --reconstruct appends _reconstructed to the name) or output directory (with --bin-dir or --collect). Defaults to next to the input, or the current directory for --collect")
    comlog_parser.add_argument("--dp-id", type=lambda value: int(value, 0), help="Only process products whose header container ID matches (decimal or 0x hex); not usable with --reconstruct")
    comlog_parser.add_argument("-f", "--format", choices=["json", "text", "both"], default="both", help="Output format (default: both)")
    comlog_parser.add_argument("--collect", action="store_true", help=f"Merge the products of --bin-dir into time-sorted {CHANNEL_LOG_NAME} and {EVENT_LOG_NAME} files instead of per-product output")
    comlog_parser.add_argument("--reconstruct", action="store_true", help="Scan a damaged --bin-file for sentry markers and decode the records that survive, ignoring the header. Payload bytes equal to the sentry split a record, and a damaged length prefix sizes the record by the next sentry; prefer --no-crc when the header is intact")
    comlog_parser.add_argument("--sentry", type=u32_argument, default=DEFAULT_SENTRY, help=f"Sentry value preceding each Com buffer (default: {DEFAULT_SENTRY:#x})")
    comlog_parser.add_argument("--no-sentry", action="store_true", help="Do not check the sentry of each record")
    comlog_parser.add_argument("--no-crc", action="store_true", help="Do not check the header and data CRCs")

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

    elif args.command == "comlog":
        if args.collect and args.bin_dir is None:
            comlog_parser.error("--collect requires --bin-dir")
        if args.reconstruct and (args.bin_dir is not None or args.collect or args.no_sentry or args.dp_id is not None):
            comlog_parser.error("--reconstruct requires --bin-file and uses the sentry; it cannot be combined with --bin-dir, --collect, --no-sentry or --dp-id")
        if args.bin_dir is not None:
            bin_dir = Path(args.bin_dir)
            if not bin_dir.is_dir():
                comlog_parser.error(f"{args.bin_dir} is not a directory")
            bin_files = sorted(path for path in bin_dir.iterdir() if path.is_file() and path.suffix in (".fdp", ".bin"))
            if not bin_files:
                print(f"No .fdp or .bin files found in {bin_dir}", file=sys.stderr)
                return 1
            if args.output:
                output = Path(args.output)
            elif args.collect:
                output = Path.cwd()
            else:
                output = None
            if output is not None:
                if output.exists() and not output.is_dir():
                    comlog_parser.error(f"--output {output} must be a directory with --bin-dir")
                output.mkdir(parents=True, exist_ok=True)
        else:
            bin_files = [Path(args.bin_file)]
            output = Path(args.output) if args.output else None
            if output is not None:
                output.parent.mkdir(parents=True, exist_ok=True)
        decoder = ComLoggerDpDecoder(
            args.dictionaries, sentry=args.sentry, validate_sentry=not args.no_sentry, validate_crc=not args.no_crc
        )
        failures = comlog_files(decoder, bin_files, args, output)
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
