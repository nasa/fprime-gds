from __future__ import annotations
from pathlib import Path
from fprime_gds.common.models.serialize.time_type import TimeType as TimeValue
from fprime_gds.common.models.serialize.bool_type import BoolType as BoolValue
from fprime_gds.common.models.serialize.enum_type import EnumType as EnumValue
from fprime_gds.common.models.serialize.serializable_type import (
    SerializableType as StructValue,
)
from fprime_gds.common.models.serialize.array_type import ArrayType as ArrayValue
from fprime_gds.common.models.serialize.numerical_types import (
    U8Type as U8Value,
    U16Type as U16Value,
    U32Type as U32Value,
    NumericalType as NumericalValue,
)
from fprime_gds.common.models.serialize.type_base import BaseType as FppValue
from lark import Lark
from fprime_gds.common.fpy.bytecode.directives import Directive
from fprime_gds.common.fpy.codegen import (
    GenerateCode,
)
from fprime_gds.common.fpy.ir import FinalChecks, IrPass, ResolveLabels
from fprime_gds.common.fpy.desugaring import DesugarForLoops
from fprime_gds.common.fpy.semantics import (
    AssignIds,
    AssignLocalScopes,
    CalculateConstExprValues,
    CheckBreakAndContinueInLoop,
    CheckConstArrayAccesses,
    CheckUseBeforeDeclare,
    CheckUseBeforeDeclareForLoopVariables,
    CreateVariables,
    PickTypesAndResolveAttrsAndItems,
    ResolveVarsTypesAndFuncs,
    WarnRangesAreNotEmpty,
)
from fprime_gds.common.fpy.syntax import AstScopedBody, FpyTransformer, PythonIndenter
from fprime_gds.common.fpy.macros import MACROS
from fprime_gds.common.fpy.types import (
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
        return None
    transformed = FpyTransformer().transform(tree)
    return transformed


def get_base_compile_state(dictionary: str, compile_args: dict) -> CompileState:
    """return the initial state of the compiler, based on the given dict path"""
    cmd_json_dict_loader = CmdJsonLoader(dictionary)
    (_, cmd_name_dict, _) = cmd_json_dict_loader.construct_dicts(
        dictionary
    )

    ch_json_dict_loader = ChJsonLoader(dictionary)
    (_, ch_name_dict, _) = ch_json_dict_loader.construct_dicts(
        dictionary
    )
    prm_json_dict_loader = PrmJsonLoader(dictionary)
    (_, prm_name_dict, _) = prm_json_dict_loader.construct_dicts(
        dictionary
    )
    event_json_dict_loader = EventJsonLoader(dictionary)
    (_, _, _) = event_json_dict_loader.construct_dicts(
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
        if issubclass(typ, EnumValue):
            for enum_const_name, val in typ.ENUM_DICT.items():
                enum_const_name_dict[name + "." + enum_const_name] = typ(
                    enum_const_name
                )

    # insert the builtin types into the dict
    type_name_dict["Fw.Time"] = TimeValue
    for typ in SPECIFIC_NUMERIC_TYPES:
        type_name_dict[typ.get_canonical_name()] = typ
    type_name_dict["bool"] = BoolValue
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
        callable_name_dict[name] = FpyCmd(
            cmd.get_full_name(), cmd_response_type, args, cmd
        )

    # add numeric type casts to callable dict
    for typ in SPECIFIC_NUMERIC_TYPES:
        callable_name_dict[typ.get_canonical_name()] = FpyCast(
            typ.get_canonical_name(), typ, [("value", NumericalValue)], typ
        )

    # for each type in the dict, if it has a constructor, create an FpyTypeCtor
    # object to track the constructor and put it in the callable name dict
    for name, typ in type_name_dict.items():
        args = []
        if issubclass(typ, StructValue):
            for arg_name, arg_type, _, _ in typ.MEMBER_LIST:
                args.append((arg_name, arg_type))
        elif issubclass(typ, ArrayValue):
            for i in range(0, typ.LENGTH):
                args.append(("e" + str(i), typ.MEMBER_TYPE))
        elif issubclass(typ, TimeValue):
            args.append(("time_base", U16Value))
            args.append(("time_context", U8Value))
            args.append(("seconds", U32Value))
            args.append(("useconds", U32Value))
        else:
            # bool, enum, string or numeric type
            # none of these have callable ctors
            continue

        callable_name_dict[name] = FpyTypeCtor(name, typ, args, typ)

    # for each macro function, add it to the callable dict
    for macro_name, macro in MACROS.items():
        callable_name_dict[macro_name] = macro

    state = CompileState(
        tlms=create_scope(ch_name_dict),
        prms=create_scope(prm_name_dict),
        types=create_scope(type_name_dict),
        callables=create_scope(callable_name_dict),
        consts=create_scope(enum_const_name_dict),
        compile_args=compile_args or dict(),
    )
    return state


def ast_to_directives(
    body: AstScopedBody,
    dictionary: str,
    compile_args: dict | None = None,
) -> list[Directive] | CompileError | BackendError:
    compile_args = compile_args or dict()
    state = get_base_compile_state(dictionary, compile_args)
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
        ResolveVarsTypesAndFuncs(),
        # make sure we don't use any variables before they are declared
        CheckUseBeforeDeclare(),
        CheckUseBeforeDeclareForLoopVariables(),
        # this pass resolves all attributes and items, as well as determines the type of expressions
        PickTypesAndResolveAttrsAndItems(),
        # okay, now that we're sure we're passing in all the right args to each func,
        # we can calculate values of type ctors etc etc
        CalculateConstExprValues(),
        CheckConstArrayAccesses(),
        WarnRangesAreNotEmpty()
    ]
    desugaring_passes: list[Visitor] = [
        # now that semantic analysis is done, we can desugar things. start with for loops
        DesugarForLoops(),
    ]
    code_generator = GenerateCode()
    ir_passes: list[IrPass] = [ResolveLabels(), FinalChecks()]

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

    # print out warnings
    for warning in state.warnings:
        print(warning)

    # all the ir is guaranteed to have been converted to directives by now
    return ir
