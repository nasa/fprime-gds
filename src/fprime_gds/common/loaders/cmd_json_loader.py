"""
cmd_json_loader.py:

Loads flight dictionary (JSON) and returns id and mnemonic based Python dictionaries of commands

@author thomas-bc
"""

from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime_gds.common.loaders.json_loader import JsonLoader


class CmdJsonLoader(JsonLoader):
    """Class to load xml based command dictionaries"""

    NAME_TAG = "name"
    OPCODE_TAG = "opcode"
    DESC_TAG = "annotation"
    PARAMETERS_TAG = "formalParams"

    def construct_dicts(self, _):
        """
         Constructs and returns python dictionaries keyed on id and name

        Args:
            _: Unused argument (inherited)
         Returns:
            A tuple with two command dictionaries (python type dict):
            (id_dict, name_dict). The keys are the events' id and name fields
            respectively and the values are CmdTemplate objects
        """
        id_dict = {}
        name_dict = {}

        for cmd_dict in self.json_dict["commands"]:
            cmd_temp = self.construct_template_from_dict(cmd_dict)

            id_dict[cmd_temp.get_id()] = cmd_temp
            name_dict[cmd_temp.get_full_name()] = cmd_temp

        return (
            id_dict,
            name_dict,
            self.get_versions(),
        )

    def construct_template_from_dict(self, cmd_dict: dict) -> CmdTemplate:
        cmd_name = cmd_dict.get(self.NAME_TAG)
        cmd_comp = cmd_name.split(".")[0]
        cmd_mnemonic = cmd_name.split(".")[1]
        cmd_opcode = cmd_dict.get(self.OPCODE_TAG)
        cmd_desc = cmd_dict.get(self.DESC_TAG)
        # Parse Arguments
        cmd_args = []
        for param in cmd_dict.get(self.PARAMETERS_TAG, []):
            cmd_args.append(
                (
                    param.get("name"),
                    param.get("annotation"),
                    self.parse_type(param.get("type")),
                )
            )

        return CmdTemplate(cmd_opcode, cmd_mnemonic, cmd_comp, cmd_args, cmd_desc)
