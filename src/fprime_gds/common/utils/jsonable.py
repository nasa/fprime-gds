"""
jsonable.py:

Folder with helper methods that allow for seamless conversion of F prime types to JSON types. This allows us to produce
data in JSON format with ease, assuming that the correct encoder is registered.

Note: JSON types must use only the following data types

 1. booleans
 2. numbers
 3. strings
 4. lists
 5. anonymous objects (dictionaries)

@author mstarch
"""
from inspect import getmembers, isroutine
from typing import Type
from fprime.common.models.serialize.type_base import BaseType
from fprime.common.models.serialize.enum_type import EnumType


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
    members = getmembers(input_type, lambda value: not isroutine(value) and not isinstance(value, property))
    jsonable_dict = {name: value for name, value in members if not name.startswith("_")}
    jsonable_dict.update({"name": input_type.__name__})
    return jsonable_dict


def fprime_to_jsonable(obj):
    """
    Takes an F prime object and converts it to a jsonable type.

    :param obj: object to convert
    :return: object in jsonable format (can call json.dump(obj))
    """
    # Otherwise try and scrape all "get_" getters in a smart way
    anonymous = {}
    getters = [attr for attr in dir(obj) if attr.startswith("get_")]
    for getter in getters:
        # Call the get_ functions, and call all non-static methods
        try:
            func = getattr(obj, getter)
            item = func()
            # If there is a property named "args" it needs to be handled specifically unless an incoming command
            if (
                getter == "get_args"
                and not "fprime_gds.common.data_types.cmd_data.CmdData"
                in str(type(obj))
            ):
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
