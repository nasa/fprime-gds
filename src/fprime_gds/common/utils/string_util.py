"""
string_util.py
Utility functions to process strings to be used in FPrime GDS
@Created March 18, 2021
@janamian
"""

import re


def format_string(format_str, given_values):
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
    template. It will remove all types so they could be duck-typed by python 
    interpreter except for hex type X or x. lengths will also be removed since
    they are not meaningful to Python interpreter
    See: https://docs.python.org/3/library/stdtypes.html#printf-style-string-formatting
    Regex Source: https://www.regexlib.com/REDetails.aspx?regexp_id=3363
    """
    def convert(match_obj):
        if match_obj.group() is not None:
            flags, width, percision, lenght, conversion_type = match_obj.groups()
            fmr_str = ''
            if flags:
                fmr_str += f'{flags}'
            if width:
                fmr_str += f'{width}'
            if percision:
                fmr_str += f'{percision}'

            if conversion_type:
                if any([
                    str(conversion_type).lower() == 'f',
                    str(conversion_type).lower() == 'd',
                    str(conversion_type).lower() == 'x',
                    str(conversion_type).lower() == 'o',
                    str(conversion_type).lower() == 'e',
                    ]):
                    fmr_str += f'{conversion_type}'

            if fmr_str == '':
                template = '{}'
            else:
                template = '{:' + fmr_str + '}'
            return template
        return match_obj

    # Allowing single, list and tuple inputs
    if not isinstance(given_values, (list, tuple)):
        values = (given_values, )
    elif isinstance(given_values, list):
        values = tuple(given_values)
    else:
        values = given_values

    pattern = '(?<!%)(?:%%)*%([\-\+0\ \#])?(\d+|\*)?(\.\*|\.\d+)?([hLIw]|l{1,2}|I32|I64)?([cCdiouxXeEfgGaAnpsSZ])'

    match = re.compile(pattern) 
    formated_str = re.sub(match, convert, format_str)
    result = formated_str.format(*values)
    result = result.replace('%%', '%')
    return result
