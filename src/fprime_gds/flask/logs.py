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
    """Returns the contents of a single log file.

    Supports incremental tailing via the ``?offset=<int>`` query argument so
    a client polling at a fixed cadence does not have to download the entire
    file on each request.

    Behaviour:

    * No ``offset`` argument: returns the full file (legacy behaviour).
      Response shape: ``{"<name>": "<full contents>"}``.
    * ``offset`` provided: returns the bytes from ``offset`` to current EOF
      and reports the new offset and file size so the client can chain
      subsequent reads.  If ``offset`` exceeds the current file size (e.g.
      because the log was rotated or truncated) the read restarts from 0
      and returns the full current contents.
      Response shape: ``{"<name>": "<delta>", "offset": <int>, "size": <int>}``.
    """

    def __init__(self, logdir):
        """
        Constructor used to setup the log directory.

        :param logdir: log directory to search for logs
        """
        self.logdir = logdir
        self.parser = flask_restful.reqparse.RequestParser()
        # ``offset`` is optional and only switches the response into the
        # incremental-tail shape; omitting it preserves legacy behaviour.
        self.parser.add_argument(
            "offset",
            type=int,
            required=False,
            location="args",
            help="Byte offset to start reading from; omit for full file.",
        )

    def _resolve_path(self, name):
        """Return the safe absolute path for ``name`` or ``None`` if invalid.

        Applies the same sanitisation rules the legacy implementation used
        (replace separators, then ``normpath``+prefix check) so the public
        surface of the endpoint is unchanged.
        """
        name = name.replace(os.path.sep, "_")
        full_path = os.path.normpath(os.path.join(self.logdir, name))
        if not full_path.startswith(self.logdir):
            return None
        if not os.path.isfile(full_path):
            return None
        return full_path

    def get(self, name):
        """Return either the full file contents or an incremental delta."""
        full_path = self._resolve_path(name)
        if full_path is None:
            return ""

        args = self.parser.parse_args()
        requested_offset = args.get("offset")

        if requested_offset is None:
            # Legacy behaviour: return the full file body keyed by name.
            with open(full_path) as file_handle:
                return {name: file_handle.read()}

        # Incremental tail: only return bytes the client has not seen yet.
        size = os.path.getsize(full_path)
        offset = max(0, int(requested_offset))
        # Rotation / truncation: the file is smaller than the client's last
        # offset, so start over from the beginning.
        if offset > size:
            offset = 0
        with open(full_path) as file_handle:
            file_handle.seek(offset)
            delta = file_handle.read()
        return {name: delta, "offset": size, "size": size}
