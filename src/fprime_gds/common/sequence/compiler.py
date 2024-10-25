import ast
from dataclasses import dataclass
from pathlib import Path
from argparse import ArgumentParser

from fprime_gds.common.loaders.cmd_json_loader import CmdJsonLoader

commands = {
    "fswExec": ["SET_MODE"]
}

@dataclass
class CommandCall:
    comp_instance: str
    comp_cmd: str
    comp_args: list[ast.Expression]

class Visitor(ast.NodeTransformer):
    def generic_visit(self, node):
        return ast.NodeTransformer.generic_visit(self, node)
    
    def visit_Call(self, node):
        


def main():
    arg_parser = ArgumentParser(description="A compiler for the FPrime advanced sequencing language")

    arg_parser.add_argument("input", type=Path, help="The path of the input sequence to compile")

    arg_parser.add_argument("-d", "--dictionary", type=Path, help="The path to the JSON topology dictionary")

    args = arg_parser.parse_args()

    input_text = args.input.read_text()

    tree = ast.parse(input_text)

    visitor = Visitor()

    print(ast.dump(visitor.visit(tree), indent=4))

    # Check the user environment:
    cmd_json_dict = CmdJsonLoader(args.dictionary)

    (cmd_id_dict, cmd_name_dict, versions) = cmd_json_dict.construct_dicts(
        args.dictionary
    )

if __name__ == "__main__":
    main()