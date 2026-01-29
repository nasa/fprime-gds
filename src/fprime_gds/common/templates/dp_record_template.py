"""
@brief Data Product Record template class

Data Product Record templates describe data product record definitions from the
F Prime dictionary. Each record has an ID, name, type, and whether it's an array.

@date Created January 2026
@author thomas-bc

@bug No known bugs
"""
from dataclasses import dataclass, field
from typing import Optional

from fprime_gds.common.templates.data_template import DataTemplate
from fprime_gds.common.models.serialize.type_base import DictionaryType


@dataclass
class DpRecordTemplate(DataTemplate):
    """Data Product Record template class"""

    record_id: int
    record_name: str
    record_type_name: str = field(init=False)  # Type name in FPP, computed from record_type
    record_type: DictionaryType
    is_array: bool
    description: Optional[str] = None

    def __post_init__(self):
        """Enables record_type_name property to be computed from record_type info"""
        self.record_type_name = self.record_type.__name__

    def get_id(self) -> int:
        """Get the record's ID"""
        return self.record_id

    def get_name(self) -> str:
        """Get the record's full name"""
        return self.record_name

    def get_full_name(self) -> str:
        """Get the record's full name (alias for get_name)"""
        return self.record_name

    def get_type(self) -> DictionaryType:
        """Get the record's type"""
        return self.record_type

    def get_is_array(self) -> bool:
        """Check if this record is an array"""
        return self.is_array

    def get_description(self) -> Optional[str]:
        """Get the record's description"""
        return self.description

