# ------------------------------------------------------------------------------------------
# Program: Data Product Writer
#
# Filename: data_product_writer.py
#
# Author: Garth Watney
#
#   The "Data Product Writer" program is designed to interpret and convert binary data products 
#   from the F' flight software into JSON format. Each data product comprises multiple records, 
#   and the program's role is to deserialize this binary data using JSON dictionaries and 
#   header specifications, producing a readable JSON file.
#
# Argument Parsing:
#   The program starts by parsing command-line arguments to obtain the path to the binary 
#   data product file.
#
# Reading JSON Dictionary:
#   It reads the F' JSON dictionary file, which provides the necessary context for 
#   interpreting the binary data, catching any JSON decoding errors to handle malformed 
#   files gracefully.
#
# Data Validation:
#   Before proceeding, the program checks for duplicate record identifiers within the 
#   JSON dictionary to ensure data integrity.
#
#
# Binary File Processing:
#   The program opens the binary file for reading, initializes counters for tracking the 
#   total bytes read and a variable for calculating the CRC checksum. The header data is 
#   read first, followed by the individual records, each deserialized based on the JSON 
#   dictionary and header specification.
#
# CRC Validation:
#   After processing the records, the program validates the CRC checksum to ensure the 
#   data's integrity has been maintained throughout the reading process.
#
# Exception Handling:
#   Throughout its execution, the program is equipped to handle various exceptions, 
#   ranging from file not found scenarios to specific data-related errors like CRC 
#   mismatches or duplicate record IDs. Each exception triggers an error handling 
#   routine that provides informative feedback and terminates the program gracefully.
#
# Output Generation:
#   Upon successful processing, the program writes the deserialized data to a JSON file. 
#   The output file's name is derived from the binary file's name with a change in its 
#   extension to `.json`, facilitating easy association between the input and output files.
#
# The "Data Product Writer" program is executed from the command line and requires specific 
# arguments to function correctly. The primary argument it needs is the path to the binary 
# data product file that will be processed.
#
# Usage:
# python data_product_writer.py <binFile> <json dictionary>
#
# Where:
# <binFile> is the path to the binary file generated by the F' flight software that contains 
# the data product to be deserialized and written to a JSON file.
#
# <json dictionary> is the path to the json dictionary that is generated upon an F' build
# 
#
# The program does not require any additional command-line options or flags for its basic 
# operation. Once executed with the correct binary file path and with the necessary JSON 
# files in place, it will perform the series of steps outlined previously, culminating in 
# the generation of a JSON file with the same base name as the binary file but with a .json 
# extension.
#
# ------------------------------------------------------------------------------------------

import struct
import json
import os
import sys
from typing import List, Dict, Union, ForwardRef
from pydantic import BaseModel, field_validator
from typing import List, Union
import argparse
from binascii import crc32

binaryFile = None

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


