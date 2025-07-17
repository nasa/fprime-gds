"""
pkt_json_loader.py:

Loads flight dictionary (JSON) and returns Python dictionaries of telemetry packets

@author jawest
"""

from fprime_gds.common.templates.pkt_template import PktTemplate
from fprime_gds.common.loaders.json_loader import JsonLoader
from fprime_gds.common.data_types.exceptions import GdsDictionaryParsingException


class PktJsonLoader(JsonLoader):
    """Class to load python based telemetry packet dictionaries"""

    PACKETS_FIELD = "telemetryPacketSets"

    SET_NAME = "name"
    MEMBERS = "members"

    def get_packet_set_names(self, path):
        """ Get the list of packet sets """
        return [packet_set[self.SET_NAME] for packet_set in self.json_dict[self.PACKETS_FIELD]]

    def get_id_dict(self, path, packet_set_name: str, ch_name_dict: dict):
        if path in self.saved_dicts and packet_set_name in self.saved_dicts[path]:
            (id_dict, name_dict) = self.saved_dicts[path][packet_set_name]
        else:
            (id_dict, name_dict, self.versions) = self.construct_dicts(packet_set_name, ch_name_dict)
            if path not in self.saved_dicts:
                self.saved_dicts[path] = dict()
            self.saved_dicts[path].update({packet_set_name: (id_dict, name_dict)})

        return id_dict
    
    def get_name_dict(self, path, packet_set_name: str, ch_name_dict: dict):
        if path in self.saved_dicts and packet_set_name in self.saved_dicts[path]:
            (id_dict, name_dict) = self.saved_dicts[path][packet_set_name]
        else:
            (id_dict, name_dict, self.versions) = self.construct_dicts(packet_set_name, ch_name_dict)
            if path not in self.saved_dicts:
                self.saved_dicts[path] = dict()
            self.saved_dicts[path].update({packet_set_name: (id_dict, name_dict)})

        return name_dict


    def construct_dicts(self, packet_set_name: str, ch_name_dict: dict):
        """
        Constructs and returns python dictionaries keyed on id and name

        This function should not be called directly, instead, use
        get_id_dict(path) and get_name_dict(path)

        Args:
            ch_name_dict (dict()): Channel dictionary with names as keys and
                                   ChTemplate objects as values.

        Returns:
            A tuple with two packet dictionaries (type==dict()):
            (id_dict, name_dict) and the dictionary version. The keys of the packet dictionaries should 
            be the packets' id and name fields respectively and the values should be PktTemplate objects.
        """
        id_dict = {}
        name_dict = {}

        if self.PACKETS_FIELD not in self.json_dict:
            raise GdsDictionaryParsingException(
                f"Ground Dictionary missing '{self.PACKETS_FIELD}' field: {str(self.json_file)}"
            )

        for packet_dict in self.json_dict[self.PACKETS_FIELD]:
            try:
                if packet_set_name == packet_dict[self.SET_NAME]:
                    for packet_group_dict in packet_dict.get(self.MEMBERS, []):
                        packet_temp = self.construct_template_from_dict(packet_group_dict, ch_name_dict)
                        id_dict[packet_temp.get_id()] = packet_temp
                        name_dict[packet_temp.get_name()] = packet_temp

                    return (
                        dict(sorted(id_dict.items())),
                        dict(sorted(name_dict.items())),
                        self.get_versions(),
                    )
                
            except KeyError as e:
                raise GdsDictionaryParsingException(
                    f"{str(e)} key missing from telemetry packet dictionary entry: {str(packet_dict)}"
                )
            
        raise GdsDictionaryParsingException(
            f"Ground Dictionary does not contain packet set '{packet_set_name}'"
        )

    def construct_template_from_dict(self, packet_group_dict: dict, ch_name_dict: dict):
        """        
        Args:
            packet_group_dict (dict()): Packet group dictionary with group id, name, and members
            ch_name_dict (dict()): Channel dictionary with names as keys and ChTemplate objects as values.
        Returns:
            A a PktTemplate object containing the packet group id, group name, and list of ChTemplate 
            objects that represent each member in the packet.
        """
        try:
            ch_list = []
            group_name = packet_group_dict["name"]
            group_id = packet_group_dict["id"]
            group_members = packet_group_dict["members"]

            for ch_name in group_members:
                ch_template = ch_name_dict[ch_name]
                ch_list.append(ch_template)
            
        except KeyError as e:
            raise GdsDictionaryParsingException(
                f"{str(e)} key missing from telemetry packet member or member is not a channel in the dictionary: {str(group_name)}"
            )
        
        return PktTemplate(
            group_id,
            group_name,
            ch_list
        )

