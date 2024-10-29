import numbers
from dataclasses import dataclass
import inspect
import ast
from pathlib import Path
from argparse import ArgumentParser
import sys
import logging

logging.basicConfig()
logger = logging.getLogger(__file__)
from fprime_gds.common.data_types.cmd_data import CmdData
from fprime_gds.common.loaders.cmd_json_loader import CmdJsonLoader
from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime.common.models.serialize.serializable_type import SerializableType
from fprime.common.models.serialize.array_type import ArrayType
from fprime.common.models.serialize.numerical_types import (
    I16Type,
    I32Type,
    I64Type,
    I8Type,
    F32Type,
    F64Type,
    U16Type,
    U32Type,
    U64Type,
    U8Type,
)
from fprime.common.models.serialize.bool_type import BoolType
from fprime.common.models.serialize.string_type import StringType
from fprime.common.models.serialize.enum_type import EnumType
from fprime.common.models.serialize.type_base import BaseType, ValueType


@dataclass
class CmdCall:
    node: ast.Call
    cmd_name: str
    cmd_template: CmdTemplate
    args: list


@dataclass
class TypeInstantiate:
    node: ast.Call
    type_name: str
    type_template: BaseType
    args: list


class TransformToFPrime(ast.NodeTransformer):

    def __init__(self, cmd_name_dict: dict[str, CmdTemplate], type_name_dict: dict[str, type[ValueType]]) -> None:
        super().__init__()
        self.cmd_name_dict = cmd_name_dict

    def visit_Module(self, node: ast.Module):
        for statement in node.body:
            statement: ast.stmt
            if not isinstance(statement, ast.Expr) or not isinstance(
                statement.value, ast.Call
            ):
                statement.error = "Invalid syntax: Sequences can only contain commands"
        return self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        """resolve the attribute into either a CmdTemplate instance or a BaseType type"""

        namespace_node = node.value
        # concatenate namespaces
        namespace = []
        while isinstance(namespace_node, ast.Attribute):
            namespace.insert(0, namespace_node.attr)
            namespace_node = namespace_node.value

        if isinstance(namespace_node, ast.Name):
            namespace.insert(0, namespace_node.id)

        namespace_str = ".".join(namespace)


    def visit_Call(self, node: ast.Call):

        cmd_name = self.get_name(node.func)
        if cmd_name not in self.cmd_name_dict:
            node.error = "Unknown command name " + str(cmd_name)
            return node

        cmd_template: CmdTemplate = self.cmd_name_dict[cmd_name]
        cmd_args_map = self.map_cmd_args(cmd_template, node)
        for fprime_arg, fpy_expr in cmd_args_map:
            fprime_name, fprime_desc, fprime_type = fprime_arg
            self.fpy_node_to_fprime_type(cmd_template, fprime_name, fprime_type, fpy_expr)

    def map_cmd_args(
        self, template: CmdTemplate, node: ast.Call
    ) -> dict[tuple[str, str, ValueType], ast.Expression]:
        """
        Maps arguments from a command template to an fpy expression by position and name. Does not perform type checking.
        """

        mapping = dict()

        for idx, arg_template in enumerate(template.arguments):
            arg_name, arg_desc, arg_type = arg_template

            arg_node = None

            if idx < len(node.args):
                # if we're still in positional args
                arg_node = node.args[idx]
            else:
                # if we're in kwargs
                # find a matching node from keywords
                arg_node = [n for n in node.keywords if n.arg == arg_name]
                if len(arg_node) != 1:
                    if len(arg_node) == 0:
                        # unable to find a matching kwarg for this arg template
                        node.error = "Missing argument " + str(arg_name)
                        continue
                    else:
                        for arg_n in arg_node:
                            arg_n.error = "Multiple values for " + str(arg_name)
                        continue

                arg_node = arg_node[0]

            mapping[arg_template] = arg_node

        return mapping

    def fpy_node_to_fprime_type(
        self,
        cmd_template: CmdTemplate,
        arg_name: str,
        fprime_type_name: str,
        fprime_type: type,
        fpy_node: ast.Expression,
    ) -> ValueType:
        """
        Ensure the fpy node can be turned into the desired FPrime type
        """

        def error(node, msg):
            node.error = "In command " + str(cmd_template.get_comp_name()) + "." + str(cmd_template.get_name()) + " for argument " + str(arg_name) + ": " + str(msg)


        fprime_type_instance = fprime_type()
        if issubclass(fprime_type, BoolType):
            if not isinstance(fpy_node, ast.Constant) or not isinstance(
                fpy_node.value, bool
            ):
                error(fpy_node, "Expected a boolean literal, found " + str(type(fpy_node.value)))
                return fprime_type_instance
            fprime_type_instance._val = fpy_node.value
        elif issubclass(fprime_type, (F64Type, F32Type)):
            if not isinstance(fpy_node, ast.Constant) or not isinstance(
                fpy_node.value, float
            ):
                error(fpy_node, "Expected a floating point literal, found " + str(type(fpy_node.value)))
                return fprime_type_instance
            fprime_type_instance._val = fpy_node.value
        elif issubclass(
            fprime_type,
            (I64Type, U64Type, I32Type, U32Type, I16Type, U16Type, I8Type, U8Type),
        ):
            if not isinstance(fpy_node, ast.Constant) or not isinstance(
                fpy_node.value, int
            ):
                error(fpy_node, "Expected an integer literal, found " + str(type(fpy_node.value)))
                return fprime_type_instance
            fprime_type_instance._val = fpy_node.value
        elif issubclass(fprime_type, StringType):
            if not isinstance(fpy_node, ast.Constant) or not isinstance(
                fpy_node.value, str
            ):
                error(fpy_node, "Expected a string literal, found " + str(type(fpy_node.value)))
                return fprime_type_instance
            fprime_type_instance._val = fpy_node.value
        elif issubclass(fprime_type, EnumType):

            # all enums follow the form Fprime.Qualified.Type.ENUM_CONST_NAME
            if not isinstance(fpy_node, ast.Attribute):
                # not an enum literal
                error(fpy_node, "Expected an enum literal")
                return fprime_type_instance

            fpy_enum_name = self.get_name(fpy_node.value) # fpy_node.value is the fqn of the enum
            if fpy_enum_name is None:
                # unable to get the name from this ast
                error(fpy_node, "Invalid syntax")
                return fprime_type_instance

            resolved_enum_type = self.resolve_type_name(fpy_enum_name)
            if resolved_enum_type is None:
                # couldn't find this enum in the type dict
                error(fpy_node, "Unknown type " + str(fpy_enum_name))
                return fprime_type_instance

            if resolved_enum_type != fprime_type:
                # wrong type
                error(fpy_node, "Expected a value from enum " + str(fprime_type.__name__) + " but got one from " + str(resolved_enum_type.__name__))
                return fprime_type_instance

            fprime_type_instance._val = fpy_node.attr # fpy_node.attr is ENUM_CONST_NAME

        elif issubclass(fprime_type, (ArrayType, SerializableType)):


            
            # all arrays and structs follow the form Fprime.Qualified.Type(<args>)
            fpy_type_name = self.get_name(fpy_node.value) # fpy_node.value is the fqn of the enum
            if fpy_enum_name is None:
                # unable to get the name from this ast
                fpy_node.error = "Invalid syntax"
                return fprime_type_instance

            resolved_enum_type = self.resolve_type_name(fpy_enum_name)
            if resolved_enum_type is None:
                # couldn't find this enum in the type dict
                fpy_node.error = "Unknown type " + str(fpy_enum_name)
                return fprime_type_instance

            if resolved_enum_type != fprime_type:
                # wrong enum
                fpy_node.error = "Expected a value from enum " + str(fprime_type.__name__) + " but got one from " + str(resolved_enum_type.__name__)
                return fprime_type_instance

            fprime_type_instance._val = fpy_node.attr

    def node_to_fprime_type(self, node: ast.Expression, into_type: ValueType) -> bool:
        """
        Turn the node into an instance of the desired FPrime type
        """
        return False

    def get_name(self, name: ast.Expression) -> str|None:

    def resolve_cmd_name(self, cmd_name: str) -> CmdTemplate|None:
        return self.cmd_name_dict.get(cmd_name, None)

    def resolve_type_name(self, enum_name: str) -> type[ValueType]|None:
        return self.type_name_dict.get(enum_name, str)

    def process_args(self, input_values):
        """Process input arguments"""
        errors = []
        args = []
        for val, arg_tuple in zip(input_values, self.template.arguments):
            try:
                _, _, arg_type = arg_tuple
                arg_value = arg_type()
                self.convert_arg_value(val, arg_value)
                args.append(arg_value)
                errors.append("")
            except Exception as exc:
                errors.append(str(exc))
        return args, errors


