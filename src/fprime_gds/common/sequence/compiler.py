import numbers
from dataclasses import dataclass
import inspect
import ast
from pathlib import Path
from argparse import ArgumentParser
import sys
import logging

from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.executables.data_product_writer import IntegerType

logging.basicConfig()
logger = logging.getLogger(__file__)
from fprime_gds.common.loaders.cmd_json_loader import CmdJsonLoader
from fprime_gds.common.loaders.ch_json_loader import ChJsonLoader
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
from fprime.common.models.serialize.enum_type import EnumType, REPRESENTATION_TYPE_MAP
from fprime.common.models.serialize.type_base import BaseType, ValueType, DictionaryType

# name, desc, type
FpyArgTemplate = tuple[str, str, type[ValueType]]


# just for pretty-printing
def value_type_repr(self: ValueType):
    return str(self.val)


ValueType.__repr__ = value_type_repr


@dataclass
class FpyType(ast.AST):
    namespace: str
    name: str
    fprime_type: type[ValueType]


# this just helps the ast find what fields to pretty-print
FpyType._fields = ["namespace", "name", "fprime_type"]


@dataclass
class FpyEnumConstant(ast.AST):
    enum_type: type[EnumType]
    repr_type: type[ValueType]
    value: int


FpyEnumConstant._fields = ["enum_type", "repr_type", "value"]


@dataclass
class FpyCmd(ast.AST):
    namespace: str
    name: str
    cmd_template: CmdTemplate


FpyCmd._fields = ["namespace", "name", "fprime_cmd"]


@dataclass
class FpyCh(ast.AST):
    namespace: str
    name: str
    ch_template: ChTemplate


FpyCh._fields = ["namespace", "name", "fprime_ch"]


class ResolveNames(ast.NodeTransformer):

    def __init__(
        self,
        cmd_name_dict: dict[str, CmdTemplate],
        type_name_dict: dict[str, type[ValueType]],
        ch_name_dict: dict[str, ChTemplate],
    ) -> None:
        super().__init__()
        self.cmd_name_dict = cmd_name_dict
        self.type_name_dict = type_name_dict
        self.ch_name_dict = ch_name_dict

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

        # an attribute node looks like x.y
        # attr.value = x
        # attr.attr = y
        # however, x in this case could be another attribute (e.g. z.w)
        # we want to take this whole attr chain (z.w.y) and get everything except
        # the last .y, so that we can know the namespace of this attribute

        namespace_node = node.value
        # concatenate namespaces
        namespace = []
        while isinstance(namespace_node, ast.Attribute):
            namespace.insert(0, namespace_node.attr)
            namespace_node = namespace_node.value

        if isinstance(namespace_node, ast.Name):
            namespace.insert(0, namespace_node.id)

        namespace_str = ".".join(namespace)

        fq_name = node.attr
        if namespace_str != "":
            fq_name = namespace_str + "." + fq_name

        # now look up this namespace string. resolve enum consts, then types, then telemetry, then commands
        resolved_fprime_enum_type = self.type_name_dict.get(namespace_str, None)
        if resolved_fprime_enum_type is not None:
            if not issubclass(resolved_fprime_enum_type, EnumType):
                node.error = "Invalid syntax"
                return node

            # this is a python integer
            enum_value_py = resolved_fprime_enum_type.ENUM_DICT[node.attr]
            # this is a string
            enum_repr_type_name = resolved_fprime_enum_type.REP_TYPE
            # this is a subclass of ValueType
            enum_repr_type = REPRESENTATION_TYPE_MAP.get(enum_repr_type_name, None)
            assert enum_repr_type is not None

            return FpyEnumConstant(
                resolved_fprime_enum_type, enum_repr_type, enum_value_py
            )

        resolved_fprime_type = self.type_name_dict.get(fq_name, None)
        if resolved_fprime_type is not None:
            return FpyType(namespace_str, node.attr, resolved_fprime_type)

        resolved_fprime_ch = self.ch_name_dict.get(fq_name, None)
        if resolved_fprime_ch is not None:
            return FpyCh(namespace_str, node.attr, resolved_fprime_ch)

        resolved_fprime_cmd = self.cmd_name_dict.get(fq_name, None)
        if resolved_fprime_cmd is not None:
            return FpyCmd(namespace_str, node.attr, resolved_fprime_cmd)

        node.error = "Unknown identifier " + str(fq_name)
        return node


