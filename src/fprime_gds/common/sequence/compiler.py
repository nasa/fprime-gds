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


FpyCmd._fields = ["namespace", "name", "cmd_template"]


@dataclass
class FpyCh(ast.AST):
    namespace: str
    name: str
    ch_template: ChTemplate


FpyCh._fields = ["namespace", "name", "ch_template"]


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

            enum_const_name = node.attr
            if enum_const_name not in resolved_fprime_enum_type.ENUM_DICT:
                node.error = "Unknown enum constant '" + str(enum_const_name) + "'"
                return node

            # this is a python integer
            enum_value_py = resolved_fprime_enum_type.ENUM_DICT[enum_const_name]
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


class CheckCalls(ast.NodeTransformer):

    def __init__(self, type_name_dict: dict[str, type[ValueType]]):
        self.type_name_dict = type_name_dict

    def visit_Call(self, node: ast.Call):

        # only valid calls right now are commands and dict type instantiations
        if not isinstance(node.func, (FpyCmd, FpyType)):
            node.error = "Invalid syntax"
            return node

        # get the list of args
        args: list[FpyArgTemplate] = []
        if isinstance(node.func, FpyCmd):
            args = node.func.cmd_template.arguments
        else:
            # it's an FpyType
            if not self.check_has_ctor(node.func.fprime_type):
                node.error = (
                    "Type "
                    + str(node.func.fprime_type.__name__)
                    + " cannot be directly constructed"
                )
                return node
            args = self.get_args_list_from_fprime_type_ctor(node.func.fprime_type)

        # okay, now map the args to the nodes
        mapped_args = self.map_args(args, node)

        # okay, now type check the args
        for arg_template, arg_node in mapped_args.items():
            # this func will add an error if it finds one
            if not self.check_node_converts_to_fprime_type(arg_node, arg_template[2]):
                # don't traverse the tree if we fail
                return node

        return super().generic_visit(node)

    def check_has_ctor(self, type: type[ValueType]) -> bool:
        # only serializables (i.e. structs) and arrays can be directly constructed in fpy syntax
        return issubclass(type, (SerializableType, ArrayType))

    def get_args_list_from_fprime_type_ctor(
        self, type: type[ValueType]
    ) -> list[FpyArgTemplate]:
        args = []
        if issubclass(type, SerializableType):
            for member in type.MEMBER_LIST:
                (member_name, member_type, member_format_str, member_desc) = member
                args.append(FpyArgTemplate((member_name, member_desc, member_type)))
        elif issubclass(type, ArrayType):
            for i in range(type.LENGTH):
                args.append(FpyArgTemplate(("e" + str(i), "", type.MEMBER_TYPE)))
        else:
            raise RuntimeError(
                "FPrime type " + str(type.__name__) + " has no constructor"
            )
        return args

    def map_args(
        self, args: list[FpyArgTemplate], node: ast.Call
    ) -> dict[FpyArgTemplate, ast.AST]:
        """
        Maps arguments from a list of arg templates to an ast node by position and name. Does not perform type checking.
        """

        mapping = dict()

        for idx, arg_template in enumerate(args):
            arg_name, arg_desc, arg_type = arg_template

            arg_node = None

            if idx < len(node.args):
                # if we're still in positional args
                arg_node = node.args[idx]
            else:
                # if we're in kwargs
                # find a matching node from keywords
                arg_node = [n.value for n in node.keywords if n.arg == arg_name]
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

    def check_node_converts_to_fprime_type(
        self, node: ast.AST, fprime_type: type[ValueType]
    ) -> bool:
        """
        Ensure the ast node can be turned into the desired FPrime type
        """

        def error(node, msg):
            node.error = msg

        if issubclass(fprime_type, BoolType):
            if not isinstance(node, ast.Constant):
                error(node, "Invalid syntax")
                return False
            if not isinstance(node.value, bool):
                error(
                    node,
                    "Expected a boolean literal, found " + str(type(node.value)),
                )
                return False
        elif issubclass(fprime_type, (F64Type, F32Type)):
            if not isinstance(node, ast.Constant):
                error(node, "Invalid syntax")
                return False
            if not isinstance(node.value, float):
                error(
                    node,
                    "Expected a floating point literal, found " + str(type(node.value)),
                )
                return False
        elif issubclass(
            fprime_type,
            (I64Type, U64Type, I32Type, U32Type, I16Type, U16Type, I8Type, U8Type),
        ):
            if not isinstance(node, ast.Constant):
                error(node, "Invalid syntax")
                return False
            if not isinstance(node.value, float):
                error(
                    node,
                    "Expected an integer literal, found " + str(type(node.value)),
                )
                return False
        elif issubclass(fprime_type, StringType):
            if not isinstance(node, ast.Constant):
                error(node, "Invalid syntax")
                return False
            if not isinstance(node.value, str):
                error(
                    node,
                    "Expected a string literal, found " + str(type(node.value)),
                )
                return False
        elif issubclass(fprime_type, EnumType):
            if not isinstance(node, FpyEnumConstant):
                if isinstance(node, ast.Constant):
                    error(node, "Expecting an enum constant, found '" + str(type(node.value).__name__) + "'")
                else:
                    error(node, "Invalid syntax")
                return False
            assert fprime_type == node.enum_type
        elif issubclass(fprime_type, (ArrayType, SerializableType)):
            if not isinstance(node, ast.Call):
                # must be a ctor call
                error(node, "Invalid syntax")
                return False
            if not isinstance(node.func, FpyType):
                # must be a ctor call
                error(node, "Invalid syntax")
                return False
            if fprime_type != node.func.fprime_type:
                error(
                    node,
                    "Expected "
                    + str(fprime_type.__name__)
                    + " but found "
                    + str(node.func.fprime_type.__name__),
                )
                return False

        return True


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
                        ret = visit(item)
                        if not ret:
                            return False
            elif isinstance(value, ast.AST):
                ret = visit(value)
                if not ret:
                    return False
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
    print("RESOLVING NAMES")
    name_resolver = ResolveNames(cmd_name_dict, type_name_dict, ch_name_dict)
    node = name_resolver.visit(node)

    print(ast.dump(node, indent=4))
    if not check_for_errors(node):
        return 1

    print("CHECKING CALLS")
    call_checker = CheckCalls(type_name_dict)
    node = call_checker.visit(node)

    print(ast.dump(node, indent=4))
    if not check_for_errors(node):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