# This defines the data in the container header.  When this is ultimately defined in the json dictionary,
# then this can be removed.
header_data = {
    "typeDefinitions" : [
        {
            "kind": "array",
            "qualifiedName": "UserDataArray",
            "size": 32,
            "elementType": {
                "name": "U8",
                "kind": "integer",
                "signed": False,
                "size": 8
            }
        },

        {
            "kind": "struct",
            "qualifiedName": "timeStruct",
            "members": {
                "seconds": {
                    "type": {
                        "name": "U32",
                        "kind": "integer",
                        "signed": False,
                        "size": 32
                    }
                },
                "useconds": {
                    "type": {
                        "name": "U32",
                        "kind": "integer",
                        "signed": False,
                        "size": 32
                    }
                },
                "timeBase": {
                    "type": {
                        "name": "U16",
                        "kind": "integer",
                        "signed": False,
                        "size": 16
                    }
                },
                "context": {
                    "type": {
                        "name": "U8",
                        "kind": "integer",
                        "signed": False,
                        "size": 8
                    }
                }
            }
        }
    ],

    "enums" : [
    ],

    "header": {
        "PacketDescriptor": {
            "type": {
                "name": "U32",
                "kind": "integer",
                "signed": False,
                "size": 32
            }
        },
        "Id": {
            "type": {
                "name": "U32",
                "kind": "integer",
                "signed": False,
                "size": 32
            }
        },
        "Priority": {
            "type": {
                "name": "U32",
                "kind": "integer",
                "signed": False,
                "size": 32
            }
        },
        "TimeTag": {
            "type": {
                "name": "timeStruct",
                "kind": "qualifiedIdentifier"
            }
        },
        "ProcTypes": {
            "type": {
                "name": "U8",
                "kind": "integer",
                "signed": False,
                "size": 8
            }
        },
        "UserData": {
            "type": {
                "name": "UserDataArray",
                "kind": "qualifiedIdentifier"
            }
        },
        "DpState": {
            "type": {
                "name": "U8",
                "kind": "integer",
                "signed": False,
                "size": 8
            }
        },
        "DataSize": {
            "type": {
                "name": "U16",
                "kind": "integer",
                "signed": False,
                "size": 16
            }       
        }
    },

    "headerHash": {
        "type": {
            "name": "U32",
            "kind": "integer",
            "signed": False,
            "size": 32
        }
    },

    "dataId": {
        "type": {
            "name": "U32",
            "kind": "integer",
            "signed": False,
            "size": 32
        }
    },

    "dataSize": {
        "type": {
            "name": "U16",
            "kind": "integer",
            "signed": False,
            "size": 16
        }
    },

    "dataHash": {
        "type": {
            "name": "U32",
            "kind": "integer",
            "signed": False,
            "size": 32
        }
    }
}

# Deserialize the binary file big endian
BIG_ENDIAN = ">"

# -------------------------------------------------------------------------------------
# These are common Pydantic classes that 
# are used by both the dictionary json and the data product json 
#
# -------------------------------------------------------------------------------------

class IntegerType(BaseModel):
    name: str
    kind: str
    size: int
    signed: bool

    @field_validator('kind')
    def kind_qualifiedIdentifier(cls, v):
        if v != "integer":
            raise ValueError('Check the "kind" field')
        return v

class FloatType(BaseModel):
    name: str
    kind: str
    size: int

    @field_validator('kind')
    def kind_qualifiedIdentifier(cls, v):
        if v != "float":
            raise ValueError('Check the "kind" field')
        return v

class BoolType(BaseModel):
    name: str
    kind: str
    size: int

    @field_validator('kind')
    def kind_qualifiedIdentifier(cls, v):
        if v != "bool":
            raise ValueError('Check the "kind" field')
        return v

Type = ForwardRef('Type')
ArrayType = ForwardRef('ArrayType')

class QualifiedType(BaseModel):
    kind: str
    name: str

    @field_validator('kind')
    def kind_qualifiedIdentifier(cls, v):
        if v != "qualifiedIdentifier":
            raise ValueError('Check the "kind" field')
        return v

class StructMember(BaseModel):
    type: Union[IntegerType, FloatType, BoolType, QualifiedType]
    size: int = 1

class StructType(BaseModel):
    kind: str
    qualifiedName: str
    members: Dict[str, StructMember]

    @field_validator('kind')
    def kind_qualifiedIdentifier(cls, v):
        if v != "struct":
            raise ValueError('Check the "kind" field')
        return v

class ArrayType(BaseModel):
    kind: str
    qualifiedName: str
    size: int
    elementType: Union[StructType, ArrayType, IntegerType, FloatType, QualifiedType]

    @field_validator('kind')
    def kind_qualifiedIdentifier(cls, v):
        if v != "array":
            raise ValueError('Check the "kind" field')
        return v

class EnumeratedConstant(BaseModel):
    name: str
    value: int


class EnumType(BaseModel):
    kind: str
    qualifiedName: str
    #representationType: RepresentationType
    representationType: IntegerType
    enumeratedConstants: List[EnumeratedConstant]

    @field_validator('kind')
    def kind_qualifiedIdentifier(cls, v):
        if v != "enum":
            raise ValueError('Check the "kind" field')
        return v


