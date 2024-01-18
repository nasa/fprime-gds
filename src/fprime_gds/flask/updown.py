"""
flask/updown.py:

A simple service that handles file uploads and downloads. This allowed the REST api to show the status of file uplinks
and downlinks. In addition, an uplink destination directory is exposed for the UI to set where new uploads should be
uplinked to.

@author mstarch
"""
import os

import flask
import flask_restful
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename
from pathlib import Path


class Destination(flask_restful.Resource):
    """
    A data model for the current location of the destination of uplinked files.
    """

    def __init__(self, uplinker):
        """
        Constructor: setup the parser for incoming destination arguments
        """
        self.parser = flask_restful.reqparse.RequestParser()
        self.parser.add_argument(
            "destination", required=True, help="Destination to place uploaded files"
        )
        self.uplinker = uplinker

    def get(self):
        """
        Gets the current destination

        :return: current destination
        """
        return {"destination": self.uplinker.destination_dir}

    def put(self):
        """
        Updates the current destination directory
        """
        args = self.parser.parse_args()
        destination = args.get("destination", None)
        self.uplinker.destination_dir = destination
        return {"message": "success"}


class FileUploads(flask_restful.Resource):
    """
    A data model for the current uplinking file set.
    """

    def __init__(self, uplinker, dest_dir):
        """
        Constructor: setup the uplinker and argument parsing
        """
        self.uplinker = uplinker
        self.dest_dir = dest_dir
        self.parser = flask_restful.reqparse.RequestParser()
        self.parser.add_argument(
            "action", required=True, help="Action to take against files"
        )
        self.parser.add_argument(
            "source", required=False, default=None, help="File on which to act file"
        )

    def get(self):
        """
        Gets the current set of files

        :return: current uplinking files
        """
        return {
            "files": self.uplinker.current_files(),
            "running": self.uplinker.is_running(),
        }

    def put(self):
        """
        Handles an update to an existing source file.  Source and action are expected parameters to be supplied. If
        source is None, then "pause-all" or "unpause-all" should be supplied to globally pause the uplinker.
        """
        args = self.parser.parse_args()
        action = args.get("action", None)
        source = args.get("source", None)
        if action == "Remove" or action == "Cancel" and source is not None:
            self.uplinker.cancel_remove(source)
        elif action == "pause-all":
            self.uplinker.pause()
        elif action == "unpause-all":
            self.uplinker.unpause()

    def post(self):
        """
        Adds file(s) to be uplinked by enqueuing each into the uplinker.
        """
        successful = []
        failed = []
        for key, file in flask.request.files.items():
            try:
                filename = self.save(file)
                flask.current_app.logger.info(f"Received file. Saved to: {filename}")
                self.uplinker.enqueue(os.path.join(self.dest_dir, filename))
                successful.append(key)
            except Exception as exc:
                flask.current_app.logger.warning(
                    f"Failed to save file {key} with error: {exc}"
                )
                failed.append(key)
        return {"successful": successful, "failed": failed}

    def save(self, file_storage: FileStorage):
        """
        This saves a `werkzeug.FileStorage` into this upload set.

        :param file_storage: The uploaded file to save.
        """
        if not isinstance(file_storage, FileStorage):
            raise TypeError("file_storage must be a werkzeug.FileStorage")

        filename = Path(secure_filename(file_storage.filename)).name
        dest_dir = Path(self.dest_dir)

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            raise PermissionError(
                f"{dest_dir} is not writable. Fix permissions or change storage directory with --file-storage-directory."
            )

        # resolve conflict may not be needed
        if (dest_dir / filename).exists():
            filename = self.resolve_conflict(dest_dir, filename)

        target = dest_dir / filename
        file_storage.save(str(target))

        return filename

    def resolve_conflict(self, target_folder: Path, filename: str):
        """
        If a file with the selected name already exists in the target folder,
        this method is called to resolve the conflict. It should return a new
        filename for the file.

        The default implementation splits the name and extension and adds a
        suffix to the name consisting of an underscore and a number, and tries
        that until it finds one that doesn't exist.

        :param target_folder: The absolute path to the target.
        :param filename: The file's original filename.
        """
        path = Path(filename)
        name, ext = path.stem, path.suffix
        count = 0
        while True:
            count = count + 1
            newname = f"{name}_{count}{ext}"
            if not (Path(target_folder) / newname).exists():
                return newname


class FileDownload(flask_restful.Resource):
    """ """

    def __init__(self, downlinker):
        """
        Constructor: setup the downlinker
        """
        self.downlinker = downlinker

    def get(self, source=None):
        """
        Gets the current downlinking files

        :return: current downlinking files
        """
        # Serve the  source if asked for, otherwise list all files
        if source is not None:
            return flask.send_from_directory(
                self.downlinker.directory, os.path.basename(source), as_attachment=True
            )
        return {"files": self.downlinker.current_files()}
