"""
File: signal_interface_helpers.py
Description: Define signal types and parse signal configuration data.
Author: Richard Löfwenberg
Created: 2026-11-19
"""

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
                return "int8_t"
            else:
                return "uint8_t"
        elif self.size <= 16:
            if self.signed:
                return "int16_t"
            else:
                return "uint16_t"
        else:
            if self.signed:
                return "int32_t"
            else:
                return "uint32_t"


class IOSignal:
    def __init__(self, signal_name: str, connection: str, is_input: bool, pullup: bool, default_value: bool):
        self.name = signal_name
        self.connection = connection
        self.is_input = is_input
        self.pullup = pullup
        self.default_value = default_value
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

            if "default" not in signal_dict:
                raise ValueError(f"Expecting default value for IO signal {signal_name}")

            default_value = signal_dict["default"]

            if not isinstance(default_value, bool):
                raise ValueError(f"Expecting boolean value for default value entry in IO signal {signal_name}")

            signal = cls(signal_name, pin_connection, is_input, pullup, default_value)

            signals[signal_name] = signal

        return signals


class InternalSignal:
    def __init__(self, signal_name: str, signal_type: str, default_value):
        self.name = signal_name
        self.type = signal_type
        self.default_value = default_value

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

            if "default" not in signal_dict:
                # If not default value found, set 0
                default_value = 0
            else:
                default_value = signal_dict["default"]

            signal = cls(signal_name, signal_type, default_value)

            signals[signal_name] = signal

        return signals
