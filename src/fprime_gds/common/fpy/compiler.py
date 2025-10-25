from pathlib import Path
from fprime.common.models.serialize.time_type import TimeType
from fprime.common.models.serialize.bool_type import BoolType
from fprime.common.models.serialize.enum_type import EnumType
from fprime.common.models.serialize.serializable_type import (
    SerializableType as StructType,
)
from fprime.common.models.serialize.array_type import ArrayType
from fprime.common.models.serialize.numerical_types import (
    U32Type,
    U16Type,
    U8Type,
    NumericalType
)
from fprime.common.models.serialize.type_base import BaseType as FppValue
from lark import Lark
from fprime_gds.common.fpy.bytecode.directives import Directive
from fprime_gds.common.fpy.codegen import (
    FinalChecks,
    GenerateCode,
    IrPass,
    ResolveLabels,
)
from fprime_gds.common.fpy.desuraging import DesugarForLoops
from fprime_gds.common.fpy.semantics import (
    AllocateVariables,
    AssignIds,
    AssignLocalScopes,
    CalculateConstExprValues,
    CheckBreakAndContinueInLoop,
    CheckConstArrayAccesses,
    CheckUseBeforeDeclare,
    CheckUseBeforeDeclareForLoopVariables,
    CreateVariables,
    PickTypesAndResolveAttrsAndItems,
    ResolveVarsAndTypes,
    SetEnclosingLoops,
)
from fprime_gds.common.fpy.syntax import AstScopedBody, FpyTransformer
from fprime_gds.common.fpy.types import (
    MACROS,
    MAX_DIRECTIVES_COUNT,
    SPECIFIC_NUMERIC_TYPES,
    CompileState,
    FppType,
    FpyCallable,
    FpyCast,
    FpyCmd,
    FpyTypeCtor,
    Visitor,
    create_scope,
)
from fprime_gds.common.loaders.ch_json_loader import ChJsonLoader
from fprime_gds.common.loaders.cmd_json_loader import CmdJsonLoader
from fprime_gds.common.loaders.event_json_loader import EventJsonLoader
from fprime_gds.common.loaders.prm_json_loader import PrmJsonLoader
from fprime_gds.common.templates.cmd_template import CmdTemplate
from pathlib import Path
from lark import Lark, LarkError
from lark.indenter import PythonIndenter

from fprime_gds.common.fpy.error import BackendError, CompileError, handle_lark_error
import fprime_gds.common.fpy.error

fpy_grammar_str = (Path(__file__).parent / "grammar.lark").read_text()


def text_to_ast(text: str):
    parser = Lark(
        fpy_grammar_str,
        start="input",
        parser="lalr",
        postlex=PythonIndenter(),
        propagate_positions=True,
        maybe_placeholders=True,
    )

    fprime_gds.common.fpy.error.input_text = text
    fprime_gds.common.fpy.error.input_lines = text.splitlines()
    try:
        tree = parser.parse(text, on_error=handle_lark_error)
    except LarkError as e:
        handle_lark_error(e)
    transformed = FpyTransformer().transform(tree)
    return transformed


