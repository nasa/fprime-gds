import ast
from pathlib import Path
from argparse import ArgumentParser
import sys
import logging
import zlib

from fprime_gds.common.fpy.types import StatementTemplate
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.models.common.command import Descriptor
from fprime_gds.common.templates.prm_template import PrmTemplate
from fprime_gds.common.utils.data_desc_type import DataDescType
from fprime.common.models.serialize.type_exceptions import (
    StringSizeException,
    TypeMismatchException,
    EnumMismatchException,
    TypeRangeException,
    ArrayLengthException,
    IncorrectMembersException,
    MissingMemberException,
)

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
from fprime.common.models.serialize.type_base import BaseType, BaseType, ValueType
from fprime.common.models.serialize.time_type import TimeType
from fprime_gds.common.fpy.fpy_type import (
    FpyArg,
    FpyArgTemplate,
    FpyCh,
    FpyEnumConstant,
    FpyStmt,
    FpyType,
    FpyCall,
)


class ResolveNames(ast.NodeTransformer):

    def __init__(
        self,
        type_name_dict: dict[str, type[BaseType]],
        ch_name_dict: dict[str, ChTemplate],
        prm_name_dict: dict[str, PrmTemplate],
        stmt_name_dict: dict[str, StatementTemplate],
    ) -> None:
        super().__init__()
        self.type_name_dict = type_name_dict
        self.ch_name_dict = ch_name_dict
        self.prm_name_dict = prm_name_dict
        self.stmt_name_dict = stmt_name_dict

    def visit_Module(self, node: ast.Module):
        # for statement in node.body:
        #     statement: ast.stmt
        #     if not isinstance(statement, ast.Expr) or not isinstance(
        #         statement.value, ast.Call
        #     ):
        #         statement.error = "Sequences can only contain commands"
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
        return self.resolve_name(node, namespace_str, node.attr)

    def visit_Name(self, node: ast.Name):
        return self.resolve_name(node, "", node.id)

    def resolve_name(self, node, namespace: str, name: str) -> ast.AST:
        fq_name = name
        if namespace != "":
            fq_name = namespace + "." + fq_name

        # now look up this namespace string. resolve enum consts, then types, then telemetry, then prms, then statements
        resolved_fprime_enum_type = self.type_name_dict.get(namespace, None)
        if resolved_fprime_enum_type is not None:
            if not issubclass(resolved_fprime_enum_type, EnumType):
                node.error = "Invalid syntax"
                return node

            enum_const_name = name
            if enum_const_name not in resolved_fprime_enum_type.ENUM_DICT:
                node.error = "Unknown enum constant '" + str(enum_const_name) + "'"
                return node

            # this is a python integer
            enum_value_py = resolved_fprime_enum_type.ENUM_DICT[enum_const_name]
            # this is a string
            enum_repr_type_name = resolved_fprime_enum_type.REP_TYPE
            # this is a subclass of BaseType
            enum_repr_type = REPRESENTATION_TYPE_MAP.get(enum_repr_type_name, None)
            assert enum_repr_type is not None

            return FpyEnumConstant(
                resolved_fprime_enum_type,
                enum_repr_type,
                enum_const_name,
                enum_value_py,
            )

        resolved_fprime_type = self.type_name_dict.get(fq_name, None)
        if resolved_fprime_type is not None:
            return FpyType(namespace, name, resolved_fprime_type)

        resolved_fprime_ch = self.ch_name_dict.get(fq_name, None)
        if resolved_fprime_ch is not None:
            return FpyCh(namespace, name, resolved_fprime_ch)

        resolved_fprime_prm = self.prm_name_dict.get(fq_name, None)
        if resolved_fprime_prm is not None:
            return FpyCh(namespace, name, resolved_fprime_prm)

        resolved_stmt = self.stmt_name_dict.get(fq_name, None)
        if resolved_stmt is not None:
            return FpyStmt(namespace, name, resolved_stmt)

        node.error = "Unknown identifier " + str(fq_name)
        return node


class CheckCalls(ast.NodeTransformer):

    def __init__(self, type_name_dict: dict[str, type[BaseType]]):
        self.type_name_dict = type_name_dict

    def visit_Call(self, node: ast.Call):
        pass



