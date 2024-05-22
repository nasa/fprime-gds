####
#
####
import re
import sys
from io import StringIO
from pathlib import Path

import flask_restful
import flask_restful.reqparse

from fprime_gds.common.tools.seqgen import SeqGenException, generateSequence


class StdioTheif(object):
    """
    This class consumes all standard out and error production produced with-in a context block (with :) capturing it.
    """

    def __init__(self):
        """Setup our capture devices"""
        self.io = StringIO()
        self.output = ""

    def write(self, *args, **kwargs):
        """Write tee for all possible inputs"""
        stripped_msg = " ".join(args)
        self.io.write(stripped_msg, **kwargs)

    def __enter__(self):
        """Entry overwrite"""
        sys.stdout = self
        sys.stderr = self
        return None

    def __exit__(self, *_):
        """No worries here"""
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        self.io.seek(0)
        self.output = self.io.read()


class SequenceCompiler(flask_restful.Resource):
    def __init__(self, dictionary, tempdir, uplinker, destination):
        self.dictionary = dictionary
        self.tempdir = Path(tempdir)
        self.uplinker = uplinker
        self.destination = destination

        self.parser = flask_restful.reqparse.RequestParser()
        self.parser.add_argument(
            "key", required=True, help="Protection key. Must be: 0xfeedcafe."
        )
        self.parser.add_argument(
            "name", required=True, help="Name of sequence file to create"
        )
        self.parser.add_argument(
            "text", required=True, help="Text of sequence file to create"
        )
        self.parser.add_argument(
            "uplink", required=True, help="Text of sequence file to create"
        )

    def put(self):
        args = self.parser.parse_args()
        key = args.get("key", None)
        name = args.get("name", "")
        text = args.get("text", "")
        uplink = args.get("uplink", "false") == "true"
        if key is None or int(key, 0) != 0xFEEDCAFE:
            flask_restful.abort(
                403,
                message=f"{key} is invalid command key. Supply 0xfeedcafe to run command.",
            )
        elif not re.match(".*\\.seq", name) or Path(name).name != name:
            flask_restful.abort(
                403,
                message={"error": "Supply filename with .seq suffix", "type": "error"},
            )
        temp_seq_path = self.tempdir / Path(name).name
        temp_bin_path = temp_seq_path.with_suffix(".bin")
        messages = ""
        try:
            with open(temp_seq_path, "w") as file_handle:
                file_handle.write(text)
            thief = StdioTheif()
            with thief:
                generateSequence(
                    temp_seq_path, temp_bin_path, self.dictionary, 0xFFFF, cont=True
                )
            messages += thief.output
            if uplink:
                destination = Path(self.destination) / temp_bin_path.name
                self.uplinker.enqueue(str(temp_bin_path), str(destination))
                messages += f"Uplinking to {destination}. Please confirm uplink EVRs before running.\n"
        except OSError as ose:
            flask_restful.abort(403, message={"error": str(ose), "type": "error"})
        except SeqGenException as exc:
            flask_restful.abort(403, message={"error": str(exc), "type": "validation"})
        if temp_seq_path.exists():
            temp_seq_path.unlink()
        return {"message": messages}