class Type(BaseModel):
    type: Union[StructType, ArrayType, IntegerType, FloatType, BoolType, QualifiedType]

class RecordStruct(BaseModel):
    name: str
    type: Union[StructType, ArrayType, IntegerType, FloatType, BoolType, QualifiedType]
    array: bool
    id: int
    annotation: str

class ContainerStruct(BaseModel):
    name: str
    id: int
    defaultPriority: int
    annotation: str

# -------------------------------------------------------------------------------------
# These Pydantic classes define the FPRIME_DICTIONARY_FILE
#
# -------------------------------------------------------------------------------------

class FprimeDict(BaseModel):
    metadata: Dict[str, Union[str, List[str]]]
    typeDefinitions: List[Union[ArrayType, StructType, EnumType]]
    records: List[RecordStruct]
    containers: List[ContainerStruct]

# -------------------------------------------------------------------------------------
# This Pydantic class defines the data product json
#
# -------------------------------------------------------------------------------------

class DPHeader(BaseModel):
    typeDefinitions: List[Union[ArrayType, StructType, EnumType]]
    header: Dict[str, Type]
    headerHash: Type
    dataId: Type
    dataSize: Type
    dataHash: Type

ArrayType.model_rebuild()
StructType.model_rebuild()
Type.model_rebuild()

TypeKind = Union[StructType, ArrayType, IntegerType, FloatType, EnumType, BoolType, QualifiedType]
TypeDef = Union[ArrayType, StructType]

# Map the JSON types to struct format strings
type_mapping = {
    'U8': 'B',  # Unsigned 8-bit integer
    'I8': 'b',  # Signed 8-bit integer
    'U16': 'H', # Unsigned 16-bit integer
    'I16': 'h', # Signed 16 bit integer
    'U32': 'I', # Unsigned 32-bit integer
    'I32': 'i', # Signed 32-bit integer
    'I64': 'q', # Signed 64-bit integer
    'U64': 'Q', # Unsigned 64-bit integer
    'F32': 'f',  # 32-bit float
    'F64': 'd',  # 64-bit float
    'bool': '?' # An 8 bit boolean
    # Add more mappings as needed
}



# ----------------------------------------------------------------------------------------------
# Function: read_and_deserialize
#
# Description: 
#   Reads specified bytes from a binary file, updates CRC, increments byte count,
#   and deserializes bytes into an integer.
#
# Parameters:
#   nbytes (int): Number of bytes to read.
#   intType (IntegerType): Integer type for deserialization.
#
# Returns:
#   int: Deserialized integer.
#
# Exceptions:
#   IOError: If reading specified bytes fails.
#   KeyError: If intType is unrecognized in type_mapping.
# ----------------------------------------------------------------------------------------------

def read_and_deserialize(nbytes: int, intType: IntegerType) -> int:
    global totalBytesRead
    global calculatedCRC
    global binaryFile

    bytes_read = binaryFile.read(nbytes)
    if len(bytes_read) != nbytes:
        raise IOError(f"Tried to read {nbytes} bytes from the binary file, but failed.")

    calculatedCRC = crc32(bytes_read, calculatedCRC) & 0xffffffff
    totalBytesRead += nbytes

    try:
        format_str = f'{BIG_ENDIAN}{type_mapping[intType.name]}'
    except KeyError:
        raise KeyError(f"Unrecognized JSON Dictionary Type: {intType}")
    data = struct.unpack(format_str, bytes_read)[0]


    return data

# -----------------------------------------------------------------------------------------------------------------------
# Function: get_struct_type
#
# Description: 
#   Searches for a structure with a matching identifier in a list of type definitions
#   and returns the matching structure if found.
#
# Parameters:
#   typeList (List[TypeDef]): A list of type definitions to search through.
#   identifier (str): The identifier to match against the qualifiedName attribute of each structure.
#
# Returns:
#   TypeDef: The structure that matches the identifier, or None if no match is found.
#
# Exceptions:
#   No explicit exceptions are raised by this function.
# -----------------------------------------------------------------------------------------------------------------------

