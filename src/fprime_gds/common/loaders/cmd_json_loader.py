"""
cmd_json_loader.py:

Loads flight dictionary (JSON) and returns id and mnemonic based Python dictionaries of commands

@author thomas-bc
"""

from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime_gds.common.loaders.json_loader import JsonLoader
from fprime_gds.common.data_types.exceptions import GdsDictionaryParsingException


class CmdJsonLoader(JsonLoader):
    """Class to load json based command dictionaries"""

    COMMANDS_FIELD = "commands"

    NAME = "name"
    OPCODE = "opcode"
    DESC = "annotation"
    PARAMETERS = "formalParams"

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

        if self.COMMANDS_FIELD not in self.json_dict:
            raise GdsDictionaryParsingException(
                f"Ground Dictionary missing '{self.COMMANDS_FIELD}' field: {str(self.json_file)}"
            )

        for cmd_dict in self.json_dict[self.COMMANDS_FIELD]:
            cmd_temp = self.construct_template_from_dict(cmd_dict)

            id_dict[cmd_temp.get_id()] = cmd_temp
            name_dict[cmd_temp.get_full_name()] = cmd_temp

        return (
            dict(sorted(id_dict.items())),
            dict(sorted(name_dict.items())),
            self.get_versions(),
        )

    def construct_template_from_dict(self, cmd_dict: dict) -> CmdTemplate:
        try:
            qualified_component_name, cmd_mnemonic = cmd_dict[self.NAME].rsplit('.', 1)
            cmd_opcode = cmd_dict[self.OPCODE]
            cmd_desc = cmd_dict.get(self.DESC)
        except ValueError as e:
            raise GdsDictionaryParsingException(
                f"Command dictionary entry malformed, expected name of the form '<QUAL_COMP_NAME>.<CMD_NAME>' in : {str(cmd_dict)}"
            )
        except KeyError as e:
            raise GdsDictionaryParsingException(
                f"{str(e)} key missing from Command dictionary entry: {str(cmd_dict)}"
            )
        # Parse Arguments
        cmd_args = []
        for param in cmd_dict.get(self.PARAMETERS, []):
            try:
                param_name = param["name"]
                param_type = self.parse_type(param["type"])
            except KeyError as e:
                raise GdsDictionaryParsingException(
                    f"{str(e)} key missing from Command parameter or its associated type in the dictionary: {str(param)}"
                )
            cmd_args.append(
                (
                    param_name,
                    param.get("annotation"),
                    param_type,
                )
            )
        return CmdTemplate(cmd_opcode, cmd_mnemonic, qualified_component_name, cmd_args, cmd_desc)
