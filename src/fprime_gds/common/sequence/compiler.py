import inspect
import ast
from pathlib import Path
from argparse import ArgumentParser
from dictionary_ac import *
from builtin_ac import *

def validate_func_call(obj_name, fn_name, args):

    valid = False

    if obj_name is None:
        # it is a builtin
        valid = validate_builtin(fn_name, args)
    else:
        # it is a command to a component
        valid = validate_command(obj_name, fn_name, args)
    
    if not valid:
        print("Invalid function call", obj_name, fn_name, args)
        return False

    print("Valid function call", obj_name, fn_name, args)
    return True

def validate_builtin(fn_name, args):
    for builtin in builtins:
        if builtin.__name__ == fn_name:
            # there is a builtin with this name
            return validate_builtin_args(builtin, args)
    # there is no builtin with this name
    return False

def validate_builtin_args(builtin, args):
    signature = inspect.signature(builtin)

    if len(args) != len(signature.parameters):
        print(f"{builtin.__name__} expects {len(signature.parameters)} args but {len(args)} args were given")
        return False

    return True

def validate_command(component_name, cmd_name, args):
    for instance in instances:
        if instance.name == component_name:
            instance_cmds = inspect.getmembers(instance)
            for instance_cmd in instance_cmds:
                if instance_cmd[0] == cmd_name:
                    return validate_command_args(instance_cmd[1], args)
    return False

def validate_command_args(cmd_fn, args):
    signature = inspect.signature(cmd_fn)

    if len(args) != len(signature.parameters):
        print(f"Command {cmd_fn.__name__} expects {len(signature.parameters)} args but {len(args)} args were given")
        return False

    return True


class NodeVisitor(ast.NodeVisitor):
    def generic_visit(self, node):
        super().generic_visit(node)

    def visit_Call(self, node: ast.Call):
        obj_name = None
        fn_name = None
        args = node.args

        if isinstance(node.func, ast.Attribute):
            # call to an attr of an obj
            if isinstance(node.func.value, ast.Name):
                obj_name = node.func.value.id
            fn_name = node.func.attr
        elif isinstance(node.func, ast.Name):
            # direct call, not on obj
            fn_name = node.func.id

        validate_func_call(obj_name, fn_name, args)

def main():
    arg_parser = ArgumentParser(description="A compiler for the FPrime advanced sequencing language")

    arg_parser.add_argument("input", type=Path, help="The path of the input sequence to compile")

    args = arg_parser.parse_args()

    input_text = args.input.read_text()

    node = ast.parse(input_text)

    NodeVisitor().generic_visit(node)

if __name__ == "__main__":
    main()