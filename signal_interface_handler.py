import json
from os import name
from pathlib import Path

import dbcreader
from dbcreader import Database

# Default paths
DEFAULT_JSON_PATH = r"..\signal_interface.json"
DEFAULT_DBC_PATH = r"..\database.dbc"

class SignalInterface:
    can_database = None

    def __init__(self, json_path: str = DEFAULT_JSON_PATH, dbc_path: str = DEFAULT_DBC_PATH):
        self.dbc_path = dbc_path
        self.ecu_name = ""
        self.signal_interface_dict = None
        self.signals = dict()
        self.runnables = dict()

        self.parse_json(json_path)

    def parse_json(self, file_path: str):
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"JSON file not found: {path}")

        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        # Start doing validation
        if len(data) != 1:
            raise ValueError("Expecting exactly 1 ECU-object.")

        self.ecu_name = next(iter(data.keys()))
        self.signal_interface_dict = data[self.ecu_name]

        # Handle signals
        if "signals" not in self.signal_interface_dict:
            raise ValueError(f"Expecting a 'signals' object for {self.ecu_name}")

        self._read_signals(self.signal_interface_dict["signals"])

        if len(self.signals) < 2:
            raise ValueError(f"Expecting at least 1 signal for {self.ecu_name}")

        # Handle runnables
        if "runnables" not in self.signal_interface_dict:
            raise ValueError(f"Expecting a 'runnables' object for {self.ecu_name}")

        self._parse_runnables(self.signal_interface_dict["runnables"])

    def _read_signals(self, signal_list: list[dict]):
        for i, signal_dict in enumerate(signal_list):
            if "name" not in signal_dict:
                raise ValueError(f"Expecting name entry for signal number {i}")
            signal_name = signal_dict["name"]

            if signal_name in self.signals:
                raise ValueError(f"Duplicate entry for signal {signal_name}")

            if "size" not in signal_dict:
                raise ValueError(f"Expecting size entry for signal {signal_name}")

            signal_size = signal_dict["size"]

            if not isinstance(signal_size, int) or signal_size < 1:
                raise ValueError(f"Expecting positive integer for signal size for signal {signal_name}. Got {signal_size}")

            if signal_size > 1:
                if "signed" not in signal_dict:
                    raise ValueError(f"Expecting signed entry for signal {signal_name}")

                signed = signal_dict["signed"]

                if not isinstance(signed, bool):
                    raise ValueError(f"Expecting boolean value for signed entry in signal {signal_name}")
            else:
                signed = True

            if "connection" not in signal_dict or signal_dict["connection"] is None:
                # Assume internal signal
                self.signals[signal_name] = InternalSignal(signal_name, signal_size, signed)
            else:
                if "input" not in signal_dict:
                    raise ValueError(f"Expecting input entry for signal {signal_name}")

                is_input = signal_dict["input"]

                if not isinstance(is_input, bool):
                    raise ValueError(f"Expecting boolean value for input entry in signal {signal_name}")

                if signal_dict["connection"] == "CAN":
                    # Only load can database when needed
                    if self.can_database is None:
                        self.can_database = Database(self.dbc_path)

                    self.signals[signal_name] = CanSignal(signal_name, signal_size, signed, is_input, self.can_database)

                else:
                    pin_connection = signal_dict["connection"]

                    if "pullup" not in signal_dict:
                        raise ValueError(f"Expecting pullup entry for signal {signal_name}")

                    pullup = signal_dict["pullup"]

                    if not isinstance(pullup, bool):
                        raise ValueError("Expecting boolean value for pullup entry in signal {signal_name}")

                    self.signals[signal_name] = IOSignal(signal_name, signal_size, signed, pin_connection, is_input, pullup)

    def _parse_runnables(self, runnable_list: list[dict]):
        for i, runnable_dict in enumerate(runnable_list):
            if "name" not in runnable_dict:
                raise ValueError(f"Expecting name entry for runnable number {i}")
            runnable_name = runnable_dict["name"]

            if "period" not in runnable_dict:
                raise ValueError(f"Expecting period entry for runnable {runnable_name}")

            period = runnable_dict["period"]

            if not isinstance(period, int) or period < 1:
                raise ValueError(f"Expecting positive integer for period entry for runnable {runnable_name}")

            if "inputs" not in runnable_dict:
                raise ValueError(f"Expecting input_signal entry for runnable {runnable_name}")

            input_signals = list()
            for signal in runnable_dict["inputs"]:
                if signal not in self.signals:
                    raise ValueError(f"Input signal {signal} in runnable {runnable_name} not defined on toplevel")

                if signal in input_signals:
                    raise ValueError(f"Duplicate entry for input signal {signal} in runnable {runnable_name}")

                input_signals.append(self.signals[signal])

            if "outputs" not in runnable_dict:
                raise ValueError(f"Expecting output_signals entry for runnable {runnable_name}")

            output_signals = list()
            for signal in runnable_dict["outputs"]:

                if signal in input_signals:
                    raise ValueError(f"Signal {signal} in runnable {runnable_name} defined both as input and output")

                if signal in output_signals:
                    raise ValueError(f"Duplicate entry for output signal {signal} in runnable {runnable_name}")

                output_signals.append(self.signals[signal])

            self.runnables[runnable_name] = Runnable(runnable_name, period, input_signals, output_signals)

class InternalSignal:
    def __init__(self, signal_name: str, size: int, signed: bool):
        self.Name = signal_name
        self.Size = size
        self.Signed = signed

class CanSignal:
    def __init__(self, signal_name: str, size: int, signed: bool, is_input: bool, can_database: Database):
        # Find signal
        if signal_name not in can_database.signals:
            raise ValueError(f"Expecting signal {signal_name} in CAN database")

        database_signal = can_database.signals[signal_name]

        # Validate CAN signal
        if database_signal.size != size:
            raise ValueError(f"Signal {signal_name} does not match for size between JSON and DBC")

        if database_signal.signed != signed:
            raise ValueError(f"Signal {signal_name} does not match for signal {signal_name}")

        self.Name = signal_name
        self.Size = size
        self.Signed = signed
        self.is_input = is_input
        self.database_signal = database_signal

class IOSignal:
    def __init__(self, signal_name, size, signed, connection, is_input, pullup):
        self.Name = signal_name
        self.Size = size
        self.Signed = signed
        self.Connection = connection
        self.Input = is_input
        self.Pullup = pullup

class Runnable:
    def __init__(self, runnable_name: str, period: int, input_signals: list, output_signals: list):
        self.name = runnable_name
        self.period = period
        self.input_signals = input_signals
        self.output_signals = output_signals