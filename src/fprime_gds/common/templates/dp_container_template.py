"""
@brief Data Product Container template class

Data Product Container templates describe data product container definitions from the
F Prime dictionary. Each container has an ID, name, and default priority.

@date Created January 2026
@author thomas-bc

@bug No known bugs
"""
from dataclasses import dataclass
from typing import Optional

from fprime_gds.common.templates.data_template import DataTemplate


@dataclass
class DpContainerTemplate(DataTemplate):
    """Data Product Container template class"""

    container_id: int
    container_name: str
    default_priority: int
    description: Optional[str] = None

    def get_id(self) -> int:
        """Get the container's ID"""
        return self.container_id

    def get_name(self) -> str:
        """Get the container's full name"""
        return self.container_name

    def get_full_name(self) -> str:
        """Get the container's full name (alias for get_name)"""
        return self.container_name

    def get_default_priority(self) -> int:
        """Get the container's default priority"""
        return self.default_priority

    def get_description(self) -> Optional[str]:
        """Get the container's description"""
        return self.description

    def __str__(self) -> str:
        return f"DpContainer({self.container_id}, {self.container_name}, default_priority={self.default_priority}, description={self.description})"
