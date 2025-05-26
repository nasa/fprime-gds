from dataclasses import dataclass

from fprime_gds.common.fpy.types import StatementData, StatementTemplate
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.prm_template import PrmTemplate
from fprime_gds.common.fpy.parser import Expr, If, Assign, Call, Name, Var, Attr
from fprime.common.models.serialize.type_base import BaseType


@dataclass
class NamedType:
    name: str
    type: type[BaseType]


@dataclass
class Variable:
    name: str
    type: NamedType


@dataclass
class Namespace:
    name: str
    tlms: list[ChTemplate]
    prms: list[PrmTemplate]
    stmts: list[StatementTemplate]
    types: list[NamedType]
    vars: list[Variable]
    children: list["Namespace"]


FppNamedObject = (
    ChTemplate | PrmTemplate | StatementTemplate | Variable | Namespace | NamedType
)


@dataclass
class CompileState:
    top: Namespace


def compile_body(body: list, context: CompileState) -> None:
    for node in body:
        if not isinstance(node, (Expr, If, Assign)):
            node.error = "Syntax error compile body"
            return None


def compile_expr(expr: ast.Expr, context: CompileState) -> list[StatementData] | None:
    if not isinstance(expr.value, ast.Call):
        expr.error = "Syntax error compile expr"
        return None

    return compile_call(expr.value, context)


def compile_call(call: ast.Call, context: CompileState) -> list[StatementData] | None:
    func_obj = resolve_named_object(call.func, context.top)
    if func_obj is None:
        return None

    # calls can be instantiations of types, or cmd calls, or directives
    # or (later) functions
    if not isinstance(func_obj, (StatementTemplate, NamedType)):
        call.error = "Syntax error compile call"
        return None

    # get the list of args
    args: list[FpyArgTemplate] = []
    if isinstance(node.func, FpyStmt):
        args = node.func.template.args
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


def resolve_named_object(obj, ns: Namespace) -> FppNamedObject | None:
    if isinstance(obj, ast.Name):
        resolved = resolve_name(obj.id, ns)
    elif isinstance(obj, ast.Attribute):
        resolved = resolve_attr(obj, ns)
    else:
        obj.error = "Syntax error resolve named object"
        return None

    return resolved


def resolve_attr(attr: ast.Attribute, ns: Namespace) -> FppNamedObject | None:
    parent_obj = resolve_named_object(attr.value, ns)

    # for now, only support children of namespaces
    # in future, support accessing tlm member fields
    if isinstance(parent_obj, Namespace):
        return resolve_name(attr.attr, parent_obj)

    attr.error = "Syntax error resolve attr"
    return None


def resolve_name(name: str, ns: Namespace) -> FppNamedObject | None:
    matching = []
    for sub_ns in ns.children:
        if sub_ns.name == name:
            matching.append(sub_ns)
    for tlm in ns.tlms:
        if tlm.name == name:
            matching.append(tlm)
    for stmt in ns.stmts:
        if stmt.name == name:
            matching.append(stmt)
    for prm in ns.prms:
        if prm.prm_name == name:
            matching.append(prm)
    for var in ns.vars:
        if var.name == name:
            matching.append(var)
    for typ in ns.types:
        if typ.name == name:
            matching.append(typ)

    if len(matching) == 0:
        name.error = "Unknown name " + str(name)
        return None
    if len(matching) > 1:
        # TODO better err msg
        name.error = "Ambiguous name " + str(name)
        return None
    return matching[0]
