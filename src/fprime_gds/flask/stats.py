""" stats.py:

Statistics package for the GDS to help diagnose performance issues and give greater visibility into the running GDS.
"""
from typing import Dict

import flask_restful

from fprime_gds.common.history.history import History
from fprime_gds.common.history.ram import RamHistory


class StatsBlob(flask_restful.Resource):
    """Produces a statistics blob for the upstream webpage"""

    def __init__(self, histories: Dict[str, History]):
        """Construct the stats object with knowledge of the histories"""
        self.histories = histories

    def get(self):
        """Get method for the statistics package"""
        try:
            counts = {
                key: history.sessions()
                for key, history in self.histories.items()
                if isinstance(history, RamHistory)
            }
            sizes = {key: history.size() for key, history in self.histories.items()}
            return {
                "Active Clients": {"total": max(counts.values()), **counts},
                "History Sizes": {"total": sum(sizes.values()), **sizes},
            }
        except Exception as exc:
            return {"errors": [str(exc)]}
