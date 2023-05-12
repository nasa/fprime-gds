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
        # Sanitization of path characters
        name = name.replace(os.path.sep, "_")
        # normpath() + startswith() to ensure the file is strictly within logdir
        full_path = os.path.normpath(os.path.join(self.logdir, name))
        if not full_path.startswith(self.logdir):
            return ""
        if not os.path.exists(full_path):
            return ""
        offset = 0
        with open(full_path) as file_handle:
            file_handle.seek(offset)
            logs[name] = file_handle.read()
        return logs
