""" fprime_encryption.framing.chain: implementation of a chained framer/deframer """
from abc import ABC, abstractmethod
from functools import reduce
from typing import Any, Dict, List, Type
from fprime_gds.common.communication.framing import FramerDeframer
from fprime_gds.common.communication.ccsds.space_data_link import SpaceDataLinkFramerDeframer
from fprime_gds.common.communication.ccsds.space_packet import SpacePacketFramerDeframer
from fprime_gds.plugin.definitions import gds_plugin



class ChainedFramerDeframer(FramerDeframer, ABC):
    """ Framer/deframer that is a composite of chained framer/deframers

    This Framer/Deframer will wrap a set of framer/deframers where the result of the frame and deframe options will pass
    from one to the other subsequently. The order is specified via the framing path and deframing will use the reverse
    order from specified.
    """
    def __init__(self, **kwargs):
        """ Initialize the chained framer/deframer from a framing-ordered set of children """
        frame_order_framer_deframers = [
            composite(**self.get_argument_subset(composite, kwargs))
            for composite in self.get_composites()
        ]
        self.framers = frame_order_framer_deframers[::1]
        self.deframers = frame_order_framer_deframers[::-1]

    @classmethod
    @abstractmethod
    def get_composites(cls) -> List[Type[FramerDeframer]]:
        """ Return a list of composites 
        Innermost FramerDeframer should be first in the list. """
        raise NotImplementedError(f"Subclasses of {cls.__name__} must implement get_composites")

    @staticmethod
    def get_argument_subset(composite: Type[FramerDeframer], argument_dictionary: Dict[str, Any]) -> Dict[str, Any]:
        """ Get an argument subset that is needed by composite

        For the composite, find the set of arguments that is needed by this composite and pull those out of the complete
        argument dictionary.

        Args:
            composite: class of a subtype of FramerDeframer
            argument_dictionary: dictionary of all input arguments
        """
        if not hasattr(composite, "get_arguments"):
            return {}
        needed_arguments = composite.get_arguments()
        needed_argument_destinations = [
            description["destination"] if "destination" in description else
                [dash_dash for dash_dash in flag if dash_dash.startswith("--")][0].lstrip("-").replace("-", "_")
            for flag, description in needed_arguments.items()
        ]
        return {name: argument_dictionary[name] for name in needed_argument_destinations}

    @classmethod
    def get_arguments(cls):
        """ Arguments to request from the CLI """
        all_arguments = {}
        for composite in cls.get_composites():
            all_arguments.update(composite.get_arguments() if hasattr(composite, "get_arguments") else {})
        return all_arguments

    @classmethod
    def check_arguments(cls, **kwargs):
        """ Check arguments from the CLI """
        for composite in cls.get_composites():
            subset_arguments = cls.get_argument_subset(composite, kwargs)
            if hasattr(composite, "check_arguments"):
                composite.check_arguments(**subset_arguments)

    def deframe(self, data, no_copy=False):
        """ Deframe via a chain of children deframers """
        packet = data[:] if not no_copy else data
        remaining = None
        discarded = b""

        for deframer in self.deframers:
            new_packet, new_remaining, new_discarded = deframer.deframe(packet, True)
            discarded += new_discarded
            remaining = new_remaining if remaining is None else remaining
            packet = new_packet
        return packet, remaining, discarded

    def frame(self, data):
        """ Frame via a chain of children framers """
        return reduce(lambda framed_data, framer: framer.frame(framed_data), self.framers, data)


@gds_plugin(FramerDeframer)
class SpacePacketSpaceDataLinkFramerDeframer(ChainedFramerDeframer):
    """ Space Data Link Protocol framing and deframing that has a data unit of Space Packets as the central """

    @classmethod
    def get_composites(cls) -> List[Type[FramerDeframer]]:
        """ Return the composite list of this chain 
        Innermost FramerDeframer should be first in the list. """
        return [
            SpacePacketFramerDeframer,
            SpaceDataLinkFramerDeframer
        ]

    @classmethod
    def get_name(cls):
        """ Name of this implementation provided to CLI """
        return "space-packet-space-data-link"
