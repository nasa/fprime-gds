""" fprime_gds.executables.dictionary_merge: merge two F Prime JSON dictionaries

Deployments connected through a hub are operated with one merged dictionary. Names are qualified by component
instance, not by deployment, so two deployments instantiating the same subtopology produce identical names; the hub
forwards raw ids, so ids are authoritative: same id = same item, different id = different item. Entries sharing a
name but not an id are therefore both kept, renamed '<prefix>.<name>' with each input's namespace prefix (the last
segment of its metadata.deploymentName, or --prefix).
"""

import argparse
import collections
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ID_KEYS = {"commands": "opcode", "parameters": "id", "events": "id", "telemetryChannels": "id", "records": "id",
           "containers": "id"}  # the sections whose entries carry an id (their identity) and that --namespace-all prefixes
QUALIFIED_NAME_SECTIONS = ["typeDefinitions", "constants"]
ARRAY_SECTIONS = [*QUALIFIED_NAME_SECTIONS, *ID_KEYS, "telemetryPacketSets"]
SECTION_ORDER = ["metadata", *ARRAY_SECTIONS]
VERSION_FIELDS = ["projectVersion", "frameworkVersion", "dictionarySpecVersion"]
IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
DOTTED_IDENTIFIER = re.compile(rf"{IDENTIFIER.pattern}(\.{IDENTIFIER.pattern})*")


@dataclass
class MergeOptions:
    name: str = None
    permissive: bool = False
    prefer_primary: bool = False
    no_namespace: bool = False
    namespace_all: bool = False


@dataclass
class LoadedInput:
    path: str
    data: dict
    prefix: str = None


@dataclass
class Report:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def validate(loaded, report):
    """ Record a 'Malformed dictionary' error for each structural problem in one input """
    def malformed(problem):
        report.errors.append(f"Malformed dictionary '{loaded.path}': {problem}")

    if not isinstance(loaded.data, dict):
        malformed("must be a JSON object")
        return
    if not isinstance(loaded.data.get("metadata"), dict):
        malformed("'metadata' must be an object")
    elif not isinstance(loaded.data["metadata"].get("deploymentName", ""), str):
        malformed("'metadata.deploymentName' must be a string")
    for section in ARRAY_SECTIONS:
        entries = loaded.data.get(section)
        if not isinstance(entries, list):
            malformed(f"'{section}' must be an array")
            continue
        name_key = "qualifiedName" if section in QUALIFIED_NAME_SECTIONS else "name"
        id_key = ID_KEYS.get(section)
        for position, entry in enumerate(entries):
            if not isinstance(entry, dict) or not isinstance(entry.get(name_key), str) or not entry[name_key]:
                malformed(f"'{section}' entry #{position} must have a non-empty string '{name_key}'")
            elif id_key and type(entry.get(id_key)) is not int:  # not isinstance: bool is an int subclass
                malformed(f"'{section}' entry {entry[name_key]!r} must have an integer '{id_key}'")
            elif section == "telemetryPacketSets" and not valid_packet_set(entry):
                malformed(f"'{section}' entry {entry[name_key]!r} must have packets with a string 'name', an "
                          f"integer 'id' and arrays of channel names")
        for key in (name_key, id_key) if id_key else (name_key,):  # entries are unique by name and by id
            values = collections.Counter(entry.get(key) for entry in entries if isinstance(entry, dict))
            for value in sorted(map(repr, (v for v, n in values.items() if n > 1))):
                malformed(f"'{section}' has two entries with {key} {value}")


def valid_packet_set(packet_set):
    """ members (packets: name, id and a members list of channel names) and omitted must be arrays or null """
    def is_channel_name_list(value):
        return value is None or (isinstance(value, list) and all(isinstance(name, str) for name in value))

    def is_packet(value):
        return (isinstance(value, dict) and isinstance(value.get("name"), str) and type(value.get("id")) is int
                and is_channel_name_list(value.get("members")))

    packets = packet_set.get("members")
    packets_ok = packets is None or (isinstance(packets, list) and all(is_packet(packet) for packet in packets))
    return packets_ok and is_channel_name_list(packet_set.get("omitted"))


def namespace_prefix(loaded):
    """ The --prefix value, else the last segment of metadata.deploymentName when it is an identifier, else None """
    segment = str(loaded.data["metadata"].get("deploymentName", "")).rsplit(".", 1)[-1]
    return loaded.prefix or (segment if IDENTIFIER.fullmatch(segment) else None)


