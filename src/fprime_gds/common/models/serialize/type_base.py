"""
Created on Dec 18, 2014

@author: reder
Replaced type base class with decorators
"""

import abc

from .type_exceptions import AbstractMethodException


class BaseType(abc.ABC):
    """
    An abstract base defining the methods supported by all base classes.
    """

    @abc.abstractmethod
    def serialize(self):
        """
        Serializes the current object type.
        """
        raise AbstractMethodException("serialize")

    @abc.abstractmethod
    def deserialize(self, data, offset):
        """
        AbstractDeserialize interface
        """
        raise AbstractMethodException("deserialize")

    @abc.abstractmethod
    def getSize(self):
        """
        Abstract getSize interface
        """
        raise AbstractMethodException("getSize")

    @classmethod
    @abc.abstractmethod
    def getMaxSize(cls):
        """Get maximum size of the type"""
        return AbstractMethodException("getMaxSize")

    def __repr__(self):
        """Produces a string representation of a given type"""
        return self.__class__.__name__.replace("Type", "")

    @abc.abstractmethod
    def to_jsonable(self):
        """
        Converts this type to a JSON serializable object
        """
        raise AbstractMethodException("to_jsonable")


class ValueType(BaseType):
    """
    An abstract base type used to represent a single value. This defines the value property, allowing for setting and
    reading from the .val member.
    """

    def __init__(self, val=None):
        """Defines the single value"""
        self._val = None
        # Run full setter
        if val is not None:
            self.val = val

    @classmethod
    @abc.abstractmethod
    def validate(cls, val):
        """
        Checks the val for validity with respect to the current type. This will raise TypeMismatchException when the
        validation fails of the val's type fails. It will raise TypeRangeException when val is out of range. Concrete
        implementations will raise other exceptions based on type. For example, serializable types raise exceptions for
        missing members.

        :param val: value to validate
        :raises TypeMismatchException: value has incorrect type, TypeRangeException: val is out of range
        """

    def __eq__(self, other):
        """Check equality between types"""
        return False if type(other) != type(self) else self._val == other._val

    @property
    def val(self):
        """Getter for .val"""
        return self._val

    @val.setter
    def val(self, val):
        """Setter for .val calls validate internally"""
        self.validate(val)
        self._val = val

    def to_jsonable(self):
        """
        Converts this type to a JSON serializable object
        """
        return {"value": self.val, "type": str(self.__class__)}


class DictionaryType(ValueType, abc.ABC):
    """Type whose specification is defined in the dictionary

    Certain types in fprime (strings, serializables, enums) are defined in the dictionary. Where all projects have
    access to primitive types (U8, F32, etc) and the definitions of theses types is global, other types complete
    specification comes from the dictionary itself. String set max-lengths per project, serializable fields are defined,
    and enumeration values are enumerated. This class is designed to take base complex types (StringType, etc) and build
    dynamic subclasses for the given dictionary defined type.
    """

    _CONSTRUCTS = {}

    @classmethod
    def construct_type(cls, parent_class, name, **class_properties):
        """Construct a new dictionary type

        Construct a new dynamic subtype of the given base type. This type will be named with the name parameter, define
        the supplied class properties, and will be a subtype of the parent class. This function registers these new
        types by name in the DictionaryType._CONSTRUCTS dictionary. When a type is defined a second or more times, the
        originally constructed sub type is used and the newly supplied class properties are validated for equality
        against the original definition. It is an error to define the type multiple times with inconsistent class
        properties.

        Args:
            cls: DictionaryType, used to access the class property _CONSTRUCTS
            parent_class: class used as parent to the new sub type
            name: name of the new sub type
            **class_properties: properties to define on the subtype (e.g. max length for strings)
        """
        assert (
            parent_class != DictionaryType
        ), "Cannot build dictionary type from dictionary type directly"
        construct, original_properties = cls._CONSTRUCTS.get(
            name, (type(name, (parent_class,), class_properties), class_properties)
        )
        # Validate both new properties against original properties and against what is set on original class
        assert (
            original_properties == class_properties
        ), "Different class properties specified"
        for attribute, value in class_properties.items():
            previous_value = getattr(construct, attribute, None)
            assert (
                previous_value == value
            ), f"Class {name} differs by attribute {attribute}. {previous_value} vs {value}"
        cls._CONSTRUCTS[name] = (construct, class_properties)
        return construct