def get_struct_type(typeList: List[TypeDef], identifier: str) -> TypeDef:

    for structure in typeList:
        if structure.qualifiedName == identifier:
            return structure

    return None

# -----------------------------------------------------------------------------------------------------------------------
# Function: read_field
#
# Description: 
#   Reads and deserializes a field from a binary file, determining the field's size and type
#   based on the provided configuration, which may be an integer, float, or boolean.
#
# Parameters:
#   field_config (Union[IntegerType, FloatType, BoolType]): Configuration specifying the type and size
#   of the field to read.
#
# Returns:
#   Union[int, float, bool]: The deserialized value of the field, which can be an integer, float, or boolean.
#
# Exceptions:
#   AssertionError: If the field_config is not an IntegerType, FloatType, or BoolType.
# -----------------------------------------------------------------------------------------------------------------------

def read_field(field_config: Union[IntegerType, FloatType, BoolType]) -> Union[int, float, bool]:

    if type(field_config) is IntegerType:
        sizeBytes = field_config.size // 8

    elif type(field_config) is FloatType:
        sizeBytes = field_config.size // 8

    elif type(field_config) is BoolType:
        sizeBytes = field_config.size // 8

    else:
        assert False, "Unsupported typeKind encountered"

    return read_and_deserialize(sizeBytes, field_config)


# -----------------------------------------------------------------------------------------------------------------------
# Function: get_struct_item
#
# Description: 
#   This function recursively reads and processes a field from a binary file, adding it to a parent dictionary.
#   The process varies depending on the field's type:
#   - For basic types (IntegerType, FloatType, BoolType), it directly reads and assigns the value.
#   - For EnumType, it reads the value, finds the corresponding enum identifier, and assigns it.
#   - For ArrayType, it creates a list, iteratively fills it with elements read recursively, and assigns the list.
#   - For StructType, it constructs a nested dictionary by recursively processing each struct member.
#   - For QualifiedType, it resolves the actual type from typeList and recursively processes the field.
#   This approach allows the function to handle complex, nested data structures by adapting to the field's type,
#   ensuring each is read and stored appropriately in the parent dictionary.
#
# Parameters:
#   field_name (str): The name of the field to be read and added to the dictionary.
#   typeKind (TypeKind): The type information of the field, determining how it should be read.
#   typeList (List[TypeDef]): A list of type definitions, used for resolving qualified types.
#   parent_dict (Dict[str, int]): The dictionary to which the read field value will be added.
#
# Returns:
#   None: The function does not return a value but modifies parent_dict in place.
#
# Exceptions:
#   AssertionError: If an unsupported typeKind is encountered.

#
# -----------------------------------------------------------------------------------------------------------------------

def get_struct_item(field_name: str, typeKind: TypeKind, typeList: List[TypeDef], parent_dict: Dict[str, int]):

    if isinstance(typeKind, IntegerType):
        parent_dict[field_name] = read_field(typeKind)

    elif isinstance(typeKind, FloatType):
        parent_dict[field_name] = read_field(typeKind)

    elif isinstance(typeKind, BoolType):
        parent_dict[field_name] = read_field(typeKind)


    elif isinstance(typeKind, EnumType):
        value = read_field(typeKind.representationType)
        enum_mapping = typeKind.enumeratedConstants
        reverse_mapping = {enum.value: enum.name for enum in enum_mapping}
        parent_dict[field_name] = reverse_mapping[value]


    elif isinstance(typeKind, ArrayType):
        array_list = []
        for item in range(typeKind.size):
            element_dict = {} 
            get_struct_item("arrayElement", typeKind.elementType, typeList, element_dict)
            array_list.append(element_dict["arrayElement"]) 
        parent_dict[field_name] = array_list

    elif isinstance(typeKind, StructType):
        array_list = []
        for key, member in typeKind.members.items():
            for i in range(member.size):
                element_dict = {}
                get_struct_item(key, member.type, typeList, element_dict)
                #array_list.append(element_dict[key])
                array_list.append(element_dict)
            parent_dict[field_name] = array_list

    elif isinstance(typeKind, QualifiedType):
        qualType = get_struct_type(typeList, typeKind.name)
        get_struct_item(field_name, qualType, typeList, parent_dict)

    else:
        assert False, "Unsupported typeKind encountered"


