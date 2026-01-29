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

import os
import sys

from fprime_gds.common.dp.common import (
    ChecksumConfig,
    calculate_crc32,
    get_dp_header_type
)

import struct



class DataProductValidator:
    """Validator for F Prime Data Product files.
    
    Validates both header and data checksums of data product files.
    Supports three methods of determining header size:
    1. Using an F Prime dictionary
    2. Explicit header size parameter
    3. Guessing the header size from a range of valid values
    """
    
    def __init__(self, dictionary=None, header_size=None, guess_size=False, verbose=False):
        """Initialize the DataProductValidator.
        
        Args:
            dictionary: Path to F Prime dictionary file (optional)
            header_size: Explicit header size in bytes (optional)
            guess_size: Whether to guess header size (optional)
            verbose: Enable verbose output (optional)
        """
        self.dictionary = dictionary
        self.header_size = header_size
        self.guess_size = guess_size
        self.verbose = verbose

        # Checksum configuration from common module
        self.checksum_len = ChecksumConfig.CHECKSUM_LEN


    def validate_payload_checksum(self, payload):
        """Validate a give payload. Assumes the checksum occupies the last bytes of the payload
        
        Returns a tuple of values
            Item 0: True if the checksum matches the payload and False otherwise
            Item 1: A tuple containing the checksum in the payload and the expected checksum
                    calculated from the payload
                    Item 0: Checksum pulled out of the payload
                    Item 1: Checksum calculated from the non-checksum payload bytes
        """
        payload_data = payload[:-self.checksum_len]
        payload_checksum = struct.unpack(
            ChecksumConfig.CHECKSUM_STRUCT,
            payload[-self.checksum_len:]
        )[0]
        
        payload_checksum_calc = calculate_crc32(payload_data)
        
        if payload_checksum != payload_checksum_calc:
            return (False, (payload_checksum, payload_checksum_calc))
        else:
            return (True, (payload_checksum, payload_checksum_calc))

    def validate_data_product(self, dp_f, header_size):
        """Validate both the header and data checksums in a data product file

        Returns a tuple of values
            Item 0: True if both the header and data checksums match calculated values
                    and False otherwise
            Item 1: String representing which checksum failed, or None otherwise
            Item 3: The failing checksum tuples, or None otherwise
        """
        assert header_size > self.checksum_len, f"Expected Header Size to be at least {self.checksum_len} bytes"

        dp_header = dp_f.read(header_size)
        assert len(dp_header), f"Expected Data Product to be at least {header_size} bytes"

        checksum_ok, checksums = self.validate_payload_checksum(dp_header)
        if not checksum_ok:
            return (False,"Header",checksums)

        dp_data = memoryview(dp_f.read())
        checksum_ok, checksums = self.validate_payload_checksum(dp_data)
        if not checksum_ok:
            return (False,"Data",checksums)
        
        return (True, None, None)

    def validate_with_size(self, dp_f):
        """Validate a data product file using a provided header size

        Returns True if both the header and data checksums match calculated values
        and False otherwise
        """
        checksum_ok, failure, checksums = self.validate_data_product(dp_f, self.header_size)
        if not checksum_ok:
            print(f'Invalid {failure} checksum. Checksum in file {checksums[0]:08x}. Calculated Checksum {checksums[1]:08x}', file=sys.stderr)

        return checksum_ok

    def validate_with_dict(self, dp_f):
        """Validate a data product file using a provided F Prime dictionary
        to derive the header size

        Dictionary information is pulled from ConfigManager

        Returns True if both the header and data checksums match calculated values
        and False otherwise
        """

        # Calculate header size using ConfigManager and common field definitions
        # This uses the loaded dictionary under the hood
        header_size = get_dp_header_type()().getMaxSize()

        if self.verbose:
            print(f'Calculated a header size of {header_size}')

        checksum_ok, failure, checksums = self.validate_data_product(dp_f, header_size)

        if not checksum_ok:
            print(f'Invalid {failure} checksum. Checksum in file {checksums[0]:08x}. Calculated Checksum {checksums[1]:08x}', file=sys.stderr)

        return checksum_ok




    def validate_with_guess(self, dp_f):
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

        # Header size guessing ranges
        default_guess_size = 2+4+4+11+1+32+1+8+4  # 67 bytes (typical config)
        min_guess_size = 1+2+2+8+1+0+1+2+4        # 21 bytes (minimum)
        max_guess_size = 4+8+8+11+1+256+1+8+4     # 301 bytes (maximum)

        dp_f.seek(0, os.SEEK_END)
        dp_size = dp_f.tell()

        max_header_size = dp_size - (self.checksum_len + 1)

        max_guess_size = min(max_guess_size, max_header_size)

        # Try the default size first as an optimization
        if default_guess_size <= max_guess_size:
            dp_f.seek(0, os.SEEK_SET)
            checksum_ok, failure, checksums = self.validate_data_product(dp_f, default_guess_size)
            if checksum_ok:
                if self.verbose:
                    print(f'Valid checksum found with default size {default_guess_size}')
                return True

        for guess_size in range(min_guess_size, max_guess_size+1):
            dp_f.seek(0, os.SEEK_SET)
            checksum_ok, failure, checksums = self.validate_data_product(dp_f, guess_size)
            if checksum_ok:
                if self.verbose:
                    print(f'Valid checksum found with header size {guess_size}')
                return True

        print(f'No valid checksum found with header sizes in range [{min_guess_size},{max_guess_size}]', file=sys.stderr)

        return False

    def process(self, data_product_path):
        """Process and validate a data product file.
        
        Args:
            data_product_path: Path to the data product file to validate
            
        Returns:
            bool: True if validation succeeds, False otherwise
        """
        try:
            with open(data_product_path, 'rb') as dp_f:
                # See validate_with_guess for this calculation
                min_header_size = 1+2+2+8+1+0+1+2+4  # 21 bytes
                # Minimum data product is a header, one byte of payload and 4 bytes of checksum
                min_dp_size = min_header_size + 1 + 4

                dp_f.seek(0, os.SEEK_END)
                dp_size = dp_f.tell()
                dp_f.seek(0, os.SEEK_SET)

                if dp_size < min_dp_size:
                    print(f'Data Product file size below minimum {min_dp_size}', file=sys.stderr)
                    return False

                if self.header_size is not None and self.header_size > 0:
                    min_dp_size = self.header_size + 1 + 4
                    if dp_size < min_dp_size:
                        print(f'Data Product file size below minimum {min_dp_size}', file=sys.stderr)
                        return False

                    checksum_ok = self.validate_with_size(dp_f)
                elif self.dictionary is not None:
                    checksum_ok = self.validate_with_dict(dp_f)
                else:
                    checksum_ok = self.validate_with_guess(dp_f)
                
                if checksum_ok:
                    print("Validation OK!")
                return checksum_ok
        except Exception as e:
            print(f'Unable to validate Data Product file {data_product_path}', file=sys.stderr)
            raise e