def check_for_errors(node: ast.Module):
    def visit(n):
        if hasattr(n, "error"):
            error_str = "error"
            if hasattr(n, "lineno"):
                error_str += " on line " + str(n.lineno)
            error_str += ": " + n.error
            print(error_str)
            return False
        for field, value in ast.iter_fields(n):
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        return visit(item)
            elif isinstance(value, ast.AST):
                return visit(value)
        return True

    return visit(node)


def main():
    arg_parser = ArgumentParser(
        description="A compiler for the FPrime advanced sequencing language"
    )

    arg_parser.add_argument(
        "input", type=Path, help="The path of the input sequence to compile"
    )
    arg_parser.add_argument(
        "-d",
        "--dictionary",
        type=Path,
        help="The JSON topology dictionary to compile against",
    )

    args = arg_parser.parse_args()

    input_text = args.input.read_text()

    node = ast.parse(input_text)

    compile(node, args.dictionary)


def compile(node: ast.Module, dictionary: Path):
    print(ast.dump(node, indent=4))
    cmd_json_dict = CmdJsonLoader(dictionary)
    (cmd_id_dict, cmd_name_dict, versions) = cmd_json_dict.construct_dicts(dictionary)
    type_name_dict = cmd_json_dict.parsed_types
    py_to_fprime_transformer = TransformToFPrime(cmd_name_dict, type_name_dict)
    node = py_to_fprime_transformer.visit(node)
    if not check_for_errors(node):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
