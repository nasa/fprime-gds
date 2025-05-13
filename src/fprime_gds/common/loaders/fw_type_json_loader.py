"""
fw_type_json_loader.py:

Loads flight dictionary (JSON) and returns name based Python dictionaries of Fw types

@author jawest
"""

from fprime_gds.common.loaders.json_loader import JsonLoader
from fprime_gds.common.data_types.exceptions import GdsDictionaryParsingException

class FwTypeJsonLoader(JsonLoader):
    """Class to load python based Fw type dictionaries"""

    TYPE_DEFINITIONS_FIELD = "typeDefinitions"

    def construct_dicts(self, _):
        """
        Constructs and returns python dictionaries keyed on id and name

        Args:
            _: Unused argument (inherited)
        Returns:
            A tuple with two Fw type dictionaries (python type dict):
            (id_dict, name_dict). The keys should be the type id and
            name fields respectively and the values should be type name
            strings. Note: An empty id dictionary is returned since there 
            are no id fields in the Fw type alias JSON dictionary entries.
        """
        id_dict = {}
        name_dict = {}

        if self.TYPE_DEFINITIONS_FIELD not in self.json_dict:
            raise GdsDictionaryParsingException(
                f"Ground Dictionary missing '{self.TYPE_DEFINITIONS_FIELD}' field: {str(self.json_file)}"
            )

        for type_def in self.json_dict[self.TYPE_DEFINITIONS_FIELD]:
            try:
                if type_def["kind"] == "alias":
                    name = str(type_def["qualifiedName"])
                    # Only consider names with the pattern Fw*Type
                    if name.startswith("Fw") and name.endswith("Type"):
                        name_dict[type_def["qualifiedName"]] = type_def["underlyingType"]["name"]
            except KeyError as e:
                raise GdsDictionaryParsingException(
                    f"{str(e)} key missing from Type Definition dictionary entry: {str(type_def)}"
                )

        return (
            dict(sorted(id_dict.items())),
            dict(sorted(name_dict.items())),
            self.get_versions(),
        )
