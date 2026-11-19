"""
File: software_component.py
Description: Parse software-component configuration and function definitions.
Author: Richard Löfwenberg
Created: 2026-11-19
"""

class SoftwareComponent:
    def __init__(self, swc_name: str,  swc_dict: dict):
        self.name = swc_name
        self.software_component_dict = swc_dict

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

    @classmethod
    def parse_swcs(cls, si_path: str, json_swc_list: list[str]) -> dict[str, SoftwareComponent]:
        swcs = {}

        for swc_name in json_swc_list:
            # Find SWC
            path = Path(f"{si_path}/{swc_name}/software_component.json")
            if not path.exists():
                raise FileNotFoundError(f"Software component not found: {path.resolve()}")

            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)

            swc_dict = next(iter(data.values()))
            swc = cls(swc_name, swc_dict)
            swcs[swc_name] = swc

        return swcs