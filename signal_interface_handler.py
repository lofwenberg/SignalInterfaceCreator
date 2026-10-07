import json
import string
import dbcreader

from datetime import datetime
from math import ceil
from pathlib import Path

class SignalInterface:
    can_database = None

    def __init__(self, si_path: str, dbc_file: str):
        self.dbc_file = dbc_file
        self.ecu_name = ""
        self.software_interface_dict = None
        self.signals = dict()
        self.si_path = Path(si_path)

        # Check that SI path exists
        if not self.si_path.is_dir():
            raise FileNotFoundError(f"Signal Interface path {self.si_path} is not a directory")

        # Check that there is a software_interface file in the directory
        si_file = Path(f"{si_path}/software_interface.json")
        if not si_file.exists():
            raise FileNotFoundError(f"Software interface file not found: {si_file.resolve()}")

        with si_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        # Start doing validation
        if len(data) != 1:
            raise ValueError("Expecting exactly 1 ECU-object.")

        self.ecu_name = next(iter(data.keys()))
        self.software_interface_dict = data[self.ecu_name]

        # Handle CAN-database
        self.can_database = dbcreader.Database(self.dbc_file)

        self.can_transmit_enable = False

        for can_signal in self.can_database.signals.values():
            # Only do signals sent or received by this ECU
            if self.ecu_name == can_signal.message.transmitter.name:
                signal = CanSignal(can_signal, False)
                self.signals[signal.name] = signal
                self.can_transmit_enable = True
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

        self.software_components = SoftwareComponent.parse_swcs(si_path, self.software_interface_dict["software_components"])

        # Validate signals in SWCs
        for swc_name, swc in self.software_components.items():
            for signal_name in swc.input_signals:
                if signal_name in self.signals:
                    # Signal found, check for direction
                    if type(self.signals[signal_name]) != InternalSignal and not self.signals[signal_name].is_input:
                        raise ValueError(
                            f"Input signal {signal_name} is defined as input in software component {swc_name} but is defined as output in {self.ecu_name}")
                    if self.signals[signal_name].type != swc.input_signals[signal_name].type:
                        raise ValueError(f"Input signal {signal_name} is not same type in software component {swc_name} and {self.ecu_name}")
                    # Set can signal as consumed
                    if type(self.signals[signal_name]) == CanSignal:
                        self.signals[signal_name].is_consumed = True
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
                    # Set can signal as consumed
                    if type(self.signals[signal_name]) == CanSignal:
                        self.signals[signal_name].is_consumed = True
                else:
                    raise ValueError(f"Output signal {signal_name} defined in software component {swc_name} is missing in {self.ecu_name}")

    def generate_templates(self, remove_stubs: bool = False):
        # Generate files
        self._generate_static_files()
        self._generate_can_handler()
        self._generate_io_handler()
        self._generate_internal_signal_handler()
        self._generate_periodicals()
        self._generate_software_components(remove_stubs)
        self._generate_signal_definitions()

    def _generate_static_files(self):
        files = ["main.c",
                 "canHandler.c",
                 "canHandler.h",
                 "periodicals.h"]

        if self.can_transmit_enable:
            can_tx_enable = "\n#define CAN_TX\n"
        else:
            can_tx_enable = ""

        for file in files:
            with open(f"c_templates/{file}") as f:
                file_text = string.Template(f.read())

            file_text = file_text.substitute(CREATION_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), CAN_TX_ENABLED=can_tx_enable)

            # Using flag "w" makes sure file is overwritten each time
            with open(f"{self.si_path}/{file}", "w") as f:
                f.write(file_text)

    def _generate_can_handler(self):

        with open(f"c_templates/canMessageHandler_TEMPLATE.c") as f:
            c_file = string.Template(f.read())

        with open(f"c_templates/canMessageHandler_TEMPLATE.h") as f:
            h_file = string.Template(f.read())

        bitfield_list = []
        persistent_var_list = ["/* Persistent variable */"]
        message_init_list = []
        message_init_name_list = []
        message_run_list = []
        message_run_name_list = []
        signal_read_list = []
        signal_read_name_list = []
        signal_write_list = []
        signal_write_name_list = []
        message_definition_list = ["messageHandler_Entry canMessageHandler_messages[] = \n\t{"]

        can_messages = self.get_can_messages()

        for message in can_messages:
            # Check if message has a consumed signal
            for signal in message.signals.values():
                if self.signals[signal.name].is_consumed:
                    break
            else:
                # We only end up here if signal wasn't consumed, in that case, skip entire message
                continue
            # Prepare init function
            message_init_list.append(f"void canMessageHandler_{message.name}_init()\n{{")
            message_init_name_list.append(f"void canMessageHandler_{message.name}_init();")

            # Prepare run function
            if self.ecu_name in message.transmitter.name:
                is_send_message = True
            else:
                is_send_message = False

            message_run_list.append(f"void canMessageHandler_{message.name}_run(uint8_t payload[8])\n"
                                    "{\n"
                                    "\t// Cast payload array to struct pointer for direct access\n"
                                    f"\t{message.name}_t* info = ({message.name}_t*)payload;\n")
            message_run_name_list.append(f"void canMessageHandler_{message.name}_run(uint8_t payload[8]);")

            # Fill message definition list
            message_definition_list.append(f"\t{{{hex(message.id)},  canMessageHandler_{message.name}_init, canMessageHandler_{message.name}_run}},")

            # Prepare variables
            persistent_var_list.append(f"// {message.name}")

            # Handle bitfield
            bitfield_list.append("typedef struct {")
            # Get bit positions and sort in case it wasn't sorted
            bit_pos_list = list(message.signals.keys())
            bit_pos_list.sort()

            filler_counter = 0

            if bit_pos_list[0] != 0:
                # Special case for bitfield if first bits are not occupied
                next_bit = bit_pos_list[0]
                amount_of_bytes = ceil(next_bit / 8)
                remaining_bits = next_bit % 8

                for i in range(amount_of_bytes - 1):
                    bitfield_list.append(f"\tuint8_t UnknownSignal_{filler_counter} : 8;\t // bits {i*8}-{(i+1)*8}")
                    filler_counter += 1

                bitfield_list.append(f"\tuint8_t UnknownSignal_{filler_counter} : {remaining_bits};\t // bits {(amount_of_bytes - 1) * 8}-{next_bit - 1}")
                filler_counter += 1

            for bit_pos in bit_pos_list:
                # Handle bitfield
                signal = message.signals[bit_pos]
                if signal.size > 8:
                    amount_of_bytes = ceil(signal.size / 8)
                    remaining_bits = signal.size % 8

                    for i in range(amount_of_bytes - 1):
                        bitfield_list.append(f"\tuint8_t {signal.name + "_" + str(i)} : 8;\t // bits {bit_pos + i * 8}-{bit_pos + 7 + i * 8 }")

                    bitfield_list.append(
                        f"\tuint8_t {signal.name + "_" + str(amount_of_bytes - 1)} : {remaining_bits};\t // bits {bit_pos + (amount_of_bytes - 1) * 8}-{bit_pos + (amount_of_bytes - 1) * 8 + remaining_bits - 1}")
                else:
                    if signal.size > 1:
                        bitfield_list.append(f"\tuint8_t {signal.name} : {signal.size};\t // bits {bit_pos}-{bit_pos + signal.size - 1}")
                    else:
                        bitfield_list.append(f"\tuint8_t {signal.name} : 1;\t // bit {bit_pos}")

                # Check if signal is consumed, in that case, only generate bitfield
                if not self.signals[signal.name].is_consumed:
                    continue

                # Handle variables
                si_signal = self.signals[signal.name]
                persistent_var_list.append(f"{si_signal.type} {message.name}_{signal.name};")
                message_init_list.append(f"\t{message.name}_{signal.name} = {str(signal.init_value)};")

                if signal.size <= 8:
                    if is_send_message:
                        message_run_list.append(f"\tinfo->{signal.name} = (uint8_t){message.name}_{signal.name};")
                    else:
                        message_run_list.append(f"\t{message.name}_{signal.name} = info->{signal.name};")
                else:
                    amount_of_bytes = ceil(signal.size / 8)
                    if is_send_message:
                        message_run_list.append(f"\tinfo->{signal.name}_0 = (uint8_t)({message.name}_{signal.name} & 0xFF);")
                        for i in range(1, amount_of_bytes, 1):
                            message_run_list.append(f"\tinfo->{signal.name}_{i} = (uint8_t)(({message.name}_{signal.name} >> {i * 8}) & 0xFF);")
                    else:
                        text_row_list = [f"\t{message.name}_{signal.name} = ({si_signal.type})info->{signal.name}_0"]
                        for i in range(1, amount_of_bytes, 1):
                            text_row_list.append(f"({si_signal.type})(info->{signal.name}_0 << {i*8})")
                        message_run_list.append(" | ".join(text_row_list) + ";")

                if is_send_message:
                    signal_write_list.append(f"inline void canMessageHandler_{message.name}_{signal.name}_Write({si_signal.type} value)\n"
                                             "{\n"
                                             f"\t{message.name}_{signal.name} = value;\n"
                                             "}\n")
                    signal_write_name_list.append(f"inline void canMessageHandler_{message.name}_{signal.name}_Write({si_signal.type} value);")
                else:
                    signal_read_list.append(f"inline {si_signal.type} canMessageHandler_{message.name}_{signal.name}_Read(void)\n"
                                             "{\n"
                                             f"\treturn {message.name}_{signal.name};\n"
                                             "}\n")
                    signal_read_name_list.append(f"inline {si_signal.type} canMessageHandler_{message.name}_{signal.name}_Read(void);")

            bitfield_list.append(f"}} {message.name}_t;\n")
            message_init_list.append("}\n")
            message_run_list.append("}\n")

        message_definition_list.append("};")

        file_text = "\n".join(bitfield_list) + "\n"
        file_text += "\n".join(persistent_var_list) + "\n\n"
        file_text += "/* Public Functions */\n"
        file_text += "\n".join(message_init_list) + "\n"
        file_text += "\n".join(message_run_list) + "\n"
        file_text += "\n".join(signal_read_list) + "\n"
        file_text += "\n".join(signal_write_list)
        file_text = c_file.substitute(CREATION_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                      MESSAGE_DEFINITION=file_text)

        # Using flag "w" makes sure file is overwritten each time
        with open(f"{self.si_path}/canMessageHandler.c", "w") as f:
            f.write(file_text)

        file_text = "\t/* Init functions */\n\t"
        file_text += "\n\t".join(message_init_name_list) + "\n\n"
        file_text += "\t/* Run functions */\n\t"
        file_text += "\n\t".join(message_run_name_list) + "\n\n"
        file_text += "\t/* Write functions */\n\t"
        file_text += "\n\t".join(signal_write_name_list) + "\n\n"
        file_text += "\t/* Read functions */\n\t"
        file_text += "\n\t".join(signal_read_name_list) + "\n\n"
        file_text += "\t/* Message definitions list */\n\t"
        file_text += "\n\t".join(message_definition_list)
        file_text = h_file.substitute(CREATION_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                      MESSAGE_DEFINITION=file_text)

        # Using flag "w" makes sure file is overwritten each time
        with open(f"{self.si_path}/canMessageHandler.h", "w") as f:
            f.write(file_text)

    def _generate_io_handler(self):

        with open(f"c_templates/ioHandler_TEMPLATE.c") as f:
            c_file = string.Template(f.read())

        with open(f"c_templates/ioHandler_TEMPLATE.h") as f:
            h_file = string.Template(f.read())

        io_variables_list = []
        io_configuration_list = []
        io_default_values_list = []
        io_run_list = []
        io_pin_functions_list = []
        io_pin_function_names_list = []

        for signal in self.signals.values():
            if isinstance(signal, IOSignal):
                io_variables_list.append(f"bool {signal.connection.upper()}_Status;")

                io_configuration_list.append(f"\t// Configure {signal.name} to PIN {signal.connection.upper()}")

                if signal.is_input:
                    io_configuration_list.append(f"\tTRIS{signal.connection.upper()} = 1; // Signal is input")

                    # Read init value from input
                    io_default_values_list.append(
                        f"\t{signal.connection.upper()}_Status = PORT{signal.connection.upper()[0]}bits.R{signal.connection.upper()}; // Read init from input")

                    # Read value each run call
                    io_run_list.append(f"\t{signal.connection.upper()}_Status = PORT{signal.connection.upper()[0]}bits.R{signal.connection.upper()}; // Read {signal.connection.upper()}")

                    # Read signal function
                    io_pin_functions_list.append(f"bool ioHandler_{signal.name}_{signal.connection.upper()}_Read(void)\n{{")
                    io_pin_function_names_list.append(f"bool ioHandler_{signal.name}_{signal.connection.upper()}_Read(void);")
                    io_pin_functions_list.append(f"\treturn {signal.connection.upper()}_Status;\n}}")
                else:
                    io_configuration_list.append(f"\tTRIS{signal.connection.upper()} = 0; // Signal is output")

                    # Read init from definition
                    io_default_values_list.append(
                        f"\t{signal.connection.upper()}_Status = {int(signal.default_value)}; // Read init from definition")
                    io_default_values_list.append(
                        f"\tPORT{signal.connection.upper()[0]}bits.R{signal.connection.upper()} = {signal.connection.upper()}_Status;")

                    # Write value each run call
                    io_run_list.append(
                        f"\tPORT{signal.connection.upper()[0]}bits.R{signal.connection.upper()} = {signal.connection.upper()}_Status; // Write {signal.connection.upper()}")

                    # Write signal function
                    io_pin_functions_list.append(f"void ioHandler_{signal.name}_{signal.connection.upper()}_Write(bool value)\n{{")
                    io_pin_function_names_list.append(f"void ioHandler_{signal.name}_{signal.connection.upper()}_Write(bool value);")
                    io_pin_functions_list.append(f"\t{signal.connection.upper()}_Status = value;\n}}")

                io_configuration_list.append(f"\tANSEL{signal.connection.upper()} = 0; // Signal is not analogue")

                if signal.is_input and signal.pullup:
                    io_configuration_list.append(f"\tWPU{signal.connection.upper()} = 1; // Activate pullup")
                elif signal.is_input and not signal.pullup:
                    io_configuration_list.append(f"\tWPU{signal.connection.upper()} = 0; // Deactivate pullup")

                # Blank row between signals
                io_configuration_list.append("")
                io_pin_functions_list.append("")

        io_variables = "\n".join(io_variables_list)
        io_configuration = "\n".join(io_configuration_list)
        io_default_values = "\n".join(io_default_values_list)
        io_run = "\n".join(io_run_list)
        io_pin_functions = "\n".join(io_pin_functions_list)
        io_pin_function_names = "\n".join(io_pin_function_names_list)

        file_text = c_file.substitute(CREATION_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                      IO_VARIABLES=io_variables,
                                      IO_CONFIGURATION=io_configuration,
                                      IO_DEFAULT_VALUES=io_default_values,
                                      IO_RUN=io_run,
                                      IO_PIN_FUNCTIONS = io_pin_functions)

        # Using flag "w" makes sure file is overwritten each time
        with open(f"{self.si_path}/ioHandler.c", "w") as f:
            f.write(file_text)

        file_text = h_file.substitute(CREATION_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                      IO_PIN_FUNCTION_NAMES = io_pin_function_names)

        # Using flag "w" makes sure file is overwritten each time
        with open(f"{self.si_path}/ioHandler.h", "w") as f:
            f.write(file_text)

    def _generate_internal_signal_handler(self):

        with open(f"c_templates/internalSignalHandler_TEMPLATE.c") as f:
            c_file = string.Template(f.read())

        with open(f"c_templates/internalSignalHandler_TEMPLATE.h") as f:
            h_file = string.Template(f.read())

        signal_variables_list = []
        default_values_list = []
        write_read_functions_list = []
        write_read_function_names_list = []

        for signal in self.signals.values():
            if isinstance(signal, InternalSignal):
                signal_variables_list.append(f"{signal.type} {signal.name}_Status;")

                # Read init value from definition
                # If default value is a bool, we need to lower it as python capitalize bools
                if isinstance(signal.default_value, bool):
                    default_value = str(signal.default_value).lower()
                else:
                    default_value = signal.default_value
                default_values_list.append(f"\t{signal.name}_Status = {default_value}; // Read init value from definition")

                # Read signal function
                write_read_functions_list.append(f"{signal.type} internalSignalHandler_{signal.name}_Read(void)\n{{")
                write_read_function_names_list.append(f"\t{signal.type} internalSignalHandler_{signal.name}_Read(void);")
                write_read_functions_list.append(f"\treturn {signal.name}_Status;\n}}")

                # Blank row between functions
                write_read_functions_list.append("")

                # Write signal function
                write_read_functions_list.append(f"void internalSignalHandler_{signal.name}_Write({signal.type} value)\n{{")
                write_read_function_names_list.append(f"\tvoid internalSignalHandler_{signal.name}_Write({signal.type} value);")
                write_read_functions_list.append(f"\t{signal.name}_Status = value;\n}}")

                # Blank row between signals
                write_read_functions_list.append("")

        signal_variables = "\n".join(signal_variables_list)
        default_values = "\n".join(default_values_list)
        write_read_functions = "\n".join(write_read_functions_list)
        write_read_function_names = "\n".join(write_read_function_names_list)

        file_text = c_file.substitute(CREATION_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                      SIGNAL_VARIABLES=signal_variables,
                                      DEFAULT_VALUES=default_values,
                                      WRITE_READ_FUNCTIONS = write_read_functions)

        # Using flag "w" makes sure file is overwritten each time
        with open(f"{self.si_path}/internalSignalHandler.c", "w") as f:
            f.write(file_text)

        file_text = h_file.substitute(CREATION_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                      WRITE_READ_FUNCTION_NAMES = write_read_function_names)

        # Using flag "w" makes sure file is overwritten each time
        with open(f"{self.si_path}/internalSignalHandler.h", "w") as f:
            f.write(file_text)

    def _generate_periodicals(self):
        with open(f"c_templates/periodicals_TEMPLATE.c") as f:
            c_file = string.Template(f.read())

        external_defines_list = []
        last_run_variables_list = []
        swc_inits_list = []
        swc_runs_list = []

        for swc in self.software_components.values():
            for init_func in swc.inits:
                swc_inits_list.append(f"\t{init_func}();")
                external_defines_list.append(f"extern void {init_func}(void);")

            for periodical, period in swc.periodicals:
                external_defines_list.append(f"extern void {periodical}(void);")
                last_run_variables_list.append(f"uint16_t {periodical}_last_run = {0xffff-period}; // Set last run to one period ago")

                # Check if timer has passed last run
                swc_runs_list.append(f"\t// Check if timer for {periodical} has elapsed")
                swc_runs_list.append(f"\tif((current_time - {periodical}_last_run) > {period})\n\t{{")
                swc_runs_list.append(f"\t\t{periodical}();")
                swc_runs_list.append(f"\t\t{periodical}_last_run = current_time;")
                swc_runs_list.append(f"\t}}\n")

            # Line break for prettyness
            external_defines_list.append("")

        external_defines = "\n".join(external_defines_list)
        last_run_variables = "\n".join(last_run_variables_list)
        swc_inits = "\n".join(swc_inits_list)
        swc_runs = "\n".join(swc_runs_list)

        file_text = c_file.substitute(CREATION_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                      EXTERNAL_DEFINES=external_defines,
                                      SWC_INITS=swc_inits,
                                      SWC_RUNS=swc_runs,
                                      LAST_RUN_VARIABLES=last_run_variables)

        # Using flag "w" makes sure file is overwritten each time
        with open(f"{self.si_path}/periodicals.c", "w") as f:
            f.write(file_text)

    def _generate_software_components(self, remove_stubs: bool = False):
        for swc in self.software_components.values():
            # Check if SWC already exists and remove_stubs is False
            if Path(f"{self.si_path}/{swc.name}/{swc.name}.c").exists() and not remove_stubs:
                # SWC exists, do not touch it
                continue

            with open(f"c_templates/SWC_TEMPLATE.c") as f:
                c_file = string.Template(f.read())

            with open(f"c_templates/SWC_TEMPLATE.h") as f:
                h_file = string.Template(f.read())

            with open(f"c_templates/SWC_SI_TEMPLATE.h") as f:
                si_h_file = string.Template(f.read())

            swc_functions_list = []
            swc_functions_names_list = []
            swc_si_function_names_list = []

            for init_func in swc.inits:
                swc_functions_names_list.append(f"\tvoid {init_func}();")
                swc_functions_list.append(f"void {init_func}()\n{{\n\n}}\n")

            for periodical, period in swc.periodicals:
                swc_functions_names_list.append(f"\tvoid {periodical}();")
                swc_functions_list.append(f"void {periodical}()\n{{\n\n}}\n")

            for signal in swc.input_signals.values():
                swc_si_function_names_list.append(f"\t{signal.type} {signal.name}_Read(void);")

            for signal in swc.output_signals.values():
                swc_si_function_names_list.append(f"\tvoid {signal.name}_Read({signal.type} value);")

            swc_functions = "\n".join(swc_functions_list)
            swc_functions_names = "\n".join(swc_functions_names_list)
            swc_si_function_names = "\n".join(swc_si_function_names_list)

            file_text = c_file.substitute(CREATION_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                          SWC_NAME=swc.name,
                                          SWC_NAME_H=swc.name + ".h",
                                          SWC_FUNCTIONS=swc_functions)

            # Using flag "w" makes sure file is overwritten each time
            with open(f"{self.si_path}/{swc.name}/{swc.name}.c", "w") as f:
                f.write(file_text)

            file_text = h_file.substitute(CREATION_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                          SWC_NAME=swc.name,
                                          SWC_NAME_H=swc.name.upper() + "_H",
                                          SWC_FUNCTIONS=swc_functions_names)

            # Using flag "w" makes sure file is overwritten each time
            with open(f"{self.si_path}/{swc.name}/{swc.name}.h", "w") as f:
                f.write(file_text)

            file_text = si_h_file.substitute(CREATION_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                             SWC_NAME="SI_" + swc.name,
                                             SWC_NAME_H="SI_" + swc.name.upper() + "_H",
                                             SWC_FUNCTIONS=swc_si_function_names)

            # Using flag "w" makes sure file is overwritten each time
            with open(f"{self.si_path}/{swc.name}/SI_{swc.name}.h", "w") as f:
                f.write(file_text)

    def _generate_signal_definitions(self):

        with open(f"c_templates/signalDefinitions_TEMPLATE.c") as f:
            c_file = string.Template(f.read())

        signal_definitions_list = []

        for signal in self.signals.values():
            if isinstance(signal, CanSignal):
                if not signal.is_consumed:
                    continue
                if signal.is_input:
                    signal_definitions_list.append(f"{signal.type} {signal.name}_Read()\n{{")
                    signal_definitions_list.append(f"\treturn canMessageHandler_{signal.database_signal.message.name}_{signal.name}_Read();\n}}")
                else:
                    signal_definitions_list.append(f"void {signal.name}_Write({signal.type} value)\n{{")
                    signal_definitions_list.append(f"\tcanMessageHandler_{signal.database_signal.message.name}_{signal.name}_Write(value);\n}}")

            elif isinstance(signal, IOSignal):
                if signal.is_input:
                    signal_definitions_list.append(f"{signal.type} {signal.name}_Read()\n{{")
                    signal_definitions_list.append(f"\treturn ioHandler_{signal.name}_{signal.connection.upper()}_Read();\n}}")
                else:
                    signal_definitions_list.append(f"void {signal.name}_Write({signal.type} value)\n{{")
                    signal_definitions_list.append(f"\nioHandler_{signal.name}_{signal.connection.upper()}_Write(value);\n}}")

            else: # Internal signal
                signal_definitions_list.append(f"{signal.type} {signal.name}_Read()\n{{\n\treturn internalSignalHandler_{signal.name}_Read();\n}}\n")
                signal_definitions_list.append(f"\tvoid {signal.name}_Write({signal.type} value)\n{{\n\tinternalSignalHandler_{signal.name}_Write(value);\n}}")

            # Add row
            signal_definitions_list.append("")

        signal_definitions = "\n".join(signal_definitions_list)

        file_text = c_file.substitute(CREATION_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                      SIGNAL_DEFINITIONS=signal_definitions)

        # Using flag "w" makes sure file is overwritten each time
        with open(f"{self.si_path}/signalDefinitions.c", "w") as f:
            f.write(file_text)

    def get_can_signals(self):
        can_signals = []
        for signal in self.signals.values():
            if type(signal) == CanSignal:
                can_signals.append(signal.database_signal)

        return can_signals

    def get_can_messages(self) -> list[dbcreader.Message]:
        can_signals = self.get_can_signals()
        messages = []
        for signal in can_signals:
            if signal.message not in messages:
                messages.append(signal.message)

        return messages


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
    signal_interface.generate_templates(True)