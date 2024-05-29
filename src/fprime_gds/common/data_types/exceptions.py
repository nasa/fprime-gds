"""
Created on Jan 9, 2015
@author: reder
"""

# Exception classes for all controllers modules


class FprimeGdsException(Exception):
    """
    Base Exception for exceptions that need to be handled at the system-level
    by the GDS
    """

    pass


class GdsDictionaryParsingException(FprimeGdsException):
    pass


# Note: Gse is the historical name for what is now called the GDS
class GseControllerException(FprimeGdsException):
    def __init__(self, val):
        self.except_msg = val
        super().__init__(val)

    def getMsg(self):
        return self.except_msg


class GseControllerUndefinedDirectoryException(GseControllerException):
    def __init__(self, val):
        super().__init__(f"Path does not exist: {str(val)}!")


class GseControllerUndefinedFileException(GseControllerException):
    def __init__(self, val):
        super().__init__(f"Path does not exist: {str(val)}!")


class GseControllerParsingException(GseControllerException):
    def __init__(self, val):
        super().__init__(f"Parsing error: {str(val)}")
