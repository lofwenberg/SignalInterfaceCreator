import argparse
from pathlib import Path

from signal_interface_handler import SignalInterface
from software_component import SoftwareComponent

def generate(args: argparse.Namespace):
    # Validate path
    if not Path.is_dir(args.path):
        raise ValueError("path must be a directory")

    if args.swc is not None:
        # Generate software components
        swc_list = args.swc.split(",")
        swc_instance_list = []
        for swc_name in swc_list:
            # Remove whitespace
            swc_name = swc_name.strip()
            swc_path = Path(swc_name) / swc_name
            # Create software component instance. Will fail if path does not exist
            swc = SoftwareComponent(swc_path)
            swc_instance_list.append(swc)

        """ Generate files in a second loop, this is to make sure all paths and parsing goes through
        before we start generating files or doing changes in existing files """
        for swc in swc_instance_list:
            swc.generate_interface_files()

    else:
        # Generate entire signal interface
        signal_interface = SignalInterface(args.path)
        signal_interface.generate_templates()

def generate_swc(args: argparse.Namespace):
    swc = SoftwareComponent(Path(args.path))
    swc.generate_interface_files()

def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    # Generate
    generate_parser = commands.add_parser(
        "generate", aliases=["g"],
        help="Generate c-code"
    )
    generate_parser.add_argument(
        "path",
        help="Directory of source code"
    )
    generate_parser.add_argument(
        "--swc",
        help="Software components to generate, comma separated",
    )

    # Generate SWC
    generate_swc_parser = commands.add_parser(
        "generateSwc", aliases=["gS"],
        help="Generate c-code for software component"
    )
    generate_swc_parser.add_argument(
        "path",
        help="Directory of source code"
    )

    # Parse
    args = parser.parse_args()
    try:
        if args.command == "generate":
            generate(args)
        elif args.command == "generateSwc":
            generate_swc(args)
        else:
            parser.error(f"Invalid command specified: {args.command}")
    except Exception as error:
        parser.error(f"{error.__class__.__name__}: {str(error)}")


if __name__ == "__main__":
    main()