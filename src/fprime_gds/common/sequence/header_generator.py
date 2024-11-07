from argparse import ArgumentParser
import os
from pathlib import Path
import sys
import shutil

from fprime_gds.common.loaders.ch_json_loader import ChJsonLoader
from fprime_gds.common.loaders.cmd_json_loader import CmdJsonLoader
from fprime.common.models.serialize.type_base import BaseType

prompted_removal = False


def prompt_removal(path: Path):
    global prompted_removal
    if not prompted_removal:
        while True:
            allow_removal = input(
                str(path.resolve())
                + " already exists. Allow overwriting existing dirs and files? [Y/n] "
            )
            if allow_removal.lower() in ["n", "no"]:
                # can't remove a dir we need to remove
                exit(1)
            if allow_removal.lower() in ["", "Y", "yes"]:
                break
            else:
                print("Unknown option")
                continue
    prompted_removal = True
    # only way out of the above loop is accepting it

    if path.is_dir():
        shutil.rmtree(str(path.resolve()))
    else:
        path.unlink()


# this function is a hack because we don't get explicit module hierarchy info in the json dict
def get_module_hierarchy(
    cmd_names: list[str], type_names: list[str], ch_names: list[str]
) -> dict:

    component_names = []
    # get list of components that have cmds and tlm chans
    for name in list(cmd_names) + list(ch_names):
        parent_component = name.split(".")[:-1]
        if parent_component not in component_names:
            component_names.append(parent_component)

    modules = {}

    def add_namespace_to_dict(name):

        d = modules

        for mod in name:
            if mod not in d:
                d[mod] = {}
            d = d[mod]

    for name in list(cmd_names) + list(ch_names):
        # add the namespace of the component that contains these chs and cmds
        add_namespace_to_dict(name.split(".")[:-2])
    
    for type_name in type_names:
        enclosing_name = type_name.split(".")[:-1]
        # type_name could either be a module, or a component
        if enclosing_name in component_names:
            print("type " + type_name + " is in a component")
            # if it's a component, add the next higher level to the module names
            add_namespace_to_dict(enclosing_name[:-1])
        else:
            # we think it might be a module (still could be a component with no cmds or tlm that has a type declared inside of it)
            print("type " + type_name + " is NOT in a component")
            add_namespace_to_dict(enclosing_name)


    # get unique names
    return modules


def generate_stubs(dictionary: Path, output_dir: Path) -> str:
    cmd_json_dict_loader = CmdJsonLoader(dictionary)
    (cmd_id_dict, cmd_name_dict, versions) = cmd_json_dict_loader.construct_dicts(
        dictionary
    )
    type_name_dict = cmd_json_dict_loader.parsed_types

    ch_json_dict_loader = ChJsonLoader(dictionary)
    (ch_id_dict, ch_name_dict, versions) = ch_json_dict_loader.construct_dicts(
        dictionary
    )

    modules = get_module_hierarchy(
        cmd_name_dict.keys(), type_name_dict.keys(), ch_name_dict.keys()
    )

    def generate_module_folders(module, submodules):
        # if not the root module
        if module is not None:
            module_folder: Path = output_dir / module
            if module_folder.exists():
                prompt_removal(module_folder)
            module_folder.mkdir(parents=True)
            (module_folder / "__init__.py").touch()

        for submodule in submodules:
            generate_module_folders(submodule, submodules[submodule])

    generate_module_folders(None, modules)

    generate_types(type_name_dict)

    # okay, now generate folders for each module
    # first generate all types
    # then generate all components
    # then generate all component instances


def generate_types(type_name_dict: dict[str, type[BaseType]]) -> str:
    ac_type_str = ""
    # for type_name, type_class in type_name_dict.items():
    #     ac_type_str += generate_type(type_name, type_class)


def main():
    arg_parser = ArgumentParser(
        description="A tool to generate Python stubs for IDE autocompletion for the FPrime advanced sequencing language"
    )

    arg_parser.add_argument(
        "dictionary",
        type=Path,
        help="The JSON topology dictionary to generate Python stubs for",
    )
    arg_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="The output directory for the stubs",
        default=Path(os.getcwd()),
    )
    arg_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="If present, don't prompt to overwrite existing stubs",
    )

    args = arg_parser.parse_args()

    if args.force:
        global prompted_removal
        prompted_removal = True

    generate_stubs(args.dictionary, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
