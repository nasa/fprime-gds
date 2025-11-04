"""
fw_type_json_loader.py:

Loads flight dictionary (JSON) and returns name based Python dictionaries of Fw types

@author jawest
"""

from fprime_gds.common.loaders.json_loader import JsonLoader
from fprime_gds.common.data_types.exceptions import GdsDictionaryParsingException


class TypeJsonLoader(JsonLoader):
    """Class to load Python objects representing types from the JSON dictionary

    While most types will be parsed from being referenced in other dictionary entries
    (e.g. an event argument that references a type definition), this loader specifically
    loops through all typeDefinitions entries in the dictionary. This allows for types
    that are not referenced elsewhere to still be loaded and available. This is needed
    for example for base Fw types and config types (Fw_Types, ComCfg)
    """

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
        name_dict = {}

        if self.TYPE_DEFINITIONS_FIELD not in self.json_dict:
            raise GdsDictionaryParsingException(
                f"Ground Dictionary missing '{self.TYPE_DEFINITIONS_FIELD}' field: {str(self.json_file)}"
            )

        for type_def in self.json_dict[self.TYPE_DEFINITIONS_FIELD]:
            try:
                name_dict[type_def["qualifiedName"]] = self.parse_type_definition(
                    type_def
                )
            except KeyError as e:
                raise GdsDictionaryParsingException(
                    f"{str(e)} key missing from Type Definition dictionary entry: {str(type_def)}"
                )

        return (
            {},  # No id for type definitions
            dict(sorted(name_dict.items())),
            self.get_versions(),
        )
