"""
cmd_json_loader.py:

Loads flight dictionary (JSON) and returns id and mnemonic based Python dictionaries of commands

@author thomas-bc
"""

from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime_gds.common.loaders.json_loader import JsonLoader


class CmdJsonLoader(JsonLoader):
    """Class to load xml based command dictionaries"""

    MNEMONIC_TAG = "name"
    OPCODE_TAG = "opcode"
    DESC_TAG = "annotation"
    PARAMETERS_TAG = "formalParams"

    def __init__(self, dict_path: str):
        super().__init__(dict_path)


    def construct_dicts(self, path):
        """
        Constructs and returns python dictionaries keyed on id and name

       Args:
            path: Path to JSON dictionary file
        Returns:
            A tuple with two command dictionaries (python type dict):
            (id_dict, name_dict). The keys are the events' id and name fields
            respectively and the values are CmdTemplate objects
        """

        id_dict = {}
        name_dict = {}

        for cmd_dict in self.json_dict["commands"]:
            cmd_name = cmd_dict.get("name")
            
            cmd_comp = cmd_name.split(".")[0]
            cmd_mnemonic = cmd_name.split(".")[1]

            cmd_opcode = cmd_dict.get("opcode")

            cmd_desc = cmd_dict.get("annotation")

            # Parse Arguments
            cmd_args = []
            for arg in cmd_dict.get("formalParams", []):
                cmd_args.append((arg.get("name"), arg.get("annotation"), self.parse_type(arg.get("type"))))

            cmd_temp = CmdTemplate(cmd_opcode, cmd_mnemonic, cmd_comp, cmd_args, cmd_desc)

            id_dict[cmd_opcode] = cmd_temp
            name_dict[cmd_temp.get_full_name()] = cmd_temp

        return id_dict, name_dict, ("unknown", "unknown")
