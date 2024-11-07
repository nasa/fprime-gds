import numbers
from dataclasses import dataclass
import inspect
import ast
from pathlib import Path
from argparse import ArgumentParser
import sys
import logging
import datetime
import zlib

from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.executables.data_product_writer import IntegerType
from fprime_gds.common.models.common.command import Descriptor
from fprime_gds.common.utils.data_desc_type import DataDescType

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
from fprime_gds.common.sequence.fpy_type import (
    FpyArg,
    FpySeqDirective,
    FpyArgTemplate,
    FpyCh,
    FpyCmd,
    FpyEnumConstant,
    FpyType,
    FpyCall,
)
from fprime_gds.common.sequence.directive import (
    SeqDirectiveId,
    SeqDirectiveTemplate,
    seq_directive_name_dict,
)


class ResolveNames(ast.NodeTransformer):

    def __init__(
        self,
        cmd_name_dict: dict[str, CmdTemplate],
        type_name_dict: dict[str, type[BaseType]],
        ch_name_dict: dict[str, ChTemplate],
        seq_directive_name_dict: dict[str, SeqDirectiveTemplate],
    ) -> None:
        super().__init__()
        self.cmd_name_dict = cmd_name_dict
        self.type_name_dict = type_name_dict
        self.ch_name_dict = ch_name_dict
        self.seq_directive_name_dict = seq_directive_name_dict

    def visit_Module(self, node: ast.Module):
        if len(node.body) == 0:
            # no statements in sequence file
            node.error = "Sequence files cannot be empty"
        for statement in node.body:
            statement: ast.stmt
            if not isinstance(statement, ast.Expr) or not isinstance(
                statement.value, ast.Call
            ):
                statement.error = "Sequences can only contain commands"
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

        # now look up this namespace string. resolve enum consts, then types, then telemetry, then seq directives, then commands
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

        resolved_seq_directive = self.seq_directive_name_dict.get(fq_name, None)
        if resolved_seq_directive is not None:
            return FpySeqDirective(namespace, name, resolved_seq_directive)

        resolved_fprime_cmd = self.cmd_name_dict.get(fq_name, None)
        if resolved_fprime_cmd is not None:
            return FpyCmd(namespace, name, resolved_fprime_cmd)

        node.error = "Unknown identifier " + str(fq_name)
        return node