class ConstructFpyTypes(ast.NodeVisitor):
    """
    Turn all FpyTypes/FpyEnumConstants/constants argument of each command into an instance of a subclass of BaseType
    """

    def visit_FpyCall(self, node: FpyCall):
        super().generic_visit(node)
        # okay, all args to args should be collapsed into a BaseType

        # now do that for the args
        for arg in node.args:
            instantiated_type = self.construct_arg_type(arg)
            arg.type_instance = instantiated_type

    def construct_arg_type(self, arg: FpyArg) -> BaseType:
        # type checking has already happened in a previous step. we'll do a minimum of checking ourselves
        fprime_type = arg.type
        node = arg.node

        type_instance = None
        if issubclass(fprime_type, ValueType):
            type_instance = fprime_type()

        # if it should be a constant
        if issubclass(
            fprime_type,
            (
                BoolType,
                F32Type,
                F64Type,
                U16Type,
                U32Type,
                U64Type,
                U8Type,
                I16Type,
                I32Type,
                I64Type,
                I8Type,
                StringType,
            ),
        ):

            # make sure the value is a constant
            assert isinstance(node, ast.Constant)

            # make sure the constant's type matches
            if issubclass(fprime_type, BoolType):
                assert isinstance(node.value, bool)
            elif issubclass(fprime_type, (F64Type, F32Type)):
                assert isinstance(node.value, float)
            elif issubclass(
                fprime_type,
                (I64Type, U64Type, I32Type, U32Type, I16Type, U16Type, I8Type, U8Type),
            ):
                assert isinstance(node.value, int)
            elif issubclass(fprime_type, StringType):
                assert isinstance(node.value, str)

            try:
                type_instance._val = node.value
            except (
                StringSizeException,
                TypeMismatchException,
                TypeMismatchException,
            ) as e:
                arg.node.error = (
                    "Error while constructing argument " + str(arg.name) + ": " + str(e)
                )

        elif issubclass(fprime_type, EnumType):
            assert isinstance(node, FpyEnumConstant)
            try:
                type_instance.val = node.const_name
            except (TypeMismatchException, EnumMismatchException) as e:
                arg.node.error = (
                    "Error while constructing argument " + str(arg.name) + ": " + str(e)
                )
        elif issubclass(fprime_type, (ArrayType, SerializableType, TimeType)):
            # should be a ctor call
            assert (
                isinstance(node, FpyCall)
                and isinstance(node.func, FpyType)
                and node.func.fprime_type == fprime_type
            )
            if issubclass(fprime_type, SerializableType):
                try:
                    type_instance.val = {a.name: a.type_instance.val for a in node.args}
                except (
                    IncorrectMembersException,
                    MissingMemberException,
                    TypeMismatchException,
                ) as e:
                    arg.node.error = (
                        "Error while constructing argument "
                        + str(arg.name)
                        + ": "
                        + str(e)
                    )
            elif issubclass(fprime_type, ArrayType):
                val = []
                for a in node.args:
                    val.append(a.type_instance.val)
                try:
                    type_instance.val = val
                except (TypeMismatchException, ArrayLengthException) as e:
                    arg.node.error = (
                        "Error while constructing argument "
                        + str(arg.name)
                        + ": "
                        + str(e)
                    )
            elif issubclass(fprime_type, TimeType):
                assert len(node.args) == 4
                try:
                    type_instance = TimeType(*[a.type_instance.val for a in node.args])
                except TypeRangeException as e:
                    arg.node.error = (
                        "Error while constructing argument "
                        + str(arg.name)
                        + ": "
                        + str(e)
                    )
        else:
            assert False, fprime_type
        return type_instance



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