class Merger:
    """ Merges a primary and a secondary input, recording every problem in `report` instead of raising """

    def __init__(self, primary, secondary, options):
        self.inputs = (primary, secondary)
        self.options = options
        self.report = Report()
        self.renamed = (set(), set())  # per input: (section, name) of entries renamed '<prefix>.<name>'
        self.dropped_channels = set()  # secondary channel names that leave the merge: packets listing them go too
        self.shared_channels = set()  # secondary channel names that resolve to the primary's entry (same id)
        self._prefixes = None
        self.prefix_error = False  # set by prefixes() when a prefix is missing or shared; renames are then meaningless

    def merge(self):
        """ Returns the merged dictionary, or None once any error has been recorded """
        for loaded in self.inputs:
            validate(loaded, self.report)
        if self.report.errors:
            return None
        primary, secondary = self.inputs
        merged = {"metadata": self.merge_metadata()}
        for section in QUALIFIED_NAME_SECTIONS:
            merged[section] = self.merge_by_qualified_name(section)
        for section in ID_KEYS:
            merged[section] = self.merge_entries(section, primary.data[section], secondary.data[section])
        packet_sets = [[self.rewrite_packet_set(index, packet_set) for packet_set in loaded.data["telemetryPacketSets"]]
                       for index, loaded in enumerate(self.inputs)]
        merged["telemetryPacketSets"] = self.merge_entries("telemetryPacketSets", *packet_sets)
        self.check_packet_sets(merged)
        for key, value in {**secondary.data, **primary.data}.items():  # unknown top-level keys, primary's win
            merged.setdefault(key, value)
        return None if self.report.errors else merged

    def merge_metadata(self):
        """ The primary's metadata with the --name or derived deploymentName; versions must agree unless --permissive """
        primary, secondary = self.inputs
        first, second = primary.data["metadata"], secondary.data["metadata"]
        name = self.options.name
        if name is None:
            name = f"{first.get('deploymentName', 'unknown')}_{second.get('deploymentName', 'unknown')}_merged"
        elif not DOTTED_IDENTIFIER.fullmatch(name):
            self.report.errors.append(f"deploymentName {name!r} is not a valid dotted identifier")
        problems = self.report.warnings if self.options.permissive else self.report.errors
        for version in VERSION_FIELDS:
            if first.get(version) != second.get(version):
                problems.append(f"Inconsistent metadata values for field '{version}': {first.get(version)!r} in "
                                f"{primary.path}, {second.get(version)!r} in {secondary.path}; keeping {primary.path}'s")
        if first.get("libraryVersions") != second.get("libraryVersions"):
            self.report.warnings.append(f"metadata libraryVersions differ between {primary.path} and "
                                        f"{secondary.path}; keeping {primary.path}'s")
        return {**first, "deploymentName": name}

    def merge_by_qualified_name(self, section):
        """ typeDefinitions/constants: one copy per qualifiedName; differing definitions of a name conflict """
        primary, secondary = self.inputs
        held = {entry["qualifiedName"]: entry for entry in primary.data[section]}
        kept = []
        for entry in secondary.data[section]:
            name = entry["qualifiedName"]
            if name not in held:
                kept.append(entry)
            elif held[name] != entry:
                conflict = f"{section} {name!r} has inconsistent definitions in {primary.path} and {secondary.path}"
                self.drop(section, entry, error=conflict, warning=f"{conflict}; kept definition from {primary.path}")
        return primary.data[section] + kept

    def merge_entries(self, section, primary_entries, secondary_entries):
        """ Merge the two inputs' lists of named entries. In id-bearing sections ids decide identity: identical
        -> one copy; same id otherwise -> conflict; same name, different id -> both renamed '<prefix>.<name>'
        """
        primary, secondary = self.inputs
        id_key = ID_KEYS.get(section)
        by_name = {entry["name"]: entry for entry in primary_entries}
        by_id = {entry[id_key]: entry for entry in primary_entries} if id_key else {}
        prefixed_anyway = id_key and self.options.namespace_all  # every id-bearing name gets a prefix: no renaming

        def located(index, entry):
            return self.inputs[index].path + (f" ({entry[id_key]:#x})" if id_key else "")

        kept = []
        for entry in secondary_entries:
            name = entry["name"]
            held = by_name.get(name)
            same_id = by_id.get(entry[id_key]) if id_key else None
            if held == entry:
                if section == "telemetryChannels":
                    self.shared_channels.add(name)
                continue
            if same_id is not None and same_id["name"] == name:
                conflict = f"{section} {name!r} has different definitions in {primary.path} and {secondary.path}"
                self.drop(section, entry, error=conflict, name_kept=True,
                          warning=f"{conflict}; kept definition {name!r} from {primary.path}")
            elif same_id is not None:
                conflict = (f"{section} {id_key} {entry[id_key]:#x} is used by {same_id['name']!r} in "
                            f"{primary.path} and {name!r} in {secondary.path}")
                self.drop(section, entry, error=conflict,
                          warning=f"{conflict}; {name!r} dropped in favour of {same_id['name']!r}")
            elif held is None or prefixed_anyway:
                kept.append(entry)
            else:
                conflict = (f"{section} {name!r} is in {located(0, held)} and {located(1, entry)} with different "
                            f"{id_key or 'definition'}s")
                if self.options.no_namespace:
                    self.drop(section, entry, error=f"{conflict}; use --prefer-primary",
                              warning=f"{conflict}; {secondary.path}'s dropped in favour of {primary.path}'s")
                else:
                    for renamed in self.renamed:
                        renamed.add((section, name))
                    alpha, beta = (self.output_name(index, section, name) for index in (0, 1))
                    if not self.prefix_error:  # prefixes() already reported; the renames it produced are noise
                        self.report.warnings.append(f"{conflict}; renamed to {alpha!r} and {beta!r}")
                    kept.append(entry)
        merged = [{**entry, "name": self.output_name(index, section, entry["name"])}
                  for index, side in enumerate((primary_entries, kept)) for entry in side]
        if self.prefix_error:
            return merged  # prefixes() already reported the problem; the derived collisions would only add noise
        names = collections.Counter(entry["name"] for entry in merged)
        for name in sorted(name for name, occurrences in names.items() if occurrences > 1):
            self.report.errors.append(f"cannot rename {section} entries to {name!r}: the merged dictionary would "
                                      f"hold two entries with that name")
        return merged

    def drop(self, section, entry, error, warning, name_kept=False):
        """ The secondary's entry loses a conflict: an error, or with --prefer-primary a warning and it is dropped.
        Packets referencing a dropped channel go too, unless the primary keeps that name at that id (name_kept)
        """
        if not self.options.prefer_primary:
            self.report.errors.append(error)
            return
        self.report.warnings.append(warning)
        if section == "telemetryChannels":
            (self.shared_channels if name_kept else self.dropped_channels).add(entry["name"])

    def prefixes(self):
        """ Both namespace prefixes; problems are reported once, the first time a prefix is needed """
        if self._prefixes is None:
            self._prefixes = [namespace_prefix(loaded) for loaded in self.inputs]
            errors_before = len(self.report.errors)
            for loaded, prefix in zip(self.inputs, self._prefixes):
                if prefix is None:
                    self.report.errors.append(f"cannot derive a namespace prefix for {loaded.path}: "
                                              f"metadata.deploymentName must end in an identifier; use --prefix")
            if None not in self._prefixes and self._prefixes[0] == self._prefixes[1]:
                self.report.errors.append(f"{self.inputs[0].path} and {self.inputs[1].path} both have the namespace "
                                          f"prefix {self._prefixes[0]!r}; use --prefix to tell them apart")
            self.prefix_error = len(self.report.errors) > errors_before
        return self._prefixes

    def output_name(self, index, section, name):
        """ The name an entry of `section` from input `index` carries in the merged dictionary """
        if (self.options.namespace_all and section in ID_KEYS) or (section, name) in self.renamed[index]:
            return f"{self.prefixes()[index]}.{name}"
        return name

    def rewrite_packet_set(self, index, packet_set):
        """ Follow this input's channel renames and remove packets listing a channel dropped by --prefer-primary """
        dropped = self.dropped_channels if index == 1 else set()

        def channel(name):
            return self.output_name(0 if name in self.shared_channels else index, "telemetryChannels", name)

        packets = []
        for packet in packet_set.get("members") or []:
            members = packet.get("members") or []
            lost = sorted(dropped.intersection(members))
            if lost:
                survivors = len(set(members) - dropped)
                lost_too = f", so its other {survivors} channel(s) are lost too" if survivors else ""
                self.report.warnings.append(f"packet {packet.get('name')!r} of packet set {packet_set['name']!r} in "
                                            f"{self.inputs[index].path} removed because it references dropped "
                                            f"channel(s) {', '.join(map(repr, lost))}; the GDS will discard that "
                                            f"packet{lost_too}")
            else:
                packets.append({**packet, "members": [channel(name) for name in members]})
        omitted = [channel(name) for name in packet_set.get("omitted") or [] if name not in dropped]
        return {**packet_set, "members": packets, "omitted": omitted}

    def check_packet_sets(self, merged):
        """ Every referenced channel must exist in the merged channels; the GDS loads a single packet set """
        if self.report.errors:  # the channel list is incomplete after a conflict; unknown-channel errors would be noise
            return
        packet_sets = merged["telemetryPacketSets"]
        if len(packet_sets) > 1:
            self.report.warnings.append(f"merged dictionary has {len(packet_sets)} packet sets; fprime-gds needs "
                                        f"--packet-set-name to start and decodes only the selected set")
        channels = {channel["name"] for channel in merged["telemetryChannels"]}
        for packet_set in packet_sets:
            references = {name for packet in packet_set["members"] for name in packet["members"]}
            for name in sorted(references.union(packet_set["omitted"]) - channels):
                self.report.errors.append(f"packet set {packet_set['name']!r} references unknown channel {name!r}")


