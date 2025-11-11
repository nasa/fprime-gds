"""
@brief Params Template class

Instances of this class describe a parameter of a component instance (not
including a specific value)

@date Created January 27, 2025
@author Zimri Leisher

@bug Hopefully none
"""

from fprime_gds.common.models.serialize.type_base import BaseType
from fprime_gds.common.models.serialize.type_exceptions import TypeMismatchException

from . import data_template


class PrmTemplate(data_template.DataTemplate):
    """Class for param templates that describe parameters of component instances"""

    def __init__(
        self,
        prm_id: int,
        prm_name: str,
        comp_name: str,
        prm_type_obj: BaseType,
        prm_default_val,
    ):
        """
        Constructor

        Args:
            prm_id: the id of the parameter
            prm_name: the name of the parameter
            comp_name: the name of the component instance owning this parameter
            prm_type_obj: the instance of BaseType corresponding to the type of this parameter
            prm_default_val: the default value of this parameter, in raw JSON form
        """
        super().__init__()
        # Make sure correct types are passed
        if not isinstance(prm_id, int):
            raise TypeMismatchException(int, type(prm_id))

        if not isinstance(prm_name, str):
            raise TypeMismatchException(str, type(prm_name))

        if not isinstance(comp_name, str):
            raise TypeMismatchException(str, type(comp_name))

        if not issubclass(prm_type_obj, BaseType):
            raise TypeMismatchException(BaseType, prm_type_obj)

        # prm_default_val is an arbitrary type, likely a primitive or dict

        self.prm_id = prm_id
        self.prm_name = prm_name
        self.comp_name = comp_name
        self.prm_type_obj = prm_type_obj
        self.prm_default_val = prm_default_val

    def get_full_name(self):
        """
        Get the full name of this param

        Returns:
            The full name (component.param) for this param
        """
        return f"{self.comp_name}.{self.prm_name}"

    def get_id(self):
        return self.prm_id

    def get_name(self):
        return self.prm_name

    def get_comp_name(self):
        return self.comp_name

    def get_type_obj(self):
        return self.prm_type_obj
