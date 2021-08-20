"""
string_util.py
Utility functions to process strings to be used in FPrime GDS
@Created March 18, 2021
@`janamian`

Note: This function has an identical copy in fprime-gds
"""

import re
import logging

LOGGER = logging.getLogger('string_util_logger')


def format_string_template(format_str, given_values):
    """
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

    It will keep f, d, x, o, and e flags and remove all other types.
    Other types will be duck-typed by python 
    interpreter. 

    lengths will also be removed since they are not meaningful to Python interpreter.
    `See: https://docs.python.org/3/library/stdtypes.html#printf-style-string-formatting`

    `Regex Source: https://www.regexlib.com/REDetails.aspx?regexp_id=3363`
    """
    def convert(match_obj, ignore_int):
        if match_obj.group() is not None:
            flags, width, precision, length, conversion_type = match_obj.groups()
            format_template = ''
            if flags:
                format_template += f'{flags}'
            if width:
                format_template += f'{width}'
            if precision:
                format_template += f'{precision}'

            if conversion_type:
                if any([
                    str(conversion_type).lower() == 'f',
                    str(conversion_type).lower() == 'x',
                    str(conversion_type).lower() == 'o',
                    str(conversion_type).lower() == 'e',
                ]):
                    format_template += f'{conversion_type}'
                elif all([not ignore_int,
                          str(conversion_type).lower() == 'd']):
                    format_template += f'{conversion_type}'

            if format_template == '':
                template = '{}'
            else:
                template = '{:' + format_template + '}'
            return template
        return match_obj

    def convert_include_all(match_obj):
        return convert(match_obj, ignore_int=False)

    def convert_ignore_int(match_obj):
        return convert(match_obj, ignore_int=True)

    # Allowing single, list and tuple inputs
    if not isinstance(given_values, (list, tuple)):
        values = (given_values, )
    elif isinstance(given_values, list):
        values = tuple(given_values)
    else:
        values = given_values

    pattern = '(?<!%)(?:%%)*%([\-\+0\ \#])?(\d+|\*)?(\.\*|\.\d+)?([hLIw]|l{1,2}|I32|I64)?([cCdiouxXeEfgGaAnpsSZ])'

    match = re.compile(pattern)
    
    # First try to include all types
    try:
        formated_str = re.sub(match, convert_include_all, format_str)
        result = formated_str.format(*values)
        result = result.replace('%%', '%')
        return result
    except ValueError as e:
        msg = 'Value and format string do not match. Will ignore integer flags `d` in string template. '
        msg += f'values: {values}. '
        msg += f'format_str: {format_str}. '
        LOGGER.warning(msg)

    # Second try by not including %d.
    # This will resolve failing ENUMs with %d
    # but will fail on other types.
    try:
        formated_str = re.sub(match, convert_ignore_int, format_str)
        result = formated_str.format(*values)
        result = result.replace('%%', '%')
        return result
    except ValueError as e:
        msg = 'Value and format string do not match. '
        msg += f'values: {values}. '
        msg += f'format_str: {format_str}. '
        msg += f'Err Msg: {str(e)}\n'
        LOGGER.error(msg)
        raise ValueError
