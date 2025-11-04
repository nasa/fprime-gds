"""
constant_json_loader.py:

Loads flight dictionary (JSON) and returns dictionaries of all constants
defined in the dictionary.

@author thomas-bc
"""

from fprime_gds.common.loaders.json_loader import JsonLoader
from fprime_gds.common.data_types.exceptions import GdsDictionaryParsingException


class ConstantJsonLoader(JsonLoader):
    """Class to load Python objects representing constants from the JSON dictionary"""

    CONSTANTS_FIELD = "constants"

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

        if self.CONSTANTS_FIELD not in self.json_dict:
            print(f"[WARNING] Ground Dictionary missing 'constants' field, relying on defaults. In: {str(self.json_file)}")

        for constant in self.json_dict[self.CONSTANTS_FIELD]:
            try:
                name_dict[constant["qualifiedName"]] = constant["value"]
            except KeyError as e:
                raise GdsDictionaryParsingException(
                    f"{str(e)} key missing from Constant dictionary entry: {str(constant)}"
                )

        return (
            {},  # No id for constants
            dict(sorted(name_dict.items())),
            self.get_versions(),
        )
