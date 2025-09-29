"""
string_util.py
Utility functions to process strings to be used in FPrime GDS
@Created March 18, 2021
@`janamian`

Note: This function has an identical copy in fprime-gds
"""

import logging
import re
from typing import Any, Union

LOGGER = logging.getLogger("string_util_logger")


def format_string_template(template: str, value: Union[tuple, list, Any]) -> str:
    """
    Function to format a string template with values. This function is a simple wrapper around the
    format function. It accepts a tuple, list, or single value and passes it to the format function

    Args:
        template (str): String template to be formatted
        value (Union[tuple, list, Any]): Value(s) to be inserted into the template

    Returns:
        str: Formatted string
    """
    if not isinstance(value, (tuple, list)):
        value = (value,)
    try:
        return template.format(*value)
    except (IndexError, ValueError) as e:
        LOGGER.error(
            f"Error formatting string template: {template} with value: {str(value)}"
        )
        raise e


def preprocess_fpp_format_str(format_str: str) -> str:
    """Preprocess a FPP-style format string and convert it to Python format string
    FPP format strings are documented https://nasa.github.io/fpp/fpp-spec.html#Format-Strings
    For example "{x}" -> "{:x}" or "{.2f}" -> "{:.2f}"

    Args:
        format_str (str): FPP-style format string

    Returns:
        str: Python-style format string
    """
    pattern = r"{(\d*\.?\d*[cdxoefgCDXOEFG])}"
    return re.sub(pattern, r"{:\1}", format_str)


def preprocess_c_style_format_str(format_str: str) -> str:
    r"""
    Function to convert C-string style to python format
    without using python interpolation
    Considered the following format for C-string:
    %[flags][width][.precision][length]type

    0- %:                (?<!%)(?:%%)*%
    1- flags:            ([\-\+0\ \#])?
    2- width:            (\d+|\*)?
    3- .precision:       (\.\*|\.\d+)?
    4- length:          `([hLIw]|l{1,2}|I32|I64)?`
    5- conversion_type: `([cCdiouxXeEfgGaAnpsSZ])`

    Note:
    This function will keep the flags, width, and .precision of C-string
    template.

    It will keep f, x, o, and e flags and remove all other types.
    Other types will be duck-typed by python interpreter.

    lengths will also be removed since they are not meaningful to Python interpreter.
    `See: https://docs.python.org/3/library/stdtypes.html#printf-style-string-formatting`
    `Regex Source: https://www.regexlib.com/REDetails.aspx?regexp_id=3363`

    For example "%x" -> "{:x}" or "%.2f" -> "{:.2f}"

    Args:
        format_str (str): C-style format string

    Returns:
        str: Python-style format string
    """

    def convert(match_obj: re.Match):
        if match_obj.group() is None:
            return match_obj
        flags, width, precision, _, conversion_type = match_obj.groups()
        format_template = ""
        if flags:
            format_template += f"{flags}"
        if width:
            format_template += f"{width}"
        if precision:
            format_template += f"{precision}"

        if conversion_type and str(conversion_type).lower() in {"f", "x", "o", "e"}:
            format_template += f"{conversion_type}"

        return "{}" if format_template == "" else "{:" + format_template + "}"

    pattern = r"(?<!%)(?:%%)*%([\-\+0\ \#])?(\d+|\*)?(\.\*|\.\d+)?([hLIw]|l{1,2}|I32|I64)?([cCdiouxXeEfgGaAnpsSZ])"  # NOSONAR

    match = re.compile(pattern)

    return re.sub(match, convert, format_str).replace("%%", "%")
