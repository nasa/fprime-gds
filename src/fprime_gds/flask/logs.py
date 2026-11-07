####
# Handles GDS logs in a lazy-loading way
####
import os

import flask_restful
import flask_restful.reqparse


class LogList(flask_restful.Resource):
    """A list of log files as produced by the GDS."""

    def __init__(self, logdir):
        """
        Constructor used to setup the log directory.

        :param logdir: log directory to search for logs
        """
        self.logdir = logdir

    def get(self):
        """Returns a list of log files that are available."""
        listing = os.listdir(self.logdir)
        return {"logs": [name for name in listing if name.endswith(".log")]}


class LogFile(flask_restful.Resource):
    """
    Command dictionary endpoint. Will return dictionary when hit with a GET.
    """

    def __init__(self, logdir):
        """
        Constructor used to setup the log directory.

        :param logdir: log directory to search for logs
        """
        self.logdir = logdir

    def get(self, name):
        """
        Returns the logdir.
        """
        logs = {}
        # Sanitization of path characters across POSIX and Windows separators
        for sep in (os.path.sep, os.path.altsep):
            if sep:
                name = name.replace(sep, "_")
        # Resolve real paths and verify commonpath containment within logdir
        logdir_real = os.path.realpath(self.logdir)
        full_path = os.path.realpath(os.path.join(logdir_real, name))
        try:
            if os.path.commonpath([logdir_real, full_path]) != logdir_real:
                return ""
        except ValueError:
            return ""
        if not os.path.isfile(full_path):
            return ""
        offset = 0
        with open(full_path) as file_handle:
            file_handle.seek(offset)
            logs[name] = file_handle.read()
        return logs
