####
# json.py:
#
# Encodes GDS objects as JSON.
####
from abc import ABCMeta
from enum import Enum
from inspect import getmembers, isroutine, isclass
from typing import Type

from fprime.common.models.serialize.type_base import BaseType
from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.data_types.event_data import EventData
from uuid import UUID
import flask.json


def jsonify_base_type(input_type: Type[BaseType]) -> dict:
    """ Turn a base type into a JSONable dictionary

    Convert a BaseType (the type, not an instance) into a jsonable dictionary. BaseTypes are converted by reading the
    class properties (without __) and creating the object:

    {
        "name": class name,
        class properties
    }

    Args:
        input_type: input to convert to dictionary
    Return:
        json-able dictionary representing the type
    """
    assert issubclass(input_type, BaseType), "Failure to properly encode data"
    members = getmembers(input_type, lambda value: not isroutine(value) and not isinstance(value, property))
    jsonable_dict = {name: value for name, value in members if not name.startswith("_")}
    jsonable_dict.update({"name": input_type.__name__})
    return jsonable_dict


def minimal_event(obj):
    """ Minimal event encoding: time, id, display_text

    Events need time, id, display_text. No other information from the event is necessary for the display.  This will
    minimally encode the data for JSON.
    """
    return {"time": obj.time, "id": obj.id, "display_text": obj.display_text}


def minimal_channel(obj):
    """ Minimal channel serialization: time, id, val, and display_text

    Minimally serializes channel values for use with the flask layer. This does away with any unnecessary data by
    serializing only the id, value, and optional display text
    """
    jsonable = {"time": obj.time, "id": obj.id, "val": obj.val_obj.val}
    if hasattr(obj, "display_text"):
        jsonable.update({"display_text": obj.display_text})
    return jsonable


def enum_json(obj):
    """ Jsonify the enums! """
    enum_dict = {"value": str(obj), "values": {}}
    for enum_val in type(obj):
        enum_dict["values"][str(enum_val)] = enum_val.value
    return enum_dict


class GDSJsonEncoder(flask.json.JSONEncoder):
    """
    Custom class used to handle GDS object to JSON
    """
    JSON_ENCODERS = {
        ABCMeta: jsonify_base_type,
        UUID: str,
        ChData: minimal_channel,
        EventData: minimal_event
    }

    def default(self, obj):
        """
        Override the default JSON encoder to pull out a dictionary for our handled types for encoding with the default
        encoder built into flask

        :param obj: obj to encode
        :return: JSON
        """
        if type(obj) in self.JSON_ENCODERS:
            return self.JSON_ENCODERS[type(obj)](obj)
        elif isinstance(obj, Enum):
            return enum_json(obj)
        elif hasattr(obj, "to_jsonable"):
            return obj.to_jsonable()
        return flask.json.JSONEncoder.default(self, obj)