# -----------------------------------------------------------------------------------------------------------------------
# Function: get_header_info
#
# Description: 
#   Extracts header information from a given DPHeader object, populating and returning a dictionary with the data.
#   Iterates over header fields, reading each and updating a root dictionary with the field values. After processing all fields,
#   it reads and compares the header hash with a computed CRC value to verify data integrity. If the CRC check fails, it raises
#   a CRCError. This function demonstrates a pattern of using global variables and custom exceptions to manage and validate
#   binary data parsing.
#
# Parameters:
#   headerJSON (DPHeader): The DPHeader object containing header information and type definitions.
#
# Returns:
#   Dict[str, int]: A dictionary populated with the header fields and their corresponding values.
#
# Exceptions:
#   CRCError: Raised if the computed CRC does not match the expected header hash value.
# -----------------------------------------------------------------------------------------------------------------------

def get_header_info(headerJSON: DPHeader) -> Dict[str, int]:
    global calculatedCRC

    header_fields = headerJSON.header
    rootDict = {}

    for field_name, field_info in header_fields.items():
        get_struct_item(field_name, field_info.type, headerJSON.typeDefinitions, rootDict)

    computedHash = calculatedCRC
    rootDict['headerHash'] = read_field(headerJSON.headerHash.type)
    calculatedCRC = 0

    if rootDict['headerHash'] != computedHash:
        raise CRCError("Header", rootDict['headerHash'], computedHash)

    return rootDict

# ------------------------------------------------------------------------------------------
# Function: get_record_data
#
# Description:
#     Retrieves and processes the record data based on a given header and dictionary
#     definition. The function first reads the 'dataId' from the header to identify the
#     relevant record. It then processes the record's data, handling both scalar values and
#     arrays by reading each item according to its type. For arrays, it also reads the
#     'dataSize' from the header to determine the number of items to process.
#
# Parameters:
#     - headerJSON (DPHeader): An object containing the header information, including
#       identifiers and sizes for the data to be processed.
#     - dictJSON (FprimeDict): An object containing definitions for records and types,
#       which are used to process the data correctly.
#
# Returns:
#     Dict[str, int]: A dictionary with the processed data, including 'dataId', optionally
#     'size' for arrays, and the data itself. For arrays, the data is indexed by its position
#     within the array.

# ------------------------------------------------------------------------------------------

def get_record_data(headerJSON: DPHeader, dictJSON: FprimeDict) -> Dict[str, int]:
    rootDict = {}
    # Go through all the Records and find the one that matches recordId
    rootDict['dataId'] = read_field(headerJSON.dataId.type)
    for record in dictJSON.records:
        if record.id == rootDict['dataId']:    
            print(f'Processing Record ID {record.id}')
            if record.array:
                dataSize = read_field(headerJSON.dataSize.type)
                rootDict['size'] = dataSize
                array_data = []
                for i in range(dataSize):
                    element_dict = {}
                    get_struct_item("arrayElement", record.type, dictJSON.typeDefinitions, element_dict)
                    array_data.append(element_dict["arrayElement"])
                rootDict['data'] = array_data
            else:
                # For non-array records, directly use 'data' as the key.
                get_struct_item("data", record.type, dictJSON.typeDefinitions, rootDict)

            return rootDict
    raise RecordIDNotFound(rootDict['dataId'])

# --------------------------------------------------------------------------------------------------
# class RecordIDNotFound
# 
# Description: 
#   Custom exception class for signaling the absence of a specified record ID in a JSON dictionary. 
#   It stores the missing record ID and provides a descriptive error message when invoked.
#
# Attributes:
#   recordId: The missing record ID.
#
# Methods:
#   __init__(self, recordId): Initializes the exception with the missing record ID.
#   __str__(self): Returns an error message indicating the missing record ID.
# ---------------------------------------------------------------------------------------------------