def merge_two(primary, secondary, options):
    """ Merge two loaded inputs; returns (merged dictionary or None, Report) """
    merger = Merger(primary, secondary, options)
    return merger.merge(), merger.report


def merge_dictionaries(dictionary1, dictionary2, name=None, permissive=False):
    """ Merge two dictionaries' contents with the CLI's default merge rules; raises ValueError listing every error """
    merged, report = merge_two(LoadedInput("dictionary1", dictionary1), LoadedInput("dictionary2", dictionary2),
                               MergeOptions(name=name, permissive=permissive))
    if merged is None:
        raise ValueError("\n".join(report.errors))
    return merged


def parse_arguments(argv):
    """ Parse and cross-check command line arguments """
    parser = argparse.ArgumentParser(description="Merge two F Prime JSON dictionaries into one")
    parser.add_argument("--name", help="'deploymentName' of the merged dictionary. Default: <name1>_<name2>_merged")
    parser.add_argument("--output", type=Path, default=Path("MergedAppDictionary.json"),
                        help="Output dictionary path. Default: MergedAppDictionary.json")
    parser.add_argument("--permissive", action="store_true",
                        help="Only warn about version discrepancies between the metadata blocks")
    parser.add_argument("--prefer-primary", action="store_true",
                        help="On id or definition conflicts (and, with --no-namespace, name conflicts) keep the "
                             "primary dictionary's entry and drop the other with a warning. Data the other deployment "
                             "emits under a dropped id is then decoded as the primary's entry; data under an id "
                             "dropped by a name conflict is unknown to the GDS")
    namespacing = parser.add_mutually_exclusive_group()
    namespacing.add_argument("--no-namespace", action="store_true",
                             help="Treat a name used with different ids as an error (a drop with --prefer-primary) "
                                  "instead of renaming both entries")
    namespacing.add_argument("--namespace-all", action="store_true",
                             help="Prefix every command, parameter, event, channel, record and container name")
    parser.add_argument("--prefix", action="append", default=[], metavar="PREFIX",
                        help="Namespace prefix of each dictionary, in order (give --prefix twice). "
                             "Default: last segment of metadata.deploymentName")
    parser.add_argument("dictionary1", type=Path, help="Primary dictionary to merge")
    parser.add_argument("dictionary2", type=Path, help="Secondary dictionary to merge")
    args = parser.parse_args(argv)
    if args.prefix and len(args.prefix) != 2:
        parser.error("--prefix must be given exactly twice, once per dictionary")
    if args.prefix and args.no_namespace:
        parser.error("--prefix cannot be combined with --no-namespace")
    if len(set(args.prefix)) != len(args.prefix) or not all(DOTTED_IDENTIFIER.fullmatch(p) for p in args.prefix):
        parser.error("--prefix values must be distinct dotted identifiers")
    return args


