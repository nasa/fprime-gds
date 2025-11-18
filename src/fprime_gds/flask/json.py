####
# json.py:
#
# Encodes GDS objects as JSON.
####
from abc import ABCMeta
from enum import Enum
from inspect import getmembers, isroutine
from typing import Type
from uuid import UUID

import flask.json
from fprime_gds.common.models.serialize.time_type import TimeType
from fprime_gds.common.models.serialize.type_base import BaseType, ValueType

from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.data_types.cmd_data import CmdData
from fprime_gds.common.data_types.event_data import EventData
from fprime_gds.common.templates.data_template import DataTemplate


def jsonify_base_type(input_type: Type[BaseType]) -> dict:
    """Turn a base type into a JSONable dictionary

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
    members = getmembers(
        input_type,
        lambda value: not isroutine(value) and not isinstance(value, property),
    )
    jsonable_dict = {name: value for name, value in members if not name.startswith("_")}
    jsonable_dict.update({"name": input_type.__name__})
    return jsonable_dict


def getter_based_json(obj):
    """Converts objects to JSON via get_ methods

    Template functions define a series of get_* methods whose return values need to be serialized. This function
    handles that data.

    Args:
        obj: object to serialize into JSON

    Returns:
        JSON compatible python anonymous type (dictionary)
    """
    anonymous = {}
    getters = [attr for attr in dir(obj) if attr.startswith("get_")]
    for getter in getters:
        # Call the get_ functions, and call all non-static methods
        try:
            func = getattr(obj, getter)
            item = func()
            # If there is a property named "args" it needs to be handled specifically unless an incoming command
            if getter == "get_args":
                args = []
                for arg_spec in item:
                    arg_dict = {
                        "name": arg_spec[0],
                        "description": arg_spec[1] if arg_spec[1] is not None else "",
                        "type": arg_spec[2],
                    }
                    args.append(arg_dict)
                # Fill in our special handling
                item = args
            anonymous[getter.replace("get_", "")] = item
        except TypeError:
            continue
    return anonymous


def minimal_event(obj):
    """Minimal event encoding: time, id, display_text

    Events need time, id, display_text. No other information from the event is necessary for the display.  This will
    minimally encode the data for JSON.

    Args:
        obj: object to serialize into JSON

    Returns:
        JSON compatible python anonymous type (dictionary)
    """
    return {"time": obj.time, "id": obj.id, "display_text": obj.display_text}


def minimal_channel(obj):
    """Minimal channel serialization: time, id, val, and display_text

    Minimally serializes channel values for use with the flask layer. This does away with any unnecessary data by
    serializing only the id, value, and optional display text

    Args:
        obj: object to serialize into JSON

    Returns:
        JSON compatible python anonymous type (dictionary)
    """
    return {
        "time": obj.time,
        "id": obj.id,
        "val": obj.val_obj.val,
        "display_text": obj.display_text,
    }


def minimal_command(obj):
    """Minimal command serialization: time, id, and args values

    Minimally serializes the command values for use with the flask layer. This prevents excess data by keeping the data
    to the minimum instance data for commands including: time, opcode (id), and the value for args.

    Args:
        obj: object to serialize into JSON

    Returns:
        JSON compatible python anonymous type (dictionary)
    """
    return {"time": obj.time, "id": obj.id, "args": obj.get_arg_vals()}


def time_type(obj):
    """Time type serialization

    Serializes the time type into a JSON compatible object.

    Args:
        obj: object to serialize into JSON

    Returns:
        JSON compatible python anonymous type (dictionary)
    """
    assert isinstance(obj, TimeType), "Incorrect type for serialization method"
    return {
        "base": obj.timeBase.numeric_value,
        "context": obj.timeContext,
        "seconds": obj.seconds,
        "microseconds": obj.useconds,
    }


def enum_json(obj):
    """Jsonify the python enums!"""
    enum_dict = {"value": str(obj), "values": {}}
    for enum_val in type(obj):
        enum_dict["values"][str(enum_val)] = enum_val.value
    return enum_dict


JSON_ENCODERS = {
    ABCMeta: jsonify_base_type,
    UUID: str,
    ChData: minimal_channel,
    EventData: minimal_event,
    CmdData: minimal_command,
    TimeType: time_type,
}


def default(obj):
    """
    Override the default JSON encoder to pull out a dictionary for our handled types for encoding with the default
    encoder built into flask. This function must convert the given object into a JSON compatable python object (e.g.
    using lists, dictionaries, strings, and primitive types).

    :param obj: obj to encode
    :return: JSON
    """
    if type(obj) in JSON_ENCODERS:
        return JSON_ENCODERS[type(obj)](obj)
    if isinstance(obj, DataTemplate):
        return getter_based_json(obj)
    if isinstance(obj, Enum):
        return enum_json(obj)
    if isinstance(obj, ValueType):
        return obj.val
    return flask.json.provider.DefaultJSONProvider.default(obj)
