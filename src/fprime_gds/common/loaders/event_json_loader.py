"""
event_json_loader.py:

Loads flight dictionary (JSON) and returns id and mnemonic based Python dictionaries of events

@author thomas-bc
"""

from fprime_gds.common.data_types import exceptions
from fprime_gds.common.templates.event_template import EventTemplate
from fprime_gds.common.utils.event_severity import EventSeverity

# Custom Python Modules
from fprime_gds.common.loaders.json_loader import JsonLoader


class EventJsonLoader(JsonLoader):
    """Class to load xml based event dictionaries"""

    EVENT_SECT = "events"

    COMP_TAG = "component"
    NAME_TAG = "name"
    ID_TAG = "id"
    SEVERITY_TAG = "severity"
    FMT_STR_TAG = "format"
    DESC_TAG = "annotation"

    def construct_dicts(self, path):
        """
        Constructs and returns python dictionaries keyed on id and name

        This function should not be called directly, instead, use
        get_id_dict(path) and get_name_dict(path)

        Args:
            path: Path to the xml dictionary file containing event information

        Returns:
            A tuple with two event dictionaries (python type dict):
            (id_dict, name_dict). The keys are the events' id and name fields
            respectively and the values are ChTemplate objects
        """
        id_dict = {}
        name_dict = {}

        for event_dict in self.json_dict.get("events"):
            event_temp = self.construct_template_from_dict(event_dict)

            id_dict[event_temp.get_id()] = event_temp
            name_dict[event_temp.get_full_name()] = event_temp

        return (
            id_dict,
            name_dict,
            self.get_versions(),
        )

    def construct_template_from_dict(self, event_dict: dict):
        event_mnemonic = event_dict.get("name")
        event_comp = event_mnemonic.split(".")[0]
        event_name = event_mnemonic.split(".")[1]

        event_id = event_dict[self.ID_TAG]
        event_severity = EventSeverity[event_dict[self.SEVERITY_TAG]]

        event_fmt_str = JsonLoader.preprocess_format_str(
            event_dict.get(self.FMT_STR_TAG, "")
        )

        event_desc = event_dict.get(self.DESC_TAG)

        # Parse arguments
        event_args = []
        for arg in event_dict.get("formalParams", []):
            event_args.append(
                (
                    arg.get("name"),
                    arg.get("annotation"),
                    self.parse_type(arg.get("type")),
                )
            )

        return EventTemplate(
            event_id,
            event_name,
            event_comp,
            event_args,
            event_severity,
            event_fmt_str,
            event_desc,
        )