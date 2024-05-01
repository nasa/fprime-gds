"""
ch_json_loader.py:

Loads flight dictionary (JSON) and returns id and mnemonic based Python dictionaries of channels

@author thomas-bc
"""

from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.loaders.json_loader import JsonLoader


class ChJsonLoader(JsonLoader):
    """Class to load python based telemetry channel dictionaries"""

    ID = "id"
    NAME = "name"
    DESC = "annotation"
    TYPE = "type"
    FMT_STR = "format"
    LIMIT_FIELD = "limit"
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

        for ch_dict in self.json_dict["telemetryChannels"]:
            # Create a channel template object
            ch_temp = self.construct_template_from_dict(ch_dict)

            id_dict[ch_temp.get_id()] = ch_temp
            name_dict[ch_temp.get_full_name()] = ch_temp

        return (
            id_dict,
            name_dict,
            self.get_versions(),
        )

    def construct_template_from_dict(self, channel_dict: dict) -> ChTemplate:
        component_name = channel_dict[self.NAME].split(".")[0]
        channel_name = channel_dict[self.NAME].split(".")[1]
        channel_type = channel_dict[self.TYPE]
        type_obj = self.parse_type(channel_type)
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
            channel_dict[self.ID],
            channel_name,
            component_name,
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
