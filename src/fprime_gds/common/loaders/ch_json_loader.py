"""
ch_json_loader.py:

Loads flight dictionary (JSON) and returns id and mnemonic based Python dictionaries of channels

@author thomas-bc
"""

from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.loaders.json_loader import JsonLoader
from fprime_gds.common.data_types.exceptions import GdsDictionaryParsingException


class ChJsonLoader(JsonLoader):
    """Class to load python based telemetry channel dictionaries"""

    CHANNELS_FIELD = "telemetryChannels"

    ID = "id"
    NAME = "name"
    DESC = "annotation"
    TYPE = "type"
    FMT_STR = "format"
    LIMIT_FIELD = "limits"
    LIMIT_LOW = "low"
    LIMIT_HIGH = "high"
    LIMIT_RED = "red"
    LIMIT_ORANGE = "orange"
    LIMIT_YELLOW = "yellow"

    def construct_dicts(self, _):
        """
        Constructs and returns python dictionaries keyed on id and name

        Args:
            _: Unused argument (inherited)
        Returns:
            A tuple with two channel dictionaries (python type dict):
            (id_dict, name_dict). The keys should be the channels' id and
            name fields respectively and the values should be ChTemplate
            objects.
        """
        id_dict = {}
        name_dict = {}

        if self.CHANNELS_FIELD not in self.json_dict:
            raise GdsDictionaryParsingException(
                f"Ground Dictionary missing '{self.CHANNELS_FIELD}' field: {str(self.json_file)}"
            )

        for ch_dict in self.json_dict[self.CHANNELS_FIELD]:
            # Create a channel template object
            ch_temp = self.construct_template_from_dict(ch_dict)

            id_dict[ch_temp.get_id()] = ch_temp
            name_dict[ch_temp.get_full_name()] = ch_temp

        return (
            dict(sorted(id_dict.items())),
            dict(sorted(name_dict.items())),
            self.get_versions(),
        )

    def construct_template_from_dict(self, channel_dict: dict) -> ChTemplate:
        try:
            ch_id = channel_dict[self.ID]
            # The below assignment also raises a ValueError if the name does not contain a '.'
            qualified_component_name, channel_name = channel_dict[self.NAME].rsplit('.', 1)
            if not qualified_component_name or not channel_name:
                raise ValueError()

            type_obj = self.parse_type(channel_dict[self.TYPE])
        except ValueError as e:
            raise GdsDictionaryParsingException(
                f"Channel dictionary entry malformed, expected name of the form '<QUAL_COMP_NAME>.<CH_NAME>' in : {str(channel_dict)}"
            )
        except KeyError as e:
            raise GdsDictionaryParsingException(
                f"{str(e)} key missing from Channel dictionary entry or its associated type in the dictionary: {str(channel_dict)}"
            )

        format_str = JsonLoader.preprocess_format_str(channel_dict.get(self.FMT_STR))

        limit_field = channel_dict.get(self.LIMIT_FIELD)
        limit_low = limit_field.get(self.LIMIT_LOW) if limit_field else None
        limit_high = limit_field.get(self.LIMIT_HIGH) if limit_field else None
        limit_low_yellow = limit_low.get(self.LIMIT_YELLOW) if limit_low else None
        limit_low_red = limit_low.get(self.LIMIT_RED) if limit_low else None
        limit_low_orange = limit_low.get(self.LIMIT_ORANGE) if limit_low else None
        limit_high_yellow = limit_high.get(self.LIMIT_YELLOW) if limit_high else None
        limit_high_red = limit_high.get(self.LIMIT_RED) if limit_high else None
        limit_high_orange = limit_high.get(self.LIMIT_ORANGE) if limit_high else None

        return ChTemplate(
            ch_id,
            channel_name,
            qualified_component_name,
            type_obj,
            ch_fmt_str=format_str,
            ch_desc=channel_dict.get(self.DESC),
            low_red=limit_low_red,
            low_orange=limit_low_orange,
            low_yellow=limit_low_yellow,
            high_yellow=limit_high_yellow,
            high_orange=limit_high_orange,
            high_red=limit_high_red,
        )
