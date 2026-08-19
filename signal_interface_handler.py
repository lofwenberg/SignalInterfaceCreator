import json
import os.path
import shutil
import string

from datetime import datetime
from pathlib import Path
from dbcreader import Database

class SignalInterface:
    can_database = None

    def __init__(self, si_path: str, dbc_file: str):
        self.dbc_file = dbc_file
        self.ecu_name = ""
        self.software_interface_dict = None
        self.signals = dict()
        self.software_components = dict()

        path = Path(f"{si_path}/software_interface.json")
        if not path.exists():
            raise FileNotFoundError(f"JSON file not found: {path.resolve()}")

        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        # Start doing validation
        if len(data) != 1:
            raise ValueError("Expecting exactly 1 ECU-object.")

        self.ecu_name = next(iter(data.keys()))
        self.software_interface_dict = data[self.ecu_name]

        # Handle CAN-database
        self.can_database = Database(self.dbc_file)

        for can_signal in self.can_database.signals.values():
            # Only do signals sent or received by this ECU
            if self.ecu_name == can_signal.message.transmitter.name:
                signal = CanSignal(can_signal, False)
                self.signals[signal.name] = signal
            elif self.ecu_name in can_signal.receivers:
                signal = CanSignal(can_signal, True)
                self.signals[signal.name] = signal

        # Handle IO Signals
        if "io_signals" not in self.software_interface_dict:
            raise ValueError(f"Expecting a 'io_signals' object for {self.ecu_name}")

        io_signals = IOSignal.parse_signals(self.software_interface_dict["io_signals"])

        # Handle duplicates
        for signal_name, signal in io_signals.items():
            if signal_name in self.signals:
                raise ValueError(f"Duplicate entry for signal {signal_name}")

            self.signals[signal_name] = signal

        # Handle internal signals
        if "internal_signals" not in self.software_interface_dict:
            raise ValueError(f"Expecting a 'internal_signals' object for {self.ecu_name}")

        internal_signals = InternalSignal.parse_signals(self.software_interface_dict["internal_signals"])

        # Handle duplicates
        for signal_name, signal in internal_signals.items():
            if signal_name in self.signals:
                raise ValueError(f"Duplicate entry for signal {signal_name}")

            self.signals[signal_name] = signal

        # Handle software components
        if "software_components" not in self.software_interface_dict:
            raise ValueError(f"Expecting a 'software_components' object for {self.ecu_name}")

        swcs = SoftwareComponent.parse_swcs(si_path, self.software_interface_dict["software_components"])

        # Validate signals in SWCs
        for swc_name, swc in swcs.items():
            for signal_name in swc.input_signals:
                if signal_name in self.signals:
                    # Signal found, check for direction
                    if type(self.signals[signal_name]) != InternalSignal and not self.signals[signal_name].is_input:
                        raise ValueError(
                            f"Input signal {signal_name} is defined as input in software component {swc_name} but is defined as output in {self.ecu_name}")
                    if self.signals[signal_name].type != swc.input_signals[signal_name].type:
                        raise ValueError(f"Input signal {signal_name} is not same type in software component {swc_name} and {self.ecu_name}")
                else:
                    raise ValueError(f"Input signal {signal_name} defined in software component {swc_name} is missing in {self.ecu_name}")


            for signal_name in swc.output_signals:
                if signal_name in self.signals:
                    # Signal found, check for direction
                    if type(self.signals[signal_name]) != InternalSignal and self.signals[signal_name].is_input:
                        raise ValueError(
                            f"Output signal {signal_name} is defined as output in software component {swc_name} but is defined as input in {self.ecu_name}")
                    if self.signals[signal_name].type != swc.output_signals[signal_name].type:
                        raise ValueError(f"Output signal {signal_name} is not same type in software component {swc_name} and {self.ecu_name}")
                else:
                    raise ValueError(f"Output signal {signal_name} defined in software component {swc_name} is missing in {self.ecu_name}")

    def generate_templates(self):
        # Start by clearing out output
        if os.path.isdir("output"):
            # Remove dir, easiest way to clean
            shutil.rmtree("output")

        # Recreate dir
        os.mkdir("output")

        # Generate files
        self._generate_static_files()
        self._generate_can_handler()

    @staticmethod
    def _generate_static_files():
        files = ["main.c",
                 "canHandler.c",
                 "canHandler.h",
                 "initBoard.c",
                 "initBoard.h"]

        for file in files:
            with open(f"c_templates/{file}") as f:
                file_text = string.Template(f.read())

            file_text = file_text.substitute(CREATION_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            with open(f"output/{file}", "w") as f:
                f.write(file_text)




class Signal:
    pass


class CanSignal:
    def __init__(self, database_signal, is_input: bool):
        self.name = database_signal.name
        self.size = database_signal.size
        self.signed = database_signal.signed
        self.transmitter = database_signal.message.transmitter
        self.receivers = database_signal.receivers
        self.database_signal = database_signal
        self.is_input = is_input
        self.is_consumed = False

    @property
    def type(self):
        if self.size == 1:
            return "bool"
        elif self.size <= 8:
            if self.signed:
                return "int_8"
            else:
                return "uint_8"
        elif self.size <= 16:
            if self.signed:
                return "int_16"
            else:
                return "uint_16"
        else:
            if self.signed:
                return "int_32"
            else:
                return "uint_32"


class IOSignal:
    def __init__(self, signal_name: str, connection: str, is_input: bool, pullup: bool):
        self.name = signal_name
        self.connection = connection
        self.is_input = is_input
        self.pullup = pullup
        self.type = "bool"

    @classmethod
    def parse_signals(cls, json_signal_list: list[dict]) -> dict[str,IOSignal]:
        signals = {}
        for i, signal_dict in enumerate(json_signal_list):
            if "name" not in signal_dict:
                raise ValueError(f"Expecting name entry for IO signal number {i + 1}")

            signal_name = signal_dict["name"]

            if signal_name in signals:
                raise ValueError(f"Duplicate entry for IO signal {signal_name}")

            if "input" not in signal_dict:
                raise ValueError(f"Expecting input entry for IO signal {signal_name}")

            is_input = signal_dict["input"]

            if not isinstance(is_input, bool):
                raise ValueError(f"Expecting boolean value for input entry in IO signal {signal_name}")

            if "connection" not in signal_dict:
                raise ValueError(f"Expecting connection entry for IO signal {signal_name}")

            pin_connection = signal_dict["connection"]

            if "pullup" not in signal_dict:
                raise ValueError(f"Expecting pullup entry for IO signal {signal_name}")

            pullup = signal_dict["pullup"]

            if not isinstance(pullup, bool):
                raise ValueError(f"Expecting boolean value for pullup entry in IO signal {signal_name}")

            signal = cls(signal_name, pin_connection, is_input, pullup)

            signals[signal_name] = signal

        return signals


class InternalSignal:
    def __init__(self, signal_name: str, signal_type: str):
        self.name = signal_name
        self.type = signal_type

    @classmethod
    def parse_signals(cls, json_signal_list: list[dict]) -> dict[str, InternalSignal]:
        signals = {}
        for i, signal_dict in enumerate(json_signal_list):
            if "name" not in signal_dict:
                raise ValueError(f"Expecting name entry for {cls.__name__} number {i + 1}")

            signal_name = signal_dict["name"]

            if signal_name in signals:
                raise ValueError(f"Duplicate entry for {cls.__name__} {signal_name}")

            if "type" not in signal_dict:
                raise ValueError(f"Expecting type entry for {cls.__name__} {signal_name}")

            signal_type = signal_dict["type"]

            signal = cls(signal_name, signal_type)

            signals[signal_name] = signal

        return signals


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

if __name__ == "__main__":
    signal_interface = SignalInterface(r"../AuxiliaryLightsModule/", r"../database.dbc")
    signal_interface.generate_templates()