def load_input(path, prefix):
    """ Read one input; parse failures name the file """
    try:
        return LoadedInput(str(path), json.loads(path.read_text()), prefix)
    except (ValueError, RecursionError) as exception:
        raise ValueError(f"{path}: {exception}") from exception


def main(argv=None):
    """ Main entry point """
    args = parse_arguments(argv)
    options = MergeOptions(name=args.name, permissive=args.permissive, prefer_primary=args.prefer_primary,
                           no_namespace=args.no_namespace, namespace_all=args.namespace_all)
    try:
        inputs = [load_input(path, prefix)
                  for path, prefix in zip((args.dictionary1, args.dictionary2), args.prefix or (None, None))]
        merged, report = merge_two(*inputs, options)
        for warning in report.warnings:
            print(f"[WARNING] {warning}", file=sys.stderr)
        for error in report.errors:
            print(f"[ERROR] {error}", file=sys.stderr)
        if merged is None:
            print(f"[ERROR] Merge failed with {len(report.errors)} error(s); no output written", file=sys.stderr)
            sys.exit(1)
        try:
            text = json.dumps(merged, indent=2)
        except RecursionError as exception:
            raise ValueError(f"{args.output}: merged dictionary is nested too deeply to write") from exception
        args.output.write_text(text)
    except (OSError, ValueError, RecursionError) as exception:  # bad input, unwritable output, too-deep merge
        print(f"[ERROR] {exception}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
