""" resource.py: flask_restful resource helpers

Helper functions used to manage resource endpoints for the fprime_gds. This functions to reduce code duplication,
establish standard patterns, and prevent replicated errors.

@author lestarch
"""
from flask_restful import Resource
from flask_restful.reqparse import RequestParser

from fprime_gds.flask.errors import build_error_object


class DictionaryResource(Resource):
    """
    Resource tasked with serving the supplied dictionary through flask. The dictionary will be returned as-is and thus
    should be flask compatible. Errors with the dictionary are a 500 server error and may not be recovered.
    """

    def __init__(self, dictionary, project_version, framework_version, metadata):
        """Constructor used to setup for dictionary

        Args:
            dictionary: dictionary to serve when GET is called
            project_version: project version for the dictionary
            framework_version: project version for the dictionary
            metadata (dict): additional metadata to serve with the dictionary
        """
        self.dictionary = dictionary
        self.project_version = project_version
        self.framework_version = framework_version
        self.metadata = metadata

    def get(self):
        """HTTP GET method handler for dictionary resource

        Returns:
            dictionary ready for conversion into JSON
        """
        return {
            "dictionary": self.dictionary,
            "project_version": self.project_version,
            "framework_version": self.framework_version,
            "metadata": self.metadata
        }


class HistoryResourceBase(Resource):
    """
    Base class for resources serving histories. Internalizes a history, serves the latest data from that history, and
    clears the history data such that replicated data is not sent. The GET method will loop through history object
    calling `process` to allow subclasses to post-process the object for sending. Errors in process will be aggregated
    but will not fail the GET transaction, however; errors outside of process will result in a 500 error.

    The history base object also sets up the request parser to handle the session argument needed to track the pointer
    into the history. This session is automatically deleted when the DELETE handler is invoked such that the GDS is
    kept cleaned-up.
    """

    def __init__(self, history):
        """Construct this history resource around a supplied history

        Args:
            history: history used as a base data store for this resource
        """
        self.parser = RequestParser()
        self.parser.add_argument(
            "session", required=True, help="Session key for fetching data.", location="args"
        )
        self.parser.add_argument(
            "limit", required=False, help="Limit to results returned (default 2000)", location="args"
        )

        self.history = history

    def process(self, item):
        """Base history object processing function (does nothing)"""
        return item

    def get(self):
        """HTTP GET handler returning new history objects"""
        errors = []
        returned_items = []
        args = self.parser.parse_args()

        # Set the clear time if possible
        if hasattr(self.history, "set_clear_time"):
            self.history.set_clear_time(60)

        # Get the new items from history ensuring it is clear in a fail-safe attempt to repeat recuring errors
        try:
            session = args.get("session")
            limit = args.get("limit") if args.get("limit") is not None else 2000
            new_items = self.history.retrieve(session, int(limit))
            validation = -1
            if hasattr(self.history, "get_seen_count"):
                validation = self.history.get_seen_count(session)
        finally:
            self.history.clear()

        # Process each item from history aggregating but not failing on processing errors
        for item in new_items:
            try:
                returned_items.append(self.process(item))
            except Exception as exc:
                errors.append(build_error_object(exc))
        return {"history": returned_items, "validation": validation, "errors": errors}
