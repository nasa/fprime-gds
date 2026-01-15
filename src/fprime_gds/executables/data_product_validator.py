# ------------------------------------------------------------------------------------------
# Program: Data Product Validator
#
# Filename: data_product_validator.py
#
# Author: Gerik Kubiak
#
#   The "Data Product Validator" program is designed to validate F Prime Data Product files.
#   The program validates both the header and data checksums of the given data product and
#   returns a 0 error code on success and a non-zero error code on failure.
#
#   The size of the data product header may vary between F Prime deployments. There are
#   three ways of providing this information to the script
#   1. Use a provided F Prime Dictionary
#   2. Pass the header size on the command line
#   3. Guess at the header size. This script may iterate through a range of valid
#      header sizes and will report success if any of these sizes results in valid
#      data product checksums
#
#   This script assumes the standard CRC32 checksum used by default in F Prime. Extended the
#   script to work with other checksums is future work

import argparse
import struct
import os
import sys
from binascii import crc32

# Note: These values are technically configurable by F Prime end users
# but this script assumes they are constants. Future work could
# parameterize these values
checksum_len = 4
checksum_struct = ">I"
checksum_crc32 = 0x104C11DB7
checksum_init = 0
checksum_rev = True
checksum_xorOut = 0xFFFFFFFF

def validate_payload_checksum(payload):
    """Validate a give payload. Assumes the checksum occupies the last bytes of the payload
    
    Returns a tuple of values
        Item 0: True if the checksum matches the payload and False otherwise
        Item 1: A tuple containing the checksum in the payload and the expected checksum
                calculated from the payload
                Item 0: Checksum pulled out of the payload
                Item 1: Checksum calculated from the non-checksum payload bytes
    """
    global checksum_struct
    global checksum_len

    payload_data = payload[:-checksum_len]
    payload_checksum = struct.unpack(checksum_struct, payload[-checksum_len:])[0]

    payload_checksum_calc = crc32(payload_data, 0) & 0xFFFFFFFF
    if payload_checksum != payload_checksum_calc:
        return (False,(payload_checksum, payload_checksum_calc))
    else:
        return (True,(payload_checksum, payload_checksum_calc))

def validate_data_product(dp_f, args, header_size):
    """Validate both the header and data checksums in a data product file

    Returns a tuple of values
        Item 0: True if both the header and data checksums match calculated values
                and False otherwise
        Item 1: String representing which checksum failed, or None otherwise
        Item 3: The failing checksum tuples, or None otherwise
    """

    global checksum_len
    assert header_size > checksum_len, f"Expected Header Size to be at least {checksum_len} bytes"

    dp_header = dp_f.read(header_size)
    assert len(dp_header), f"Expected Data Product to be at least {header_size} bytes"

    checksum_ok, checksums = validate_payload_checksum(dp_header)
    if not checksum_ok:
        return (False,"Header",checksums)

    dp_data = memoryview(dp_f.read())
    checksum_ok, checksums = validate_payload_checksum(dp_data)
    if not checksum_ok:
        return (False,"Data",checksums)
    
    return (True, None, None)

def validate_data_product_size(dp_f, args):
    """Validate a data product file using a provided header size

    Returns True if both the header and data checksums match calculated values
    and False otherwise
    """
    checksum_ok,failure,checksums = validate_data_product(dp_f, args, args.header_size)
    if not checksum_ok:
        print(f'Invalid {failure} checksum. Checksum in file {checksums[0]:08x}. Calculated Checksum {checksums[1]:08x}', file=sys.stderr)

    return checksum_ok

def validate_data_product_dict(dp_f, args):
    """Validate a data product file using a provided F Prime dictionary
    to derive the header size

    Returns True if both the header and data checksums match calculated values
    and False otherwise
    """

    import json

    field_types = {
        "PacketDescriptor": "FwPacketDescriptorType",
        "Id": "FwDpIdType",
        "Priority": "FwDpPriorityType",
        "TimeBase": "TimeBase",
        "TimeContext": "FwTimeContextStoreType",
        "TimeSeconds": 4,
        "TimeUseconds": 4,
        "ProcTypes": "Fw.DpCfg.ProcType",
        "UserData": "Fw.DpCfg.CONTAINER_USER_DATA_SIZE",
        "DpState": "Fw.DpState",
        "DataSize": "FwSizeStoreType",
        "Checksum": 4
    }

    try:
        with open(args.dictionary, 'r') as fprimeDictFile:
            dict_json = json.load(fprimeDictFile)

            header_size = 0
            for field_type in field_types.values():
                if type(field_type) is int:
                    field_size = field_type
                else:
                    found = False
                    try:
                        for entry in dict_json["constants"]:
                            if field_type == entry["qualifiedName"]:
                                field_size = int(entry["value"])
                                found = True
                                break
                        if not found:
                            for entry in dict_json["typeDefinitions"]:
                                if field_type == entry["qualifiedName"]:
                                    if entry["kind"] == "alias":
                                        field_size = int(int(entry["underlyingType"]["size"])/8)
                                        found = True
                                        break
                                    elif entry["kind"] == "enum":
                                        field_size = int(int(entry["representationType"]["size"])/8)
                                        found = True
                                        break
                                    else:
                                        print(f'Unsupported field type kind {entry["kind"]} for type {field_type}', file=sys.stderr)
                                        sys.exit(1)

                        if args.verbose:
                            print(f'Found Dictionary entry for {field_type}. Size {field_size}')

                    except KeyError as e:
                        print(f'KeyError processing field type {field_type}', file=sys.stderr)
                        raise e

                    if not found:
                        print(f'Unable to find size of {field_type} in dictionary. Aborting', file=sys.stderr)
                        return False


                header_size += field_size

        if args.verbose:
            print(f'Calculated a header size of {header_size}')

        checksum_ok,failure,checksums = validate_data_product(dp_f, args, header_size)
        if not checksum_ok:
            print(f'Invalid {failure} checksum. Checksum in file {checksums[0]:08x}. Calculated Checksum {checksums[1]:08x}', file=sys.stderr)

        return checksum_ok
    except OSError as e:
        print(f'Unable to open dictionary file {args.dictionary}', file=sys.stderr)
        raise e
    except json.JSONDecodeError as e:
        print(f'Error parsing {args.dictionary}, line number {e.lineno}', file=sys.stderr)
        raise e



