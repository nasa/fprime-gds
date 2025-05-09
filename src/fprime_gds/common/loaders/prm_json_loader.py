"""
prm_json_loader.py:

Loads flight dictionary (JSON) and returns id and mnemonic based Python dictionaries of params

@author zimri.leisher
"""

from fprime_gds.common.templates.prm_template import PrmTemplate
from fprime_gds.common.loaders.json_loader import JsonLoader
from fprime_gds.common.data_types.exceptions import GdsDictionaryParsingException


class PrmJsonLoader(JsonLoader):
    """Class to load parameters from json dictionaries"""

    PARAMS_FIELD = "parameters"

    ID = "id"
    NAME = "name"
    TYPE = "type"
    DESC = "annotation"
    DEFAULT = "default"
    

    def construct_dicts(self, _):
        """
        Constructs and returns python dictionaries keyed on id and name

        Args:
            _: Unused argument (inherited)
        Returns:
            A tuple with two channel dictionaries (python type dict):
            (id_dict, fqn_name_dict). The keys should be the channels' id and
            fully qualified name fields respectively and the values should be PrmTemplate
            objects.
        """
        id_dict = {}
        fqn_name_dict = {}

        if self.PARAMS_FIELD not in self.json_dict:
            raise GdsDictionaryParsingException(
                f"Ground Dictionary missing '{self.PARAMS_FIELD}' field: {str(self.json_file)}"
            )

        for prm_dict in self.json_dict[self.PARAMS_FIELD]:
            # Create a channel template object
            prm_temp = self.construct_template_from_dict(prm_dict)

            id_dict[prm_temp.get_id()] = prm_temp
            fqn_name_dict[prm_temp.get_full_name()] = prm_temp

        return (
            dict(sorted(id_dict.items())),
            dict(sorted(fqn_name_dict.items())),
            self.get_versions(),
        )

    def construct_template_from_dict(self, prm_dict: dict) -> PrmTemplate:
        try:
            prm_id = prm_dict[self.ID]
            # The below assignment also raises a ValueError if the name does not contain a '.'
            qualified_component_name, prm_name = prm_dict[self.NAME].rsplit('.', 1)
            if not qualified_component_name or not prm_name:
                raise ValueError()

            type_obj = self.parse_type(prm_dict[self.TYPE])
        except ValueError as e:
            raise GdsDictionaryParsingException(
                f"Parameter dictionary entry malformed, expected name of the form '<QUAL_COMP_NAME>.<PRM_NAME>' in : {str(prm_dict)}"
            )
        except KeyError as e:
            raise GdsDictionaryParsingException(
                f"{str(e)} key missing from parameter dictionary entry or its associated type in the dictionary: {str(prm_dict)}"
            )

        prm_default_val = prm_dict.get(self.DEFAULT, None)

        return PrmTemplate(
            prm_id,
            prm_name,
            qualified_component_name,
            type_obj,
            prm_default_val
        )