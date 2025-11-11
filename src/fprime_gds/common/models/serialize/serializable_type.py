"""
Created on Dec 18, 2014

@author: tcanham

"""

from .type_base import BaseType, DictionaryType
from .type_exceptions import (
    IncorrectMembersException,
    MissingMemberException,
    NotInitializedException,
    TypeMismatchException,
    DeserializeException,
)


class SerializableType(DictionaryType):
    """
    Representation of the Serializable type (comparable to the ANY type)

    The serializable type is a container for other instances of
    BaseType, including itself.

    @param param: typename = "SomeTypeName" string
    To preserve member order, the member argument is a list of members and their types:
    @param param: mem_list = [ ("member",<ref to BaseType>, format string, description), ... ]
    OR mem_list = [ ("member",<ref to BaseType>, format string), ... ].
    The member descriptions can be None
    """

    @classmethod
    def construct_type(cls, name, member_list):
        """Construct a new serializable sub-type

        Constructs a new serializable subtype from the supplied member list and name. Member list may optionally exclude
        description keys, which will be filled with None.

        Args:
            name: name of the new sub-type
            member_list: list of member definitions in form list of tuples (name, type, format string, description)
        """
        # Check that we are dealing with a list
        if not isinstance(member_list, list):
            raise TypeMismatchException(list, type(member_list))
        member_list = [list(item) + ([None] * (4 - len(item))) for item in member_list]
        # Check the validity of the member list
        for member_name, member_type, format_string, description in member_list:
            # Check each of these members for correct types
            if not isinstance(member_name, str):
                raise TypeMismatchException(str, type(member_name))
            if not issubclass(member_type, BaseType):
                raise TypeMismatchException(BaseType, member_type)
            if format_string is not None and not isinstance(format_string, str):
                raise TypeMismatchException(str, type(format_string))
            if description is not None and not isinstance(description, str):
                raise TypeMismatchException(str, type(description))
        return DictionaryType.construct_type(cls, name, MEMBER_LIST=member_list)

    @classmethod
    def validate(cls, val):
        """Validate this object including member list and values"""
        # Ensure that the supplied value is a dictionary
        if not isinstance(val, dict):
            raise TypeMismatchException(dict, type(val))
        if len(val) != len(cls.MEMBER_LIST):
            raise IncorrectMembersException([name for name, _, _, _ in cls.MEMBER_LIST])
        # Now validate each field as defined via the value
        for member_name, member_type, _, _ in cls.MEMBER_LIST:
            try:
                member_val = val[member_name]
            except KeyError:
                raise MissingMemberException(member_name)
            member_type.validate(member_val)

    @property
    def val(self) -> dict:
        """
        The .val property typically returns the python-native type. This the python native type closes to a serializable
        without generating full classes would be a dictionary (anonymous object). This returns such an object.

        :return dictionary of member names to python values of member keys
        """
        if self._val is None:
            return None
        return {
            member_name: self._val.get(member_name).val
            for member_name, _, _, _ in self.MEMBER_LIST
        }

    @val.setter
    def val(self, val: dict):
        """
        The .val property typically returns the python-native type. This the python native type closes to a serializable
        without generating full classes would be a dictionary (anonymous object). This takes such an object and sets the
        member val list from it.

        :param val: dictionary containing python types to key names. This
        """
        self.validate(val)
        self._val = {
            member_name: member_type(val.get(member_name))
            for member_name, member_type, _, _, in self.MEMBER_LIST
        }

    @property
    def formatted_val(self) -> dict:
        """
        Format all the members of dict according to the member_format.
        Note 1: All elements will be cast to str
        Note 2: If a member is an array will call array formatted_val
        :return a formatted dict
        """
        result = {}
        for member_name, _, member_format, _ in self.MEMBER_LIST:
            value_object = self._val[member_name]
            if hasattr(value_object, "formatted_val"):
                result[member_name] = value_object.formatted_val
            else:
                result[member_name] = member_format.format(value_object.val)
        return result

    def serialize(self):
        """Serializes the members of the serializable"""
        if self._val is None:
            raise NotInitializedException(type(self))
        return b"".join(
            [
                self._val.get(member_name).serialize()
                for member_name, _, _, _ in self.MEMBER_LIST
            ]
        )

    def deserialize(self, data, offset):
        """Deserialize the values of each of the members"""
        new_value = {}
        for member_name, member_type, _, _ in self.MEMBER_LIST:
            try:
                new_member = member_type()
                new_member.deserialize(data, offset)
                new_value[member_name] = new_member
                offset += new_member.getSize()
            except Exception as exc:
                raise DeserializeException(
                    f"Field '{member_name}' [{member_type.__name__}] failed to deserialize: {exc}"
                )
        self._val = new_value

    def getSize(self):
        """The size of a struct is the size of all the members"""
        return sum(self._val.get(name).getSize() for name, _, _, _ in self.MEMBER_LIST)

    @classmethod
    def getMaxSize(cls):
        """Return the maximum size in bytes of the array"""
        return sum(member_type.getMaxSize() for _, member_type, _, _ in cls.MEMBER_LIST)

    def to_jsonable(self):
        """
        JSONable type for a serializable
        """
        members = {}
        for member_name, member_value, member_format, member_desc in self.MEMBER_LIST:
            value = (
                {"value": None}
                if self._val is None
                else self._val.get(member_name).to_jsonable()
            )
            members[member_name] = {"format": member_format, "description": member_desc}
            members[member_name].update(value)
        return members

    def items(self):
        """Allow dictionary like iteration"""

        def items_generator():
            """Generator of items"""
            for member_name, _, _, _ in self.MEMBER_LIST:
                yield member_name, self._val.get(member_name)

        return items_generator()
