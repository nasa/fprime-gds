"""
event_json_loader.py:

Loads flight dictionary (JSON) and returns id and mnemonic based Python dictionaries of events

@author thomas-bc
"""

from fprime_gds.common.templates.event_template import EventTemplate
from fprime_gds.common.utils.event_severity import EventSeverity
from fprime_gds.common.loaders.json_loader import JsonLoader
from fprime_gds.common.data_types.exceptions import GdsDictionaryParsingException


class EventJsonLoader(JsonLoader):
    """Class to load json based event dictionaries"""

    EVENTS_FIELD = "events"

    NAME = "name"
    ID = "id"
    SEVERITY = "severity"
    FMT_STR = "format"
    DESC = "annotation"
    PARAMETERS = "formalParams"

    def construct_dicts(self, _):
        """
        Constructs and returns python dictionaries keyed on id and name

        This function should not be called directly, instead, use
        get_id_dict(path) and get_name_dict(path)

        Args:
            _: Unused argument (inherited)

        Returns:
            A tuple with two event dictionaries (python type dict):
            (id_dict, name_dict). The keys are the events' id and name fields
            respectively and the values are ChTemplate objects
        """
        id_dict = {}
        name_dict = {}

        if self.EVENTS_FIELD not in self.json_dict:
            raise GdsDictionaryParsingException(
                f"Ground Dictionary missing '{self.EVENTS_FIELD}' field: {str(self.json_file)}"
            )

        for event_dict in self.json_dict[self.EVENTS_FIELD]:
            event_temp = self.construct_template_from_dict(event_dict)

            id_dict[event_temp.get_id()] = event_temp
            name_dict[event_temp.get_full_name()] = event_temp

        return (
            dict(sorted(id_dict.items())),
            dict(sorted(name_dict.items())),
            self.get_versions(),
        )

    def construct_template_from_dict(self, event_dict: dict):
        try:
            qualified_component_name, event_name = event_dict[self.NAME].rsplit('.', 1)
            event_id = event_dict[self.ID]
            event_severity = EventSeverity[event_dict[self.SEVERITY]]
        except ValueError as e:
            raise GdsDictionaryParsingException(
                f"Event dictionary entry malformed, expected name of the form '<QUAL_COMP_NAME>.<EVENT_NAME>' in : {str(event_dict)}"
            )
        except KeyError as e:
            raise GdsDictionaryParsingException(
                f"{str(e)} key missing from Event dictionary entry: {str(event_dict)}"
            )

        event_fmt_str = JsonLoader.preprocess_format_str(
            event_dict.get(self.FMT_STR, "")
        )

        event_desc = event_dict.get(self.DESC)

        # Parse arguments
        event_args = []
        for arg in event_dict.get(self.PARAMETERS, []):
            try:
                arg_name = arg["name"]
                arg_type = self.parse_type(arg["type"])
            except KeyError as e:
                raise GdsDictionaryParsingException(
                    f"{str(e)} key missing from Event parameter or its associated type in the dictionary: {str(arg)}"
                )
            event_args.append(
                (
                    arg_name,
                    arg.get("annotation"),
                    arg_type,
                )
            )

        return EventTemplate(
            event_id,
            event_name,
            qualified_component_name,
            event_args,
            event_severity,
            event_fmt_str,
            event_desc,
        )
