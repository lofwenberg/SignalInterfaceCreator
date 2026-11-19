"""
File: software_component.py
Description: Parse software-component configuration and function definitions.
Author: Richard Löfwenberg
Created: 2026-11-19
"""
import json
import string
from pathlib import Path
from datetime import datetime

from signal_interface_helpers import InternalSignal


class SoftwareComponent:
    def __init__(self, swc_path: Path):

        self.swc_path = swc_path
        # Find json swc file
        path = Path(f"{swc_path}/software_component.json")
        if not path.exists():
            raise FileNotFoundError(f"Software component not found: {path.resolve()}")

        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        # Verify only one top level item
        if len(data) == 0:
            raise ValueError("No software component data found")
        if len(data) > 1:
            raise ValueError("Software component configuration file can only contain one top level item")

        # Special handling to get first key from dict
        self.name = next(iter(data.keys()))
        self.software_component_dict = data[self.name]

        # Handle input Signals
        if "input_signals" not in self.software_component_dict:
            raise ValueError(f"Expecting a 'input_signals' object for {self.name}")

        self.input_signals = InternalSignal.parse_signals(self.software_component_dict["input_signals"])

        # Handle output Signals
        if "output_signals" not in self.software_component_dict:
            raise ValueError(f"Expecting a 'output_signals' object for {self.name}")

        self.output_signals = InternalSignal.parse_signals(self.software_component_dict["output_signals"])

        # Handle inits
        if "inits" not in self.software_component_dict:
            raise ValueError(f"Expecting a 'inits' object for {self.name}")

        self.inits = self.software_component_dict["inits"]

        # Handle periodicals
        if "periodicals" not in self.software_component_dict:
            raise ValueError(f"Expecting a 'periodicals' object for {self.name}")

        self.periodicals = []

        for i, periodical in enumerate(self.software_component_dict["periodicals"]):
            if "name" not in periodical:
                raise ValueError(f"Expecting name entry for periodical number {i + 1} in {self.name}")
            periodical_name = periodical["name"]

            if "period" not in periodical:
                raise ValueError(f"Expecting a 'period' entry for {periodical_name} in {self.name}")

            period = periodical["period"]

            if not isinstance(period, int) or period < 1:
                raise ValueError(f"Expecting positive integer for period entry for {periodical_name} in {self.name}")

            self.periodicals.append((periodical_name, period))

    def generate_interface_files(self, remove_stubs: bool = False):
        # Only generate stubs if path doesn't exist or remove stubs is specified
        if not self.swc_path.joinpath(f"{self.name}.c").exists() or remove_stubs:
            with open(f"c_templates/SWC_TEMPLATE.c") as f:
                c_file = string.Template(f.read())

            with open(f"c_templates/SWC_TEMPLATE.h") as f:
                h_file = string.Template(f.read())

            swc_functions_list = []
            swc_functions_names_list = []

            for init_func in self.inits:
                swc_functions_names_list.append(f"\tvoid {init_func}();")
                swc_functions_list.append(f"void {init_func}()\n{{\n\n}}\n")

            for periodical, period in self.periodicals:
                swc_functions_names_list.append(f"\tvoid {periodical}();")
                swc_functions_list.append(f"void {periodical}()\n{{\n\n}}\n")

            swc_functions = "\n".join(swc_functions_list)
            swc_functions_names = "\n".join(swc_functions_names_list)

            file_text = c_file.substitute(CREATION_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                          SWC_NAME=self.name,
                                          SWC_NAME_H=self.name + ".h",
                                          SWC_FUNCTIONS=swc_functions)

            # Using flag "w" makes sure file is overwritten each time
            with open(self.swc_path.joinpath(f"{self.name}.c"), "w") as f:
                f.write(file_text)

            file_text = h_file.substitute(CREATION_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                          SWC_NAME=self.name,
                                          SWC_NAME_H=self.name.upper() + "_H",
                                          SWC_FUNCTIONS=swc_functions_names)

            # Using flag "w" makes sure file is overwritten each time
            with open(self.swc_path.joinpath(f"{self.name}.h"), "w") as f:
                f.write(file_text)

        with open(f"c_templates/SWC_SI_TEMPLATE.h") as f:
            si_h_file = string.Template(f.read())

        swc_si_function_names_list = []

        for signal in self.input_signals.values():
            swc_si_function_names_list.append(f"\t{signal.type} SI_{signal.name}_Read(void);")

        for signal in self.output_signals.values():
            swc_si_function_names_list.append(f"\tvoid SI_{signal.name}_Write({signal.type} value);")

        swc_si_function_names = "\n".join(swc_si_function_names_list)

        file_text = si_h_file.substitute(CREATION_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                         SWC_NAME="SI_" + self.name,
                                         SWC_NAME_H="SI_" + self.name.upper() + "_H",
                                         SWC_FUNCTIONS=swc_si_function_names)

        # Using flag "w" makes sure file is overwritten each time
        with open(self.swc_path.joinpath(f"SI_{self.name}.h"), "w") as f:
            f.write(file_text)

    @classmethod
    def generate_swc_interface(cls, swc_path: str):
        swc = cls(Path(swc_path))
        swc.generate_interface_files()

if __name__ == "__main__":
    SoftwareComponent.generate_swc_interface(r"D:\CanReaderProject\TestFolder")