def validate_data_product_guess(dp_f, args):
    """Validate a data product file by guessing at the header size

    Returns True if both the header and data checksums match calculated values
    and False otherwise
    """

    # Header parts and default values
    # Field            | Data Type   | Size in Default Config | Min Reasonable Size | Max Reasonable Size
    # PacketDescriptor | FwPacketDescriptorType | 2  | 1 | 4
    # Id               | FwDpIdType             | 4  | 2 | 8
    # Priority         | FwDpPriorityType       | 4  | 2 | 8
    # TimeTag          | Fw::Time               | 11 | 8 | 11
    # ProcTypes        | Fw::DpCfg::ProcType    | 1  | 1 | 1
    # UserData         | Header::UserData       | 32 | 0 | 256
    # DpState          | DpState                | 1  | 1 | 1
    # DataSize         | FwSizeType             | 8  | 2 | 8
    # Header Hash      | HASH_DIGEST_LENGTH     | 4  | 4 | 4

    default_guess_size = 2+4+4+11+1+32+1+8+4
    min_guess_size = 1+2+2+8+1+0+1+2+4
    max_guess_size = 4+8+8+11+1+256+1+8+4

    dp_f.seek(0, os.SEEK_END)
    dp_size = dp_f.tell()

    max_header_size = dp_size - (checksum_len + 1)

    max_guess_size = min(max_guess_size, max_header_size)

    # Try the default size first as an optimization
    if default_guess_size <= max_guess_size:
        dp_f.seek(0, os.SEEK_SET)
        checksum_ok, failure, checksums = validate_data_product(dp_f, args, default_guess_size)
        if checksum_ok:
            if args.verbose:
                print(f'Valid checksum found with default size {default_guess_size}')
            return True

    for guess_size in range(min_guess_size, max_guess_size+1):
        dp_f.seek(0, os.SEEK_SET)
        checksum_ok, failure, checksums = validate_data_product(dp_f, args, guess_size)
        if checksum_ok:
            if args.verbose:
                print(f'Valid checksum found with header size {guess_size}')
            return True

    print(f'No valid checksum found with header sizes in range [{min_guess_size},{max_guess_size}]', file=sys.stderr)

    return False

def main():

    parser = argparse.ArgumentParser(description="F Prime Data Product Checksum validator")

    parser.add_argument('data_product', help='Data Product file')
    parser.add_argument('-d', '--dictionary', default=None, help='Use an F Prime dictionary to derive the appropriate header size')
    parser.add_argument('-s', '--header-size', type=int, default=0, help='Use the provided value as the header size for the data product. The provided size is the sum of the header + header checksum')
    parser.add_argument('-g', '--guess-size', action='store_true', help='Guess at the header size and attempt to find a header size the results in a valid data product header checksum')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    if args.header_size < 0:
        print(f'--header-size must be a positive integer', file=sys.stderr)
        return 1

    if args.dictionary is None and args.header_size == 0 and args.guess_size == False:
        print(f'One of --dictionary, --header-size or --guess-size is necessary to process the data product', file=sys.stderr)
        return 1

    try:
        dp_f = open(args.data_product, 'rb')
    except Exception as e:
        print(f'Unable to open Data Product file {args.data_product}', file=sys.stderr)
        raise e

    # See validate_data_product_guess for this calculation
    min_header_size = 1+2+2+8+1+0+1+2+4
    # Minimum data product is a header, one byte of payload and 4 bytes of checksum
    min_dp_size = min_header_size + 1 + 4

    dp_f.seek(0, os.SEEK_END)
    dp_size = dp_f.tell()
    dp_f.seek(0, os.SEEK_SET)

    if dp_size < min_dp_size:
        print(f'Data Product file size below minimum {min_dp_size}', file=sys.stderr)
        return 1

    if args.header_size > 0:
        min_dp_size = args.header_size + 1 + 4
        if dp_size < min_dp_size:
            print(f'Data Product file size below minimum {min_dp_size}', file=sys.stderr)
            return 1

        checksum_ok = validate_data_product_size(dp_f, args)
    elif args.dictionary is not None:
        checksum_ok = validate_data_product_dict(dp_f, args)
    else:
        checksum_ok = validate_data_product_guess(dp_f, args)

    if checksum_ok:
        return 0
    else:
        return 1

if __name__ == "__main__":
    sys.exit(main())

