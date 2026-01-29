"""
dp_json_loader.py:

Loads flight dictionary (JSON) and returns id and name based Python dictionaries 
of data product records and containers.

This loader extracts data product metadata from the JSON dictionary and populates
the ConfigManager with:
1. Data product records (id -> DpRecordTemplate mapping)
2. Data product containers (id -> DpContainerTemplate mapping)

@author thomas-bc
@date January 2026
"""

from fprime_gds.common.templates.dp_record_template import DpRecordTemplate
from fprime_gds.common.templates.dp_container_template import DpContainerTemplate
from fprime_gds.common.loaders.json_loader import JsonLoader
from fprime_gds.common.data_types.exceptions import GdsDictionaryParsingException


class DpJsonLoader(JsonLoader):
    """Class to load JSON based data product dictionaries"""

    RECORDS_FIELD = "records"
    CONTAINERS_FIELD = "containers"

    # Record fields
    RECORD_NAME = "name"
    RECORD_ID = "id"
    RECORD_TYPE = "type"
    RECORD_ARRAY = "array"
    RECORD_ANNOTATION = "annotation"

    # Container fields
    CONTAINER_NAME = "name"
    CONTAINER_ID = "id"
    CONTAINER_DEFAULT_PRIORITY = "defaultPriority"
    CONTAINER_ANNOTATION = "annotation"

    def construct_dicts(self, _):
        """
        Constructs and returns python dictionaries for both records and containers

        Args:
            _: Unused argument (inherited)

        Returns:
            A tuple with four dictionaries:
            (record_id_dict, record_name_dict, container_id_dict, container_name_dict)
            - record_id_dict: Maps record ID to DpRecordTemplate
            - record_name_dict: Maps record name to DpRecordTemplate
            - container_id_dict: Maps container ID to DpContainerTemplate
            - container_name_dict: Maps container name to DpContainerTemplate
        """
        # Parse records
        record_id_dict = {}
        record_name_dict = {}

        if self.RECORDS_FIELD in self.json_dict:
            for record_dict in self.json_dict[self.RECORDS_FIELD]:
                record_temp = self.construct_record_template_from_dict(record_dict)
                record_id_dict[record_temp.get_id()] = record_temp
                record_name_dict[record_temp.get_full_name()] = record_temp

        # Parse containers
        container_id_dict = {}
        container_name_dict = {}

        if self.CONTAINERS_FIELD in self.json_dict:
            for container_dict in self.json_dict[self.CONTAINERS_FIELD]:
                container_temp = self.construct_container_template_from_dict(
                    container_dict
                )
                container_id_dict[container_temp.get_id()] = container_temp
                container_name_dict[container_temp.get_full_name()] = container_temp

        # Not respecting the interface, but this is Python so, eh? it's cleaner this way
        return (
            dict(sorted(record_id_dict.items())),
            dict(sorted(record_name_dict.items())),
            dict(sorted(container_id_dict.items())),
            dict(sorted(container_name_dict.items())),
            self.get_versions(),
        )

    def construct_record_template_from_dict(
        self, record_dict: dict
    ) -> DpRecordTemplate:
        """
        Construct a DpRecordTemplate from a dictionary entry

        Args:
            record_dict: Dictionary containing record information

        Returns:
            DpRecordTemplate object

        Raises:
            GdsDictionaryParsingException: If required fields are missing or malformed
        """
        try:
            record_name = record_dict[self.RECORD_NAME]
            record_id = record_dict[self.RECORD_ID]
            record_type_dict = record_dict[self.RECORD_TYPE]
            is_array = record_dict.get(self.RECORD_ARRAY, False)
            description = record_dict.get(self.RECORD_ANNOTATION)

            # Parse the type using the inherited parse_type method
            record_type = self.parse_type(record_type_dict)

        except KeyError as e:
            raise GdsDictionaryParsingException(
                f"{str(e)} key missing from Data Product Record dictionary entry: {str(record_dict)}"
            )
        except Exception as e:
            raise GdsDictionaryParsingException(
                f"Error parsing Data Product Record: {str(record_dict)}, Error: {str(e)}"
            )

        return DpRecordTemplate(
            record_id=record_id,
            record_name=record_name,
            record_type=record_type,
            is_array=is_array,
            description=description,
        )

    def construct_container_template_from_dict(
        self, container_dict: dict
    ) -> DpContainerTemplate:
        """
        Construct a DpContainerTemplate from a dictionary entry

        Args:
            container_dict: Dictionary containing container information

        Returns:
            DpContainerTemplate object

        Raises:
            GdsDictionaryParsingException: If required fields are missing or malformed
        """
        try:
            container_name = container_dict[self.CONTAINER_NAME]
            container_id = container_dict[self.CONTAINER_ID]
            default_priority = container_dict[self.CONTAINER_DEFAULT_PRIORITY]
            description = container_dict.get(self.CONTAINER_ANNOTATION)

        except KeyError as e:
            raise GdsDictionaryParsingException(
                f"{str(e)} key missing from Data Product Container dictionary entry: {str(container_dict)}"
            )
        except Exception as e:
            raise GdsDictionaryParsingException(
                f"Error parsing Data Product Container: {str(container_dict)}, Error: {str(e)}"
            )

        return DpContainerTemplate(
            container_id=container_id,
            container_name=container_name,
            default_priority=default_priority,
            description=description,
        )
