####
# json.py:
#
# Encodes GDS objects as JSON.
####
import collections.abc
import enum
import inspect

from fprime.common.models.serialize.type_base import BaseType
from fprime_gds.common.utils.jsonable import jsonify_base_type

import flask.json


class GDSJsonEncoder(flask.json.JSONEncoder):
    """
    Custom class used to handle GDS object to JSON
    """

    def default(self, obj):
        """
        Override the default JSON encoder to pull out a dictionary for our handled types for encoding with the default
        encoder built into flask

        :param obj: obj to encode
        :return: JSON
        """
        # Object may already define a method for this, if so call it
        if inspect.isclass(obj) and issubclass(obj, BaseType):
            return jsonify_base_type(obj)
        if hasattr(obj, "to_jsonable"):
            return obj.to_jsonable()
        # Dictionaries are "iterable", must handle them first
        elif isinstance(obj, collections.abc.Mapping):
            return flask.json.JSONEncoder.default(self, obj)
        # Enumerations, just return the list of values
        elif isinstance(obj, enum.Enum):
            enum_dict = {"value": str(obj), "values": {}}
            for enum_val in type(obj):
                enum_dict["values"][str(enum_val)] = enum_val.value
            return enum_dict
        # Lists and iterables
        try:
            return list(iter(obj))
        except TypeError:
            pass
        return flask.json.JSONEncoder.default(self, obj)