class ParseCalls(ast.NodeTransformer):

    def __init__(self, type_name_dict: dict[str, type[ValueType]]):
        self.type_name_dict = type_name_dict

    def visit_Call(self, node: ast.Call):

        # only valid calls right now are commands and dict type instantiations
        if not isinstance(node.func, (FpyCmd, FpyType)):
            node.error = "Invalid syntax"
            return node

        # okay, now map the args to the nodes
        
        if isinstance(node.func, FpyType) and not issubclass(node.func.fprime_type, DictionaryType):
            # unknown how to construct this type

        if isinstance(node.func, FpyCmd):

            mapped_args = self.map_cmd_args(node.func.cmd_template, node)

            for cmd_template_arg, ast_node in mapped_args.items():
                # get the type name of the arg from the fprime type
                fprime_type_name = [
                    k for k, v in self.type_name_dict if v == cmd_template_arg[2]
                ]
                # the type should be in the dict and there should only be one of it
                assert len(fprime_type_name) == 1
                fprime_type_name = fprime_type_name[0]
                fprime_value = self.cmd_template_arg_and_node_to_fprime_value(
                    node.func.cmd_template, cmd_template_arg, fprime_type_name, ast_node
                )

    def map_cmd_args(
        self, template: CmdTemplate, node: ast.Call
    ) -> dict[FpyArgTemplate, ast.AST]:
        """
        Maps arguments from a command template to an ast node by position and name. Does not perform type checking.
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

    def cmd_template_arg_and_node_to_fprime_value(
        self,
        cmd_template: CmdTemplate,
        cmd_arg_template: FpyArgTemplate,
        cmd_template_arg_type_name: str,
        ast_node: ast.AST,
    ) -> ValueType:
        """
        Ensure the fpy node can be turned into the desired FPrime type
        """

        arg_name = cmd_arg_template[0]
        fprime_type = cmd_arg_template[2]
        fprime_type_instance = fprime_type()

        def error(node, msg):
            node.error = (
                "In command "
                + str(cmd_template.get_comp_name())
                + "."
                + str(cmd_template.get_name())
                + ", argument "
                + str(arg_name)
                + ": "
                + msg
            )

        if issubclass(fprime_type, BoolType):
            if not isinstance(ast_node, ast.Constant):
                error(ast_node, "Invalid syntax")
                return fprime_type_instance
            if not isinstance(ast_node.value, bool):
                error(
                    ast_node,
                    "Expected a boolean literal, found "
                    + str(type(ast_node.value)),
                )
                return fprime_type_instance
            fprime_type_instance._val = ast_node.value
        elif issubclass(fprime_type, (F64Type, F32Type)):
            if not isinstance(ast_node, ast.Constant):
                error(ast_node, "Invalid syntax")
                return fprime_type_instance
            if not isinstance(ast_node.value, float):
                error(
                    ast_node,
                    "Expected a floating point literal, found "
                    + str(type(ast_node.value)),
                )
                return fprime_type_instance
            fprime_type_instance._val = ast_node.value
        elif issubclass(
            fprime_type,
            (I64Type, U64Type, I32Type, U32Type, I16Type, U16Type, I8Type, U8Type),
        ):
            if not isinstance(ast_node, ast.Constant):
                error(ast_node, "Invalid syntax")
                return fprime_type_instance
            if not isinstance(ast_node.value, float):
                error(
                    ast_node,
                    "Expected an integer literal, found "
                    + str(type(ast_node.value)),
                )
                return fprime_type_instance
            fprime_type_instance._val = ast_node.value
        elif issubclass(fprime_type, StringType):
            if not isinstance(ast_node, ast.Constant):
                error(ast_node, "Invalid syntax")
                return fprime_type_instance
            if not isinstance(ast_node.value, float):
                error(
                    ast_node,
                    "Expected an integer literal, found "
                    + str(type(ast_node.value)),
                )
                return fprime_type_instance
            fprime_type_instance._val = ast_node.value
        elif issubclass(fprime_type, EnumType):
            if not isinstance(ast_node, FpyEnumConstant):
                error(ast_node, "Invalid syntax")
                return fprime_type_instance
            assert fprime_type == ast_node.enum_type
            fprime_type_instance._val = ast_node.value
        elif issubclass(fprime_type, (ArrayType, SerializableType)):

            if not isinstance(ast_node, FpyType):


    def node_to_fprime_type(self, node: ast.Expression, into_type: ValueType) -> bool:
        """
        Turn the node into an instance of the desired FPrime type
        """
        return False

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

    cmd_json_dict_loader = CmdJsonLoader(dictionary)
    (cmd_id_dict, cmd_name_dict, versions) = cmd_json_dict_loader.construct_dicts(
        dictionary
    )
    type_name_dict = cmd_json_dict_loader.parsed_types
    ch_json_dict_loader = ChJsonLoader(dictionary)
    (ch_id_dict, ch_name_dict, versions) = ch_json_dict_loader.construct_dicts(
        dictionary
    )
    name_resolver = ResolveNames(cmd_name_dict, type_name_dict, ch_name_dict)
    node = name_resolver.visit(node)

    print(ast.dump(node, indent=4))
    if not check_for_errors(node):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