class CheckCalls(ast.NodeTransformer):

    def __init__(self, type_name_dict: dict[str, type[BaseType]]):
        self.type_name_dict = type_name_dict

    def visit_Call(self, node: ast.Call):

        # only valid calls right now are commands, seq directives and type instantiations
        if not isinstance(node.func, (FpyCmd, FpySeqDirective, FpyType)):
            node.error = "Invalid syntax"
            return node

        # get the list of args
        args: list[FpyArgTemplate] = []
        if isinstance(node.func, FpyCmd):
            args = node.func.cmd_template.arguments
        elif isinstance(node.func, FpySeqDirective):
            args = node.func.seq_directive_template.args
        elif isinstance(node.func, FpyType):
            # it's an FpyType
            if not self.check_has_ctor(node.func.fprime_type):
                node.error = (
                    "Type "
                    + str(node.func.fprime_type.__name__)
                    + " cannot be directly constructed"
                )
                return node
            args = self.get_args_list_from_fprime_type_ctor(node.func.fprime_type)
        else:
            assert False, node.func

        # okay, now map the args to the nodes
        mapped_args = self.map_args(args, node)

        if hasattr(node, "error"):
            # if something went wrong, don't traverse the tree
            return node

        # okay, now type check the args
        for arg in mapped_args:
            # this func will add an error if it finds one
            if not self.check_node_converts_to_fprime_type(arg.node, arg.type):
                # don't traverse the tree if we fail
                return node

        fpy_call = FpyCall(node.func, mapped_args)

        return super().generic_visit(fpy_call)

    def check_has_ctor(self, type: type[BaseType]) -> bool:
        # only serializables (i.e. structs), time objects and arrays can be directly constructed in fpy syntax. enums and literals cannot
        return issubclass(type, (SerializableType, ArrayType, TimeType))

    def get_args_list_from_fprime_type_ctor(
        self, type: type[BaseType]
    ) -> list[FpyArgTemplate]:
        args = []
        if issubclass(type, SerializableType):
            for member in type.MEMBER_LIST:
                (member_name, member_type, member_format_str, member_desc) = member
                args.append(FpyArgTemplate((member_name, member_desc, member_type)))
        elif issubclass(type, ArrayType):
            for i in range(type.LENGTH):
                args.append(FpyArgTemplate(("e" + str(i), "", type.MEMBER_TYPE)))
        elif issubclass(type, TimeType):
            args.append(
                (
                    "time_base",
                    "Time base index for the time tag. Must be a valid integer for a TimeBase Enum value.",
                    I32Type,
                )
            )
            args.append(("time_context", "Time context for the time tag", I32Type))
            args.append(
                ("seconds", "Seconds elapsed since specified time base", I32Type)
            )
            args.append(
                (
                    "useconds",
                    "Microseconds since start of current second. Must be in range [0, 999999] inclusive",
                    I32Type,
                )
            )
        else:
            raise RuntimeError(
                "FPrime type " + str(type.__name__) + " has no constructor"
            )
        return args

    def map_args(self, args: list[FpyArgTemplate], node: ast.Call) -> list[FpyArg]:
        """
        Maps arguments from a list of arg templates to an ast node by position and name. Does not perform type checking.
        """

        mapping = []

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
                        node.error = "Multiple values for " + str(arg_name)
                        continue

                arg_node = arg_node[0]

            mapping.append(FpyArg(arg_name, arg_type, arg_node))

        return mapping

    def check_node_converts_to_fprime_type(
        self, node: ast.AST, fprime_type: type[BaseType]
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
                    "Expected a boolean literal, found '" + str(type(node.value)) + "'",
                )
                return False
        elif issubclass(fprime_type, (F64Type, F32Type)):
            if not isinstance(node, ast.Constant):
                error(node, "Invalid syntax")
                return False
            if not isinstance(node.value, float):
                error(
                    node,
                    "Expected a floating point literal, found '"
                    + str(type(node.value))
                    + "'",
                )
                return False
        elif issubclass(
            fprime_type,
            (I64Type, U64Type, I32Type, U32Type, I16Type, U16Type, I8Type, U8Type),
        ):
            if not isinstance(node, ast.Constant):
                error(node, "Invalid syntax")
                return False
            if not isinstance(node.value, int):
                error(
                    node,
                    "Expected an integer literal, found '"
                    + str(type(node.value))
                    + "'",
                )
                return False
        elif issubclass(fprime_type, StringType):
            if not isinstance(node, ast.Constant):
                error(node, "Invalid syntax")
                return False
            if not isinstance(node.value, str):
                error(
                    node,
                    "Expected a string literal, found '" + str(type(node.value)) + "'",
                )
                return False
        elif issubclass(fprime_type, EnumType):
            if not isinstance(node, FpyEnumConstant):
                if isinstance(node, ast.Constant):
                    error(
                        node,
                        "Expecting a value from "
                        + str(fprime_type.__name__)
                        + ", found '"
                        + str(type(node.value).__name__)
                        + "'",
                    )
                else:
                    error(node, "Expecting a value from " + str(fprime_type.__name__))
                return False
            if fprime_type != node.enum_type:
                error(
                    node,
                    "Expecting a value from "
                    + str(fprime_type.__name__)
                    + ", found a value from "
                    + str(node.enum_type.__name__),
                )
                return False
        elif issubclass(fprime_type, (ArrayType, SerializableType, TimeType)):
            if not isinstance(node, ast.Call):
                # must be a ctor call
                if isinstance(node, ast.Constant):
                    error(
                        node,
                        "Expecting a value of type "
                        + str(fprime_type.__name__)
                        + ", found '"
                        + str(type(node.value).__name__)
                        + "'",
                    )
                else:
                    error(
                        node, "Expecting a value of type " + str(fprime_type.__name__)
                    )

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
        else:
            if isinstance(node, ast.Constant):
                error(
                    node,
                    "Can't convert '"
                    + str(type(node.value).__name__)
                    + "' to "
                    + str(fprime_type),
                )
            else:
                error(node, "Can't convert argument to " + str(fprime_type))
            return False

        return True


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
            except BaseException as e:
                arg.node.error = (
                    "Error while constructing argument " + str(arg.name) + ": " + str(e)
                )

        elif issubclass(fprime_type, EnumType):
            assert isinstance(node, FpyEnumConstant)
            try:
                type_instance.val = node.const_name
            except BaseException as e:
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
                except BaseException as e:
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
                except BaseException as e:
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
                except BaseException as e:
                    arg.node.error = (
                        "Error while constructing argument "
                        + str(arg.name)
                        + ": "
                        + str(e)
                    )
        else:
            assert False, fprime_type
        return type_instance


