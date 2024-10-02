import ast
from pathlib import Path
from argparse import ArgumentParser

commands = {
    "fswExec": ["SET_MODE"]
}



def visit(node: ast.Node):


def main():
    arg_parser = ArgumentParser(description="A compiler for the FPrime advanced sequencing language")

    arg_parser.add_argument("input", type=Path, help="The path of the input sequence to compile")

    args = arg_parser.parse_args()

    input_text = args.input.read_text()

    node = ast.parse(input_text)


    print(ast.dump(node, indent=4))

if __name__ == "__main__":
    main()