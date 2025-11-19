"""
Tests the serialization and deserialization of all the types in Fw/Python/src/fprime/common/models/serialize/

Created on Jun 25, 2020
@author: hpaulson, mstarch
"""

import json
from collections.abc import Iterable

import pytest
from fprime_gds.common.models.serialize.array_type import ArrayType
from fprime_gds.common.models.serialize.bool_type import BoolType
from fprime_gds.common.models.serialize.enum_type import EnumType
from fprime_gds.common.models.serialize.numerical_types import (
    F32Type,
    F64Type,
    I8Type,
    I16Type,
    I32Type,
    I64Type,
    U8Type,
    U16Type,
    U32Type,
    U64Type,
)
from fprime_gds.common.models.serialize.serializable_type import SerializableType
from fprime_gds.common.models.serialize.string_type import StringType
from fprime_gds.common.models.serialize.time_type import TimeType
from fprime_gds.common.models.serialize.type_base import (
    BaseType,
    DictionaryType,
    ValueType,
)
from fprime_gds.common.models.serialize.type_exceptions import (
    AbstractMethodException,
    ArrayLengthException,
    DeserializeException,
    EnumMismatchException,
    IncorrectMembersException,
    MissingMemberException,
    NotInitializedException,
    StringSizeException,
    TypeMismatchException,
    TypeRangeException,
)

PYTHON_TESTABLE_TYPES = [
    True,
    False,
    -1,
    0,
    300,
    "abc",
    "True",
    "False",
    3.1412,
    (0, 1),
    (True, False),
    [],
    [0],
    {},
    {"abc": 123},
    {2, 4, 3},
]


def valid_values_test(type_input, valid_values, sizes):
    """Tests to be run on all types"""
    if not isinstance(sizes, Iterable):
        sizes = [sizes] * len(valid_values)

    instantiation = type_input()
    with pytest.raises(NotInitializedException):
        instantiation.serialize()
    assert instantiation.val is None
    # Setting to None is invalid
    with pytest.raises(TypeMismatchException):
        instantiation.val = None
    # Should be able to get a JSONable object that is dump-able to a JSON string
    jsonable = instantiation.to_jsonable()
    json.loads(json.dumps(jsonable))

    # Run on valid values
    for value, size in zip(valid_values, sizes):
        instantiation = type_input(val=value)
        assert instantiation.val == value
        assert instantiation.getSize() == size

        # Check assignment by value
        by_value = type_input()
        by_value.val = value
        assert by_value.val == instantiation.val, "Assignment by value has failed"
        assert by_value.getSize() == size

        # Check that the value returned by .val is also assignable to .val
        by_value.val = by_value.val

        # Check serialization and deserialization
        serialized = instantiation.serialize()
        for offset in [0, 10, 50]:
            deserializer = type_input()
            deserializer.deserialize((b" " * offset) + serialized, offset)
            assert instantiation.val == deserializer.val, "Deserialization has failed"
            assert deserializer.getSize() == size
            # Check another get/set pair and serialization of the post-deserialized object
            deserializer.val = deserializer.val
            new_serialized_bytes = deserializer.serialize()
            assert (
                serialized == new_serialized_bytes
            ), "Repeated serialization has failed"
    return instantiation


def invalid_values_test(
    type_input, invalid_values, exception_class=TypeMismatchException
):
    """Check invalid values for all types"""
    for item in invalid_values:
        # Constructor initialization
        with pytest.raises(exception_class):
            instantiation = type_input(item)
        # Value initialization
        with pytest.raises(exception_class):
            instantiation = type_input()
            instantiation.val = item
        # Deserialization problems required space
        for offset in [0, 10, 50]:
            with pytest.raises(DeserializeException):
                instantiation = type_input()
                instantiation.deserialize(b" " * offset, offset)


def ser_deser_time_test(t_base, t_context, secs, usecs):
    """
    Test serialization/deserialization of TimeType objects.

    This test function creates a time type object with the given parameters and
    then serializes it and deserializes it. Also prints it for visual inspection
    of the formatted output.

    Args:
        t_base (TimeType.TimeBase): Time base for the new time type object
        t_context (int): Time context for the new time type object
        secs (int): Seconds value for the new time type object
        usecs (int): Seconds value for the new time type object
        should_err (int): True if error expected, else False

    Returns:
        True if test passed, False otherwise
    """
    val = TimeType(t_base, t_context, secs, usecs)

    buff = val.serialize()

    val2 = TimeType()
    val2.deserialize(buff, 0)

    assert val2.timeBase == t_base
    assert val2.timeContext == t_context
    assert val2.seconds == secs
    assert val2.useconds == usecs


def test_boolean_nominal():
    """Tests the nominal cases of a BoolType"""
    instance = valid_values_test(BoolType, [True, False], 1)
    # Make sure max size is the same as the size and can be derived from the class
    assert instance.getSize() == instance.__class__.getMaxSize()


def test_boolean_off_nominal():
    """Tests the nominal cases of a BoolType"""
    invalid_values_test(
        BoolType, filter(lambda item: not isinstance(item, bool), PYTHON_TESTABLE_TYPES)
    )


def test_int_types_nominal():
    """Tests the integer types"""
    for type_input, size in [(I8Type, 1), (I16Type, 2), (I32Type, 4), (I64Type, 8)]:
        total = pow(2, (size * 8) - 1)
        instance = valid_values_test(type_input, [0, -1, 1, -total, total - 1], size)
        # Make sure max size is the same as the size and can be derived from the class
        assert instance.getSize() == instance.__class__.getMaxSize()


def test_int_types_off_nominal():
    """Tests the integer off nominal types"""
    for type_input, size in [(I8Type, 1), (I16Type, 2), (I32Type, 4), (I64Type, 8)]:
        total = pow(2, (size * 8) - 1)
        invalid_values_test(
            type_input,
            filter(lambda item: not isinstance(item, int), PYTHON_TESTABLE_TYPES),
        )
        invalid_values_test(
            type_input, [-total - 1, total, -total * 35, total * 35], TypeRangeException
        )


def test_uint_types_nominal():
    """Tests the integer types"""
    for type_input, size in [(U8Type, 1), (U16Type, 2), (U32Type, 4), (U64Type, 8)]:
        max_int = pow(2, (size * 8)) - 1
        instance = valid_values_test(type_input, [0, 1, max_int - 1, max_int], size)
        # Make sure max size is the same as the size and can be derived from the class
        assert instance.getSize() == instance.__class__.getMaxSize()


def test_uint_types_off_nominal():
    """Tests the integer off nominal types"""
    for type_input, size in [(U8Type, 1), (U16Type, 2), (U32Type, 4), (U64Type, 8)]:
        max_int = pow(2, (size * 8)) - 1
        invalid_values_test(
            type_input,
            filter(lambda item: not isinstance(item, int), PYTHON_TESTABLE_TYPES),
        )
        invalid_values_test(
            type_input,
            [-1, -2, max_int + 1, max_int * 35, -max_int],
            TypeRangeException,
        )


def test_float_types_nominal():
    """Tests the integer types"""
    instance = valid_values_test(
        F32Type, [0.31415000557899475, 0.0, -3.141590118408203], 4
    )
    # Make sure max size is the same as the size and can be derived from the class
    assert instance.getSize() == instance.__class__.getMaxSize()
    instance = valid_values_test(
        F64Type, [0.31415000557899475, 0.0, -3.141590118408203], 8
    )
    # Make sure max size is the same as the size and can be derived from the class
    assert instance.getSize() == instance.__class__.getMaxSize()


def test_float_types_off_nominal():
    """Tests the integer off nominal types"""
    invalid_values_test(
        F32Type,
        filter(lambda item: not isinstance(item, (float, int)), PYTHON_TESTABLE_TYPES),
    )
    invalid_values_test(
        F64Type,
        filter(lambda item: not isinstance(item, (float, int)), PYTHON_TESTABLE_TYPES),
    )


def test_enum_nominal():
    """
    Tests the EnumType serialization and deserialization
    """
    members = {"MEMB1": 0, "MEMB2": 6, "MEMB3": 9}
    enum_class = EnumType.construct_type("SomeEnum", members)
    valid = ["MEMB1", "MEMB2", "MEMB3"]
    instance = valid_values_test(enum_class, valid, [4] * len(valid))
    # Make sure max size is the same as the size and can be derived from the class
    assert instance.getSize() == instance.__class__.getMaxSize()


def test_enum_off_nominal():
    """
    Tests the EnumType serialization and deserialization
    """
    members = {"MEMB1": 0, "MEMB2": 6, "MEMB3": 9}
    enum_class = EnumType.construct_type("SomeEnum", members)
    invalid = ["MEMB12", "MEMB22", "MEMB23"]
    invalid_values_test(enum_class, invalid, EnumMismatchException)
    invalid_values_test(
        enum_class,
        filter(lambda item: not isinstance(item, str), PYTHON_TESTABLE_TYPES),
    )


def test_string_nominal():
    """Tests named string types"""
    py_string = "ABC123DEF456"
    string_type = StringType.construct_type("MyFancyString", max_length=10)
    instance = valid_values_test(
        string_type, [py_string[:10], py_string[:4], py_string[:7]], [12, 6, 9]
    )
    # String type defined a max-size of 10 plus 2 for the size data
    assert instance.__class__.getMaxSize() == 10 + 2