def cmd_to_bytes(cmd: FpyStmt, args: list[FpyArg]) -> bytes:

    # command format is descriptor + time + command length + command packet descriptor + command opcode + command args

    # the "descriptor" is just whether this is abs or rel
    descriptor = Descriptor.RELATIVE if cmd.is_time_relative else Descriptor.ABSOLUTE
    # subtract one because this enum starts at 1
    descriptor = U8Type(descriptor.value - 1).serialize()
    time = (
        U32Type(cmd.time.seconds).serialize() + U32Type(cmd.time.useconds).serialize()
    )
    header = descriptor + time

    command = bytes()
    packet_descriptor_val = DataDescType["FW_PACKET_COMMAND"].value
    opcode_val = cmd.cmd_template.get_id()
    command += U32Type(packet_descriptor_val).serialize()
    command += U32Type(opcode_val).serialize()
    for arg in args:
        command += arg.type_instance.serialize()

    length = U32Type(len(command)).serialize()

    return header + length + command


def module_to_bytes(node: ast.Module):
    output_bytes = bytes()
    num_cmds = 0
    for statement in node.body:
        # sorry another sanity check
        assert (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, FpyCall)
            and isinstance(statement.value.func, (FpyDirective, FpyCmd))
        )
        if isinstance(statement.value.func, FpyDirective):
            assert statement.value.func.seq_directive_template.id in [
                SeqDirectiveId.WAIT_ABS,
                SeqDirectiveId.WAIT_REL,
            ]
            # have already dealt with these by adding timestamps to cmds
            continue
        # okay, serialize the command
        output_bytes += cmd_to_bytes(statement.value.func, statement.value.args)
        num_cmds += 1

    size = len(output_bytes)
    tb_txt = "ANY"

    print(f"Sequence is {size} bytes with timebase {tb_txt}")

    header = b""
    header += U32Type(
        size + 4
    ).serialize()  # Write out size of the sequence file in bytes here
    header += U32Type(num_cmds).serialize()  # Write number of records
    header += U16Type(0xFFFF).serialize()  # Write time base
    header += U8Type(0xFF).serialize()  # write time context
    output_bytes = header + output_bytes  # Write the list of command records here
    # compute CRC. Ported from Utils/Hash/libcrc/libcrc.h (update_crc_32)
    crc = compute_crc(output_bytes)

    print("CRC: %d (0x%04X)" % (crc, crc))
    output_bytes += U32Type(crc).serialize()

    return output_bytes


def compute_crc(buff):
    # See http://stackoverflow.com/questions/30092226/how-to-calculate-crc32-with-python-to-match-online-results
    # RE: signed to unsigned CRC
    return zlib.crc32(buff) % (1 << 32)


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
    arg_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="The output .bin file path. Defaults to the input file path",
        default=None,
    )

    args = arg_parser.parse_args()

    input_text = args.input.read_text()

    node = ast.parse(input_text)
    print(ast.dump(node, indent=4))

    # output_bytes = compile(node, args.dictionary)
    # if output_bytes is None:
    #     return 1

    # output_path: Path = args.output
    # if output_path is None:
    #     output_path = args.input.with_suffix(".bin")

    # output_path.write_bytes(output_bytes)

    return 0


def compile(node: ast.Module, dictionary: Path) -> bytes:

    cmd_json_dict_loader = CmdJsonLoader(dictionary)
    (cmd_id_dict, cmd_name_dict, versions) = cmd_json_dict_loader.construct_dicts(
        dictionary
    )
    type_name_dict = cmd_json_dict_loader.parsed_types
    # insert the implicit TimeType into the dict
    type_name_dict["Time"] = TimeType

    ch_json_dict_loader = ChJsonLoader(dictionary)
    (ch_id_dict, ch_name_dict, versions) = ch_json_dict_loader.construct_dicts(
        dictionary
    )
    name_resolver = ResolveNames(
        cmd_name_dict, type_name_dict, ch_name_dict, seq_directive_name_dict
    )
    node = name_resolver.visit(node)

    if not check_for_errors(node):
        return None

    call_checker = CheckCalls(type_name_dict)
    node = call_checker.visit(node)
    if not check_for_errors(node):
        return None

    type_constructor = ConstructFpyTypes()
    type_constructor.visit(node)
    if not check_for_errors(node):
        return None

    timestamp_adder = AddTimestamps()
    timestamp_adder.visit(node)
    if not check_for_errors(node):
        return None

    output_bytes = module_to_bytes(node)

    return output_bytes


if __name__ == "__main__":
    sys.exit(main())