class RecordIDNotFound(Exception):
    
    def __init__(self, recordId):
        self.recordId = recordId
        
    def __str__(self):
        return f"Record ID {self.recordId} was not found in the JSON dictionary"
    
# ----------------------------------------------------------------------------------------------------------------
# class DictionaryError
# 
# Description: 
#   Custom exception class for signaling errors while parsing a JSON dictionary file.
#   It stores the file name and the line number where the error occurred, providing context in the error message.
#
# Attributes:
#   jsonFile: The name of the JSON file being parsed.
#   lineNo: The line number in the file where the error was detected.
#
# Methods:
#   __init__(self, jsonFile, lineNo): Initializes the exception with the JSON file name and the line number.
#   __str__(self): Returns an error message indicating the file and line number where the error occurred.
# ----------------------------------------------------------------------------------------------------------------
    
class DictionaryError(Exception):
    
    def __init__(self, jsonFile, lineNo):
        self.jsonFile = jsonFile
        self.lineNo = lineNo
        
    def __str__(self):
        return f"DictionaryError parsing {self.jsonFile}, line number: {self.lineNo}"

# -------------------------------------------------------------------------------------------------------------------
# class CRCError
# 
# Description: 
#   Custom exception class for signaling CRC hash mismatches during data validation.
#   It specifies whether the error occurred in the header or data, the expected CRC value, and the calculated CRC value.
#
# Attributes:
#   headerOrData: Indicates whether the mismatch occurred in the header or the data section.
#   expected: The expected CRC value.
#   calculated: The calculated CRC value that did not match the expected value.
#
# Methods:
#   __init__(self, headerOrData, expected, calculated): Initializes the exception with details of the mismatch.
#   __str__(self): Returns an error message detailing the mismatch with expected and calculated CRC values.
# --------------------------------------------------------------------------------------------------------------------
    
class CRCError(Exception):
    
    def __init__(self, headerOrData, expected, calculated):
        self.headerOrData = headerOrData
        self.expected = expected
        self.calculated = calculated
        
    def __str__(self):
        return f"CRC Hash mismatch for {self.headerOrData}: Expected {self.expected:#x}, Calculated {self.calculated:#x}"

# --------------------------------------------------------------------------------------------------------------------
# class DuplicateRecordID
#
# Description: 
#   Custom exception class for indicating the presence of a duplicate record identifier in a JSON dictionary.
#   It stores the duplicate identifier and provides a descriptive error message when invoked.
#
# Attributes:
#   identifier: The duplicate record identifier that triggered the exception.
#
# Methods:
#   __init__(self, identifier): Initializes the exception with the duplicate identifier.
#   __str__(self): Returns an error message indicating the duplicate record identifier.
# ----------------------------------------------------------------------------------------------------------------------
class DuplicateRecordID(Exception):
    
    def __init__(self, identifier):
        self.identifier = identifier
        
    def __str__(self):
        return f"In the Dictionary JSON there is a duplicate Record identifier: {self.identifier}"

# --------------------------------------------------------------------------------------------------------------------
# Function handleException
# 
# Description: 
#   Function for handling exceptions by displaying an error message and terminating the program.
#   It displays the provided exception message with color-coded output for emphasis. 
#   After displaying the messages, it immediately exits the program, halting further execution.
#
# Parameters:
#   msg (str): The specific error message to be displayed.
#
# Returns:
#   None: This function does not return a value. It terminates the program execution with sys.exit().
#
# Exceptions:
#   No explicit exceptions are raised by this function, but it triggers the program's termination.
# -----------------------------------------------------------------------------------------------------------------
def handleException(msg):
    errorMessage = f"*** Error in processing: "
    print(bcolors.FAIL)
    print(errorMessage)
    print(bcolors.WARNING)
    print(msg)
    print(bcolors.ENDC)
    sys.exit()


