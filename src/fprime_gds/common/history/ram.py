"""
ram.py:

A simple implementation of a history that maintains items in RAM. This is used for simplicity, but isn't exactly
robust nor persistent. Given that it is in the RAM, it is driven from the decoders object, which should run off the
middle-ware layer.

Note: this RAM history treats "start times" as session tokens to remember where it was last fetched from.

:author: lestarch
"""
import threading
import time

from fprime_gds.common.history.history import History


class RamHistory(History):
    """
    Chronological variant of history.  This is intended to be registered with the decoders in order
    to handle incoming objects, and store them for retrieval.
    """

    def __init__(self):
        """
        Constructor used to set-up in-memory store for history
        """
        self.lock = threading.RLock()
        self.objects = []
        self.retrieved_cursors = {}

    def data_callback(self, data, sender=None):
        """
        Data callback to store

        :param data: object to store
        """
        with self.lock:
            self.objects.append(data)

    def retrieve(self, start=None, limit=None):
        """
        Retrieve objects from this history. 'start' is the session token for retrieving new elements. If session is not
        specified, all elements are retrieved. If session is specified, then unseen elements are returned. If the
        session itself is new, it is recorded and set to the newest data.

        :param start: return all objects newer than given start session key
        :param limit: limit (count) of returned results
        :return: a list of objects
        """
        index = 0
        with self.lock:
            size = self.size()
            if start is not None:
                index = self.retrieved_cursors.get(start, size)
            end_slice = min(size, index + (limit if limit is not None else size))
            objs = self.objects[index:end_slice]
            self.retrieved_cursors[start] = end_slice
        return objs

    def retrieve_new(self):
        """
        Retrieves a chronological order of objects that haven't been accessed through retrieve or
        retrieve_new before.

        Returns:
            a list of objects in chronological order
        """
        index = 0
        with self.lock:
            if len(self.retrieved_cursors.values()) > 0:
                index = max(self.retrieved_cursors.values())
            return self.objects[index:]

    def clear(self, start=None):
        """
        Clears objects from RamHistory. It clears upto the earliest session. If session is supplied, the session id will
        be deleted as well.

        Args:
            start: a position in the history's order (int).
        """
        with self.lock:
            try:
                if start is not None:
                    del self.retrieved_cursors[start]
            except KeyError:
                pass
            earliest = 0
            if len(self.retrieved_cursors.values()) > 0:
                earliest = min(self.retrieved_cursors.values())
            del self.objects[:earliest]
            for key in self.retrieved_cursors:
                self.retrieved_cursors[key] -= earliest

    def sessions(self):
        """
        Accessor for the number of stored sessions

        Returns:
            number of tracked sessions
        """
        return len(self.retrieved_cursors.values())

    def size(self):
        """
        Accessor for the number of objects in the history
        Returns:
            the number of objects (int)
        """
        with self.lock:
            return len(self.objects)


class SelfCleaningRamHistory(RamHistory):
    """A Ram history which clears itself after a time of inactivity"""

    def __init__(self):
        """Construct object"""
        super().__init__()
        self.last_request = {}
        self.clear_time = -1

    def set_clear_time(self, time):
        """Update the clear time"""
        self.clear_time = time

    def retrieve(self, start=None, limit=None):
        """
        Retrieve objects from this history. 'start' is the session token for retrieving new elements. If session is not
        specified, all elements are retrieved. If session is specified, then unseen elements are returned. If the
        session itself is new, it is recorded and set to the newest data. This refreshes the last polled time preventing
        self clearing for another time

        :param start: return all objects newer than given start session key
        :param limit: limit (count) of returned results
        :return: a list of objects
        """
        if start is not None:
            with self.lock:
                self.last_request[start] = time.time()
        return super().retrieve(start, limit)

    def clear(self, start=None):
        """
        Clears objects from RamHistory. It clears upto the earliest session. If session is supplied, the session id will
        be deleted as well. This will also check all sessions for expiration and clear any sessions that have not been
        updated in self.clear_time seconds, unless that value is negative.

        Args:
            start: a position in the history's order (int).
        """
        current = time.time()
        with self.lock:
            deletes = [
                key
                for key, last in self.last_request.items()
                if self.clear_time > 0 and (last + self.clear_time) < current
            ]
            for delete in deletes:
                for container in [self.retrieved_cursors, self.last_request]:
                    try:
                        del container[delete]
                    except KeyError:
                        pass
        return super().clear(start)