class AddTimestamps(ast.NodeVisitor):
    def __init__(self):

        self.next_command_has_time = False
        """Whether or not the next command coming up will have a specific runtime"""
        self.next_wait_absolute_time: TimeType | None = None
        """The absolute time to wait for before the next command"""
        self.next_wait_relative_time: TimeType | None = None
        """The relative time to wait before the next command"""

    def visit_Module(self, node: ast.Module):
        for statement in node.body:
            # just make sure our checks above worked
            assert (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, FpyCall)
                and isinstance(statement.value.func, (FpyCmd, FpySeqDirective))
            )
            func = statement.value.func
            # okay, is this a sleep seq dir?
            if isinstance(func, FpySeqDirective) and func.seq_directive_template.id in [
                SeqDirectiveId.SLEEP_ABS,
                SeqDirectiveId.SLEEP_REL,
            ]:
                if self.next_command_has_time:
                    # the next command already has a time. can't specify two sleeps or more next to each other
                    # this is just a temporary limitation due to not using a new bytecode
                    statement.error = (
                        "Can only have one sleep directive before running a command"
                    )
                    return

                # get the first arg of the directive
                time = statement.value.get_arg(func.seq_directive_template.args[0][0])

                if func.seq_directive_template == SeqDirectiveId.SLEEP_ABS:
                    self.next_wait_absolute_time = time
                else:
                    self.next_wait_relative_time = time

                self.next_command_has_time = True
            elif isinstance(func, FpyCmd):
                # do we have a time waiting to be applied to this cmd?
                if not self.next_command_has_time:
                    # no, give it a relative time of 0
                    func.is_time_relative = True
                    # TB_DONT_CARE
                    func.time = TimeType(0xFFFF, 0, 0, 0)
                else:
                    # has a time
                    if self.next_wait_absolute_time is not None:
                        func.time = self.next_wait_absolute_time
                        func.is_time_relative = False
                    elif self.next_wait_relative_time is not None:
                        func.time = self.next_wait_relative_time
                        func.is_time_relative = True

                    # reset internal state
                    self.next_wait_absolute_time = None
                    self.next_wait_relative_time = None
                    self.next_command_has_time = False


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


def cmd_to_bytes(cmd: FpyCmd, args: list[FpyArg]) -> bytes:

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
            and isinstance(statement.value.func, (FpySeqDirective, FpyCmd))
        )
        if isinstance(statement.value.func, FpySeqDirective):
            assert statement.value.func.seq_directive_template.id in [
                SeqDirectiveId.SLEEP_ABS,
                SeqDirectiveId.SLEEP_REL,
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
    arg_parser.add_argument("-o", "--output", type=Path, help="The output .bin file path. Defaults to the input file path", default=None)

    args = arg_parser.parse_args()

    input_text = args.input.read_text()

    node = ast.parse(input_text)

    output_bytes = compile(node, args.dictionary)
    output_path: Path = args.output
    if output_path is None:
        output_path = args.input.with_suffix(".bin")
    
    output_path.write_bytes(output_bytes)


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