def get_base_compile_state(dictionary: str) -> CompileState:
    """return the initial state of the compiler, based on the given dict path"""
    cmd_json_dict_loader = CmdJsonLoader(dictionary)
    (cmd_id_dict, cmd_name_dict, versions) = cmd_json_dict_loader.construct_dicts(
        dictionary
    )

    ch_json_dict_loader = ChJsonLoader(dictionary)
    (ch_id_dict, ch_name_dict, versions) = ch_json_dict_loader.construct_dicts(
        dictionary
    )
    prm_json_dict_loader = PrmJsonLoader(dictionary)
    (prm_id_dict, prm_name_dict, versions) = prm_json_dict_loader.construct_dicts(
        dictionary
    )
    event_json_dict_loader = EventJsonLoader(dictionary)
    (event_id_dict, event_name_dict, versions) = event_json_dict_loader.construct_dicts(
        dictionary
    )
    # the type name dict is a mapping of a fully qualified name to an fprime type
    # here we put into it all types found while parsing all cmds, params and tlm channels
    type_name_dict: dict[str, FppType] = cmd_json_dict_loader.parsed_types
    type_name_dict.update(ch_json_dict_loader.parsed_types)
    type_name_dict.update(prm_json_dict_loader.parsed_types)
    type_name_dict.update(event_json_dict_loader.parsed_types)

    # enum const dict is a dict of fully qualified enum const name (like Ref.Choice.ONE) to its fprime value
    enum_const_name_dict: dict[str, FppValue] = {}

    # find each enum type, and put each of its values in the enum const dict
    for name, typ in type_name_dict.items():
        if issubclass(typ, EnumType):
            for enum_const_name, val in typ.ENUM_DICT.items():
                enum_const_name_dict[name + "." + enum_const_name] = typ(
                    enum_const_name
                )

    # insert the implicit types into the dict
    type_name_dict["Fw.Time"] = TimeType
    for typ in SPECIFIC_NUMERIC_TYPES:
        type_name_dict[typ.get_canonical_name()] = typ
    type_name_dict["bool"] = BoolType
    # note no string type at the moment

    cmd_response_type = type_name_dict["Fw.CmdResponse"]
    callable_name_dict: dict[str, FpyCallable] = {}
    # add all cmds to the callable dict
    for name, cmd in cmd_name_dict.items():
        cmd: CmdTemplate
        args = []
        for arg_name, _, arg_type in cmd.arguments:
            args.append((arg_name, arg_type))
        # cmds are thought of as callables with a Fw.CmdResponse return value
        callable_name_dict[name] = FpyCmd(cmd_response_type, args, cmd)

    # add numeric type casts to callable dict
    for typ in SPECIFIC_NUMERIC_TYPES:
        callable_name_dict[typ.get_canonical_name()] = FpyCast(typ, [("value", NumericalType)], typ)

    # for each type in the dict, if it has a constructor, create an FpyTypeCtor
    # object to track the constructor and put it in the callable name dict
    for name, typ in type_name_dict.items():
        args = []
        if issubclass(typ, StructType):
            for arg_name, arg_type, _, _ in typ.MEMBER_LIST:
                args.append((arg_name, arg_type))
        elif issubclass(typ, ArrayType):
            for i in range(0, typ.LENGTH):
                args.append(("e" + str(i), typ.MEMBER_TYPE))
        elif issubclass(typ, TimeType):
            args.append(("time_base", U16Type))
            args.append(("time_context", U8Type))
            args.append(("seconds", U32Type))
            args.append(("useconds", U32Type))
        else:
            # bool, enum, string or numeric type
            # none of these have callable ctors
            continue

        callable_name_dict[name] = FpyTypeCtor(typ, args, typ)

    # for each macro function, add it to the callable dict
    for macro_name, macro in MACROS.items():
        callable_name_dict[macro_name] = macro

    state = CompileState(
        tlms=create_scope(ch_name_dict),
        prms=create_scope(prm_name_dict),
        types=create_scope(type_name_dict),
        callables=create_scope(callable_name_dict),
        consts=create_scope(enum_const_name_dict),
    )
    return state


def ast_to_directives(
    body: AstScopedBody, dictionary: str
) -> list[Directive] | CompileError | BackendError:
    state = get_base_compile_state(dictionary)
    state.root = body
    semantics_passes: list[Visitor] = [
        # assign each node a unique id for indexing/hashing
        AssignIds(),
        # based on position of node in tree, figure out which scope it is in
        AssignLocalScopes(),
        # based on assignment syntax nodes, we know which variables exist where
        CreateVariables(),
        # check that break/continue are in loops, and store which loop they're in
        CheckBreakAndContinueInLoop(),
        # now that variables have been defined, we can resolve all "single word"
        # nodes in the tree, to either some namespace or a var probs
        # also, because types have a restricted set of possible syntax, resolve them
        # before we resolve other things. this means we can also figure out the type of variables
        # at this stage
        ResolveVarsAndTypes(),
        # make sure we don't use any variables before they are declared
        CheckUseBeforeDeclare(),
        CheckUseBeforeDeclareForLoopVariables(),
        # this pass resolves all attributes and items, as well as determines the type of expressions
        PickTypesAndResolveAttrsAndItems(),
        # now that expr types have been narrowed down, we can allocate lvar space for variables
        AllocateVariables(),
        # okay, now that we're sure we're passing in all the right args to each func,
        # we can calculate values of type ctors etc etc
        CalculateConstExprValues(),
        CheckConstArrayAccesses(),
    ]
    desugaring_passes: list[Visitor] = [
        # now that semantic analysis is done, we can desugar things. start with for loops
        DesugarForLoops(),
    ]
    code_generator = GenerateCode()
    ir_passes: list[IrPass] = [
        ResolveLabels(),
        FinalChecks()
    ]

    for compile_pass in semantics_passes:
        compile_pass.run(body, state)
        if len(state.errors) != 0:
            return state.errors[0]
    for compile_pass in desugaring_passes:
        compile_pass.run(body, state)
        if len(state.errors) != 0:
            return state.errors[0]
    ir = code_generator.emit(body, state)
    for compile_pass in ir_passes:
        ir = compile_pass.run(ir, state)
        if isinstance(ir, BackendError):
            # early return errors
            return ir

    # all the ir is guaranteed to have been converted to directives by now
    return ir