def test_string_off_nominal():
    """Tests named string types"""
    py_string = "ABC123DEF456"
    string_type = StringType.construct_type("MyFancyString", max_length=10)
    invalid_values_test(string_type, [py_string], StringSizeException)
    invalid_values_test(
        string_type,
        filter(lambda item: not isinstance(item, str), PYTHON_TESTABLE_TYPES),
    )


def test_serializable_basic():
    """Serializable type with basic member types"""
    member_list = [
        [
            ("member1", U32Type, "%d"),
            ("member2", U32Type, "%lu"),
            ("member3", I64Type, "%lld"),
        ],
        [
            (
                "member4",
                StringType.construct_type("StringMember1", max_length=10),
                "%s",
            ),
            ("member5", StringType.construct_type("StringMember2", max_length=4), "%s"),
            ("member6", I64Type, "%lld"),
        ],
    ]
    valid_values = [
        ({"member1": 123, "member2": 456, "member3": -234}, 4 + 4 + 8, 4 + 4 + 8),
        ({"member4": "345", "member5": "abc1", "member6": 213}, 5 + 6 + 8, 12 + 6 + 8),
    ]

    for index, (members, (valid, size, max_size)) in enumerate(
        zip(member_list, valid_values)
    ):
        serializable_type = SerializableType.construct_type(
            f"BasicSerializable{index}", members
        )
        instance = valid_values_test(serializable_type, [valid], [size])
        assert (
            instance.__class__.getMaxSize() == max_size
        )  # Sum of sizes of member list


def test_serializable_basic_off_nominal():
    """Serializable type with basic member types"""
    member_list = [
        ("member1", U32Type, "%d"),
        ("member2", StringType.construct_type("StringMember1", max_length=10), "%s"),
    ]
    serializable_type = SerializableType.construct_type(
        "BasicInvalidSerializable", member_list
    )

    invalid_values = [
        ({"member5": 123, "member6": 456}, MissingMemberException),
        ({"member1": "345", "member2": 123}, TypeMismatchException),
        (
            {"member1": 345, "member2": "234", "member3": "Something"},
            IncorrectMembersException,
        ),
    ]

    for valid, exception_class in invalid_values:
        invalid_values_test(serializable_type, [valid], exception_class)
    invalid_values_test(
        serializable_type,
        filter(lambda item: not isinstance(item, dict), PYTHON_TESTABLE_TYPES),
    )


def test_serializable_advanced():
    """
    Tests the SerializableType serialization and deserialization
    """

    # First setup some classes to represent various member types ensuring that the serializable can handle them
    string_member_class = StringType.construct_type("StringMember", max_length=3)
    enum_member_class = EnumType.construct_type(
        "EnumMember", {"Option1": 0, "Option2": 6, "Option3": 9}
    )
    array_member_class = ArrayType.construct_type(
        "ArrayMember", string_member_class, 3, "%s"
    )
    sub_serializable_class = SerializableType.construct_type(
        "AdvancedSubSerializable",
        [("subfield1", U32Type), ("subfield2", array_member_class)],
    )

    field_data = [
        ("field1", string_member_class),
        ("field2", U32Type),
        ("field3", enum_member_class),
        ("field4", array_member_class),
        ("field5", sub_serializable_class),
    ]
    serializable_class = SerializableType.construct_type(
        "AdvancedSerializable", field_data
    )

    serializable1 = {
        "field1": "abc",
        "field2": 123,
        "field3": "Option2",
        "field4": ["", "123", "6"],
        "field5": {"subfield1": 3234, "subfield2": ["abc", "def", "abc"]},
    }
    instance = valid_values_test(
        serializable_class,
        [serializable1],
        [5 + 4 + 4 + (2 + 5 + 3) + (4 + (5 + 5 + 5))],
    )
    assert instance.__class__.getMaxSize() == (
        5 + 4 + 4 + (3 * 5) + (4 + (3 * 5))
    )  # Sum of sizes of member list


def test_array_type():
    """
    Tests the ArrayType serialization and deserialization
    """
    extra_ctor_args = [
        ("TestArray", I32Type, 2, "%d"),
        ("TestArray2", U8Type, 4, "%d"),
        (
            "TestArray3",
            StringType.construct_type("TestArrayString", max_length=18),
            3,
            "%s",
        ),
    ]
    values = [[32, 1], [0, 1, 2, 3], ["one", "1234", "1"]]
    sizes = [8, 4, 14]
    max_sizes = [8, 4, (2 + 18) * 3]
    for ctor_args, values, size, max_size in zip(
        extra_ctor_args, values, sizes, max_sizes
    ):
        type_input = ArrayType.construct_type(*ctor_args)
        instance = valid_values_test(type_input, [values], [size])
        assert instance.__class__.getMaxSize() == max_size


