"""
dictionaries.py:

Helps the standard pipeline wrangle dictionaries by encapsulating the functionality of dictionary loading into a single
class called "Dictionaries".

@author mstarch
"""

from pathlib import Path


# XML Loaders
import fprime_gds.common.loaders.ch_xml_loader
import fprime_gds.common.loaders.cmd_xml_loader
import fprime_gds.common.loaders.event_xml_loader
import fprime_gds.common.loaders.pkt_json_loader
import fprime_gds.common.loaders.pkt_xml_loader

# JSON Loaders
from fprime_gds.common.loaders import ch_json_loader
from fprime_gds.common.loaders import cmd_json_loader
from fprime_gds.common.loaders import event_json_loader
from fprime_gds.common.loaders import type_json_loader
from fprime_gds.common.loaders import constant_json_loader


class Dictionaries:
    """
    Dictionaries class to encapsulate the many different dictionaries used in the system. This includes the following
    dictionary types:

    1. Command IDs to Commands
    2. Command names to Commands
    3. Channel IDs to Channels
    4. Channel names to Channels
    5. Event IDs to Events
    6. Event names to Events
    7. Packet IDs to Packets
    """

    def __init__(self):
        """Constructor of the dictionaries object"""
        self._command_id_dict = None
        self._event_id_dict = None
        self._channel_id_dict = None
        self._command_name_dict = None
        self._event_name_dict = None
        self._channel_name_dict = None
        self._packet_dict = None
        self._typedefs_name_dict = None
        self._constant_name_dict = None
        self._versions = None
        self._metadata = None
        self._dictionary_path = None
        self._packet_spec_path = None
        self._packet_set_name = None

    def load_dictionaries(self, dictionary, packet_spec, packet_set_name):
        """
        Loads the dictionaries based on the dictionary path supplied. Optional packet_spec is allowed to specify the
        definitions of packets.

        :param dictionary: dictionary path used for loading dictionaries
        :param packet_spec: specification for packets, or None, for packetized telemetry
        :param packet_set_name: name of packet set in case multiple are available
        """
        # Update the "from" values
        self._dictionary_path = dictionary
        self._packet_spec_path = packet_spec
        self._packet_set_name = packet_set_name

        if Path(dictionary).is_file() and ".json" in Path(dictionary).suffixes:
            # Events
            json_event_loader = event_json_loader.EventJsonLoader(dictionary)
            self._event_name_dict = json_event_loader.get_name_dict(None)
            self._event_id_dict = json_event_loader.get_id_dict(None)
            # Commands
            json_command_loader = cmd_json_loader.CmdJsonLoader(dictionary)
            self._command_name_dict = json_command_loader.get_name_dict(None)
            self._command_id_dict = json_command_loader.get_id_dict(None)
            # Channels
            json_channel_loader = ch_json_loader.ChJsonLoader(dictionary)
            self._channel_name_dict = json_channel_loader.get_name_dict(None)
            self._channel_id_dict = json_channel_loader.get_id_dict(None)
            # Load all type definitions to retrieve config types not used elsewhere
            types_loader = type_json_loader.TypeJsonLoader(dictionary)
            self._typedefs_name_dict = types_loader.get_name_dict(None)
            # Load all constant definitions
            constant_loader = constant_json_loader.ConstantJsonLoader(dictionary)
            self._constant_name_dict = constant_loader.get_name_dict(None)
            # Metadata
            self._versions = json_event_loader.get_versions()
            self._metadata = json_event_loader.get_metadata().copy()
            self._metadata["dictionary_type"] = "json"
            # Each loaders should agree on metadata and versions
            assert (
                json_command_loader.get_metadata()
                == json_channel_loader.get_metadata()
                == json_event_loader.get_metadata()
            ), "Metadata mismatch while loading"
            assert (
                json_command_loader.get_versions()
                == json_channel_loader.get_versions()
                == json_event_loader.get_versions()
            ), "Version mismatch while loading"
        # XML dictionaries
        elif Path(dictionary).is_file():
            # Events
            event_loader = fprime_gds.common.loaders.event_xml_loader.EventXmlLoader()
            self._event_id_dict = event_loader.get_id_dict(dictionary)
            self._event_name_dict = event_loader.get_name_dict(dictionary)
            self._versions = event_loader.get_versions()
            # Commands
            command_loader = fprime_gds.common.loaders.cmd_xml_loader.CmdXmlLoader()
            self._command_id_dict = command_loader.get_id_dict(dictionary)
            self._command_name_dict = command_loader.get_name_dict(dictionary)
            assert (
                self._versions == command_loader.get_versions()
            ), "Version mismatch while loading"
            # Channels
            channel_loader = fprime_gds.common.loaders.ch_xml_loader.ChXmlLoader()
            self._channel_id_dict = channel_loader.get_id_dict(dictionary)
            self._channel_name_dict = channel_loader.get_name_dict(dictionary)
            assert (
                self._versions == channel_loader.get_versions()
            ), "Version mismatch while loading"
            # versions are camelCase to match the metadata field of the JSON dictionaries
            self._metadata = {
                "frameworkVersion": self._versions[0],
                "projectVersion": self._versions[1],
                "dictionary_type": "xml",
            }
        else:
            msg = f"[ERROR] Dictionary '{dictionary}' does not exist."
            raise Exception(msg)
        # Check for packet specification
        if packet_spec is not None:
            packet_loader = fprime_gds.common.loaders.pkt_xml_loader.PktXmlLoader()
            self._packet_dict = packet_loader.get_id_dict(
                packet_spec, self._channel_name_dict
            )
        # Otherwise use JSON dictionary to attempt automatic packet loading
        elif self._metadata["dictionary_type"] == "json":
            packet_loader = fprime_gds.common.loaders.pkt_json_loader.PktJsonLoader(dictionary)
            if packet_set_name is None:
                names = packet_loader.get_packet_set_names(None)
                if len(names) == 0:
                    self._packet_dict = None
                    return
                elif len(names) > 1:
                    raise Exception("[ERROR] Multiple packet sets, must set --packet-set-name")
                packet_set_name = names[0]
            self._packet_dict = packet_loader.get_id_dict(
                None, packet_set_name, self._channel_name_dict
            )
        else:
            self._packet_dict = None

    @property
    def command_id(self):
        """Command dictionary by ID"""
        return self._command_id_dict

    @property
    def event_id(self):
        """Event dictionary by ID"""
        return self._event_id_dict

    @property
    def channel_id(self):
        """Channel dictionary by ID"""
        return self._channel_id_dict

    @property
    def command_name(self):
        """Command dictionary by name"""
        return self._command_name_dict

    @property
    def event_name(self):
        """Event dictionary by name"""
        return self._event_name_dict

    @property
    def channel_name(self):
        """Channel dictionary by name"""
        return self._channel_name_dict

    @property
    def typedefs_name(self):
        """Type definitions dictionary by name
        Returns:
            dict[str, DictionaryType]
        """
        return self._typedefs_name_dict

    @property
    def constant_name(self):
        """Constants dictionary by name. Constants do not carry type information in FPP
        and are simply name to int mappings in Python.
        Returns:
            dict[str, int]
        """
        return self._constant_name_dict

    @property
    def project_version(self):
        """Project version in dictionary"""
        return self._versions[1]

    @property
    def framework_version(self):
        """Framework version in dictionary"""
        return self._versions[0]

    @property
    def metadata(self):
        """Dictionary metadata.

        Note: framework_version and project_version are also available as separate properties
        for legacy reasons. New code should use the metadata property."""
        return self._metadata

    @property
    def dictionary_path(self):
        """Dictionary Path"""
        return self._dictionary_path

    @property
    def packet_spec_path(self):
        """Dictionary Path"""
        return self._packet_spec_path

    @property
    def packet_set_name(self):
        """Dictionary Path"""
        return self._packet_set_name

    @property
    def packet(self):
        """Packet dictionary"""
        return self._packet_dict