# -------------------------------------------------------------------------------------------------------------------------
# Function check_record_data
#
# Description: 
#   Validates record data in a given dictionary JSON object by ensuring there are no duplicate record identifiers.
#   Iterates through the records in the dictionary, checking each record's identifier against a set that 
#   tracks unique identifiers.  If a duplicate identifier is detected, a DuplicateRecordID exception is raised.
#
# Parameters:
#   dictJSON (FprimeDict): The dictionary JSON object containing records to be validated.
#
# Returns:
#   None: This function does not return a value. It either completes successfully or raises an exception.
#
# Exceptions:
#   DuplicateRecordID: Raised if a duplicate record identifier is found in the dictionary JSON object.

# -----------------------------------------------------------------------------------------------------------------------
def check_record_data(dictJSON: FprimeDict):
    idSet = set()
    for record in dictJSON.records:
        if record.id in idSet:
            raise DuplicateRecordID(record.id)
        else:
            idSet.add(record.id)

# -------------------------------------------------------------------------------------------------------------------------
# Function parse_args
#
# Description: 
#   Parse the input arguments either as passed into this function or on the command line
# -------------------------------------------------------------------------------------------------------------------------
def parse_args(args=None):
    parser = argparse.ArgumentParser(description='Data Product Writer.')
    parser.add_argument('binFile', help='Data Product Binary file')
    parser.add_argument('jsonDict', help='JSON Dictionary')
    if args is None:
        args = sys.argv[1:]
    return parser.parse_args(args)


# -------------------------------------------------------------------------------------------------------------------------
# Function process
#
# Description: 
#   Main processing
# -------------------------------------------------------------------------------------------------------------------------
def process(args):
    global binaryFile
    global calculatedCRC
    global totalBytesRead

    try:

        # Read the F prime JSON dictionary
        print(f"Parsing {args.jsonDict}...")
        try:
            with open(args.jsonDict, 'r') as fprimeDictFile:
                dictJSON = FprimeDict(**json.load(fprimeDictFile))
        except json.JSONDecodeError as e:
            raise DictionaryError(args.jsonDict, e.lineno)
        
        check_record_data(dictJSON)

        headerJSON = DPHeader(**header_data)

        with open(args.binFile, 'rb') as binaryFile:

            totalBytesRead = 0
            calculatedCRC = 0

            # Read the header data up until the Records
            headerData = get_header_info(headerJSON)

            # Read the total data size
            dataSize = headerData['DataSize']

            # Restart the count of bytes read
            totalBytesRead = 0

            recordList = [headerData]

            while totalBytesRead < dataSize:

                recordData = get_record_data(headerJSON, dictJSON)
                recordList.append(recordData)

            computedCRC = calculatedCRC
            # Read the data checksum
            headerData['dataHash'] = read_field(headerJSON.dataHash.type)

            if computedCRC != headerData['dataHash']:
                raise CRCError("Data", headerData['dataHash'], computedCRC)


    except (FileNotFoundError, RecordIDNotFound, IOError, KeyError, json.JSONDecodeError, 
            DictionaryError, CRCError, DuplicateRecordID) as e:
        handleException(e)

    except (ValueError) as e:
        error = e.errors()[0]
        msg = f'ValueError in JSON file {error["loc"]}: {error["msg"]}'
        handleException(msg)


    # Output the generated json to a file
    baseName = os.path.basename(args.binFile)
    outputJsonFile = os.path.splitext(baseName)[0] + '.json'
    if outputJsonFile.startswith('._'):
        outputJsonFile = outputJsonFile.replace('._', '')
    with open(outputJsonFile, 'w') as file:
        json.dump(recordList, file, indent=2)

    print(f'Output data generated in {outputJsonFile}')


# ------------------------------------------------------------------------------------------
# main program
#
# ------------------------------------------------------------------------------------------
def main():
    args = parse_args()
    process(args)


if __name__ == "main":
    sys.exit(main())