def test_array_type_off_nominal():
    """
    Test the array type for invalid values etc
    """
    type_input = ArrayType.construct_type("TestArrayPicky", I32Type, 4, "%d")
    invalid_inputs = [
        ([1, 2, 3], ArrayLengthException),
        ([1, 2, 3, 4, 5, 6], ArrayLengthException),
        (["one", "two", "three", "four"], TypeMismatchException),
    ]
    for invalid, exception_class in invalid_inputs:
        invalid_values_test(type_input, [invalid], exception_class)
    invalid_values_test(
        type_input,
        filter(lambda item: not isinstance(item, (list, tuple)), PYTHON_TESTABLE_TYPES),
    )


def test_time_type():
    """
    Tests the TimeType serialization and deserialization
    """
    TIME_SIZE = 11

    in_no_err_list = [
        (TimeType.TimeBase("TB_NONE"), 1, 100, 999999),
        (TimeType.TimeBase("TB_PROC_TIME"), 0xFF, 1234567, 2952),
        (TimeType.TimeBase("TB_WORKSTATION_TIME"), 8, 1529430215, 12),
        (TimeType.TimeBase("TB_SC_TIME"), 231, 1344230277, 123456),
        (TimeType.TimeBase("TB_FPGA_TIME"), 78, 10395, 24556),
        (TimeType.TimeBase("TB_DONT_CARE"), 0xB3, 12390819, 12356),
    ]

    in_err_list = [
        (TimeType.TimeBase("TB_NONE"), 1, 3, -1),
        (TimeType.TimeBase("TB_WORKSTATION_TIME"), 1, 700000, 1234567),
    ]

    val = TimeType()
    size = val.getSize()
    assert size == TIME_SIZE
    assert val.getMaxSize() == TIME_SIZE

    for t_base, t_context, secs, usecs in in_no_err_list:
        ser_deser_time_test(t_base, t_context, secs, usecs)

    for t_base, t_context, secs, usecs in in_err_list:
        with pytest.raises(TypeRangeException):
            ser_deser_time_test(t_base, t_context, secs, usecs)


class Dummy(BaseType):
    def serialize(self):
        return "serialized"

    def deserialize(self, data, offset):
        super(Dummy, self).deserialize(data, offset)
        return "deserialized"

    def getSize(self):
        return 0

    @classmethod
    def getMaxSize(cls):
        return 902

    def to_jsonable(self):
        return {"name": "dummy"}


def test_base_type():
    with pytest.raises(TypeError) as exception:
        BaseType()

    assert "Can't instantiate abstract class" in str(exception.value)

    with pytest.raises(TypeError) as exception2:
        ValueType()

    assert "Can't instantiate abstract class" in str(exception2.value)

    d = Dummy()
    assert d.serialize() == "serialized"
    assert d.getSize() == 0
    assert Dummy.getMaxSize() == 902
    assert d.getMaxSize() == 902

    with pytest.raises(AbstractMethodException):
        # In the Dummy class above, the deserialize method
        # is set to call the super class, which is just the
        # raw abstract method, which is the only way to
        # raise an `AbstractMethodException`.
        d.deserialize("a", 0)


def test_dictionary_type_errors():
    """Ensure the dictionary type is preventing errors"""
    # Check no raw calls passing in DictionaryType
    with pytest.raises(AssertionError):
        DictionaryType.construct_type(
            DictionaryType, "MyNewString", PROPERTY="one", PROPERTY2="two"
        )

    # Check consistent field definitions: field values
    DictionaryType.construct_type(str, "MyNewString1", PROPERTY="one", PROPERTY2="two")
    with pytest.raises(AssertionError):
        DictionaryType.construct_type(
            str, "MyNewString1", PROPERTY="three", PROPERTY2="four"
        )

    # Check consistent field definitions: field names
    DictionaryType.construct_type(str, "MyNewString2", PROPERTY1="one", PROPERTY2="two")
    with pytest.raises(AssertionError):
        DictionaryType.construct_type(
            str, "MyNewString2", PROPERTY="one", PROPERTY3="two"
        )

    # Check consistent field definitions: missing field
    DictionaryType.construct_type(str, "MyNewString3", PROPERTY1="one", PROPERTY2="two")
    with pytest.raises(AssertionError):
        DictionaryType.construct_type(str, "MyNewString3", PROPERTY1="one")
