""" fprime_gds.executables.dictionary_merge: script to merge two F Prime dictionaries """

import argparse
import functools
import json
import re
import sys
from pathlib import Path


def validate_metadata(metadata1, metadata2):
    """ Check consistency between metadata blocks
    
    The JSON dictionary has multiple fields in the metadata block. This function will check that there is consistency
    between these two blocks.

    Args:
        metadata1: metadata from the first dictionary
        metadata2: metadata from the second dictionary
    """
    for field in ["projectVersion", "frameworkVersion", "dictionarySpecVersion"]:
        value1 = metadata1[field]
        value2 = metadata2[field]
        if value1 != value2:
            raise ValueError(f"Inconsistent metadata values for field '{field}'. ({value1} vs {value2})")

def validate_non_unique(non_unique1, non_unique2):
    """ Validate non-unique definitions are consistent between dictionaries """
    indexed_non_unique1 = {value.get("qualifiedName"): value for value in non_unique1}

    for value2 in non_unique2:
        value1 = indexed_non_unique1.get(value2["qualifiedName"], None)
        if value1 is not None and value1 != value2:
            raise ValueError(f"'{value2['qualifiedName']}' has inconsistent definitions")

def validate_unique(unique1, unique2):
    """ Validate unique definitions have no duplication """
    ids = {item.get("id", item.get("opcode", "")) for item in unique1}
    names = {item.get("name") for item in unique1}


    for value2 in unique2:
        name = value2['name']
        id = value2.get("id", value2.get("opcode", ""))
        if name in names:
            raise ValueError(f"'{name}' appears in both dictionaries")
        if id and id in ids:
            raise ValueError(f"ID/Opcode {id} used in both dictionaries")


def merge_metadata(meta1, meta2, name=None, permissive=False):
    """ Merge JSON dictionary metadata blocks
    
    The JSON dictionary starts with a metadata block. This function will merge the two metadata blocks preferring the
    first when there is a discrepancy. 'name' will be supplied as the new name defaulting to "name1_name2_merged" when
    not supplied. If 'permissive' is true, version discrepancies will be ignored otherwise this will throw a ValueError
    if the versions do not match.

    Args:
        meta1: first metadata block
        meta2: second metadata block
        name: (optional) name for the new dictionary (Default: meta.name_meta2.name_merged)
        permissive: (optional) True to allow version miss-matching. (Default: False)
    Return:
        merged metadata block
    Throws:
        ValueError on version miss-match without the permissive flag
    """
    if not permissive:
        validate_metadata(meta1, meta2)
    if name is None:
        name = f"{meta1.get('deploymentName', 'unknown')}_{meta2.get('deploymentName', 'unknown')}_merged"
    return {
        **meta1,
        **{
            "deploymentName": name
          }
    }

def merge_lists(list1, list2, validator):
    """ Merge list-like entities
    
    This will merge two list-like entities using the supplied validator.

    Args:
        list1: first list-like
        list2: second list-like
        validator: validate the lists are consistent or non-colliding

    """
    validator(list1, list2)
    singular = {item.get("qualifiedName", item.get("name", "")): item for item in list1 + list2}
    return list(singular.values())

def merge_non_unique(non_unique1, non_unique2):
    """ Merge the non-unique blocks in JSON dictionaries

    JSON dictionaries have some non-unique definitions (e.g. "typeDefinitions") that must be merged ensuring
    consistency but ignoring duplication. This function will create a superset of the two blocks. Inconsistent
    definitions will result in a ValueError.

    Args:
        non_unique1: first non unique block
        non_unique2: second non unique block
    """
    return merge_lists(non_unique1, non_unique2, validate_non_unique)


def merge_unique(unique1, unique2):
    """ Merge the unique blocks in JSON dictionaries

    JSON dictionaries have some unique definitions (e.g. "eventDefinitions") that must be merged ensuring that entries
    are not duplicated between the sets. This function will create a superset of the two blocks. Duplicated definitions
    will result in a ValueError.

    Args:
        unique1: first unique block
        unique2: second unique block
    """
    return merge_lists(unique1, unique2, validate_unique)


def merge_dictionaries(dictionary1, dictionary2, name=None, permissive=False):
    """ Merge two dictionaries

    This will merge two JSON dictionaries' major top-level sections. Unknown fields will be preserved preferring
    dictionary1's content for unknown fields.

    Args:
        dictionary1: dictionary 1's content
        dictionary2: dictionary 2's content
        name: new 'deploymentName' field
        permissive: allow miss-matched dictionary versions

    Return: merged dictionaries
        
    """
    merge_metadata_fn = functools.partial(merge_metadata, name=name, permissive=permissive)

    stages = [
        ("metadata", merge_metadata_fn),
        ("typeDefinitions", merge_non_unique),
        ("constants", merge_non_unique),
        ("commands", merge_unique),
        ("parameters", merge_unique),
        ("events", merge_unique),
        ("telemetryChannels", merge_unique),
        ("records", merge_unique),
        ("containers", merge_unique),
        ("telemetryPacketSets", merge_unique),

    ]

    merged = {**dictionary2, **dictionary1}
    for field, merger in stages:
        object1 = dictionary1[field]
        object2 = dictionary2[field]
        try:
            merged[field] = merger(object1, object2)
        except ValueError as value_error:
            raise ValueError(f"Merging '{field}' failed. {value_error}")
        except KeyError as key_error:
            raise ValueError(f"Malformed dictionary section '{field}'. Missing key: {key_error}")
    return merged

def parse_arguments():
    """ Parse arguments for this script """
    parser = argparse.ArgumentParser(description="Merge two dictionaries")
    parser.add_argument("--name", type=str, default=None, help="Name to use as the new 'deploymentName' field")
    parser.add_argument("--output", type=Path, default=Path("MergedAppDictionary.json"),
                        help="Output dictionary path. Default: MergedAppDictionary.json")
    parser.add_argument("--permissive", action="store_true", default=False,
                        help="Ignore discrepancies between dictionaries")
    parser.add_argument("dictionary1", type=Path, help="Primary dictionary to merge")
    parser.add_argument("dictionary2", type=Path, help="Secondary dictionary to merge")

    args = parser.parse_args()

    # Validate arguments
    if args.name is not None and not re.match("[a-zA-Z_][a-zA-Z_0-9]*"):
        raise ValueError(f"--name '{args.name}' is an invalid identifier")
    if not args.dictionary1.exists():
        raise ValueError(f"'{args.dictionary1}' does not exist")
    if not args.dictionary2.exists():
        raise ValueError(f"'{args.dictionary2}' does not exist")
    return args

def main():
    """ Main entry point """
    try:
        args = parse_arguments()
        # Open dictionaries
        with open(args.dictionary1, "r") as dictionary1_fh:
            dictionary1 = json.load(dictionary1_fh)
        with open(args.dictionary2, "r") as dictionary2_fh:
            dictionary2 = json.load(dictionary2_fh)
        output = merge_dictionaries(dictionary1, dictionary2, args.name, args.permissive)
        with open(args.output, "w") as output_fh:
            json.dump(output, output_fh, indent=2)
    except Exception as exception:
        print(f"[ERROR] {exception}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
