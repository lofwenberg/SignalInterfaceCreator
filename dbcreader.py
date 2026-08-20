class ControlUnit:
    """Represents a control unit in the CAN network"""

    def __init__(self, name):
        self.name = name
        self.messages = []

    def __repr__(self):
        return self.name

    def __eq__(self, other):
        if isinstance(other, ControlUnit):
            return self.name == other.name
        elif isinstance(other, str):
            return self.name == other
        else:
            return NotImplemented

    def add_message(self, message: Message):
        self.messages.append(message)
        message.transmitter = self

class Message:
    """Represents a CAN message parsed from a DBC file."""

    def __init__(self, message_id, name, size):
        self.id = message_id
        self.name = name
        self.size = size
        self.signals = {}
        self.transmitter = None

    def __repr__(self):
        return self.name

    def add_signal(self, signal):
        """Store a signal by its bit position inside the message."""
        self.signals[signal.position] = signal


class Signal:
    """Represents a single signal that belongs to a CAN message."""

    def __init__(self, name, position, size, signed, message: Message, receivers: list[ControlUnit]):
        self.name = name
        self.position = position
        self.size = size
        self.signed = signed
        self.message = message
        self.receivers = receivers
        self.init_value = 0
        message.add_signal(self)

    def __repr__(self):
        return self.name


class Database:
    """Parse a DBC file and build an in-memory model of its messages and signals."""

    def __init__(self, filename):
        self.filename: str = filename
        self.messages: dict[int, Message] = {}
        self.signals: dict[str, Signal] = {}
        self.control_units: dict[str, ControlUnit] = {}
        self._parse(filename)

    def _parse(self, filename):
        # Read the DBC file into memory so we can walk it line by line.
        with open(filename) as handle:
            lines = [line.rstrip("\n") for line in handle]

        index = 0
        while index < len(lines):
            line = lines[index]

            # Read control unit section
            if line.startswith("BU_"):
                control_units = list()
                parts = line.split()

                for control_unit_name in parts[1:]:
                    self.control_units[control_unit_name] = ControlUnit(control_unit_name)
                index+=1
            # Read message section
            elif line.startswith("BO_"):
                # Parse the message header: ID, name, and size.
                parts = line.split()
                if len(parts) < 4:
                    index += 1
                    continue

                message_id = int(parts[1])
                message_name = parts[2][:-1]
                message_size = int(parts[3])
                message_transmitter_name = parts[4]
                message_transmitter = self.control_units[message_transmitter_name]

                index += 1
                message = None

                # Consume all signal lines that belong to this message.
                while index < len(lines):
                    line = lines[index]
                    if not line.startswith(" SG_"):
                        break

                    # Create the message once we hit the first signal line.
                    if message is None:
                        message = Message(message_id, message_name, message_size)
                        message_transmitter.add_message(message)
                        self.messages[message_id] = message

                    # Parse the signal definition from the DBC line.
                    parts = line.split()
                    signal_name = parts[1]
                    sub_parts = parts[3].split("|")
                    signal_pos = int(sub_parts[0])
                    sub_parts = sub_parts[1].split("@")
                    signal_size = int(sub_parts[0])
                    signed = False if sub_parts[1].count("-") == 0 else True
                    receiver_name_list = parts[7:]

                    receiver_list = []
                    for receiver_name in receiver_name_list:
                        receiver_list.append(self.control_units[receiver_name])

                    # Create the signal object and register it in the database.
                    signal = Signal(signal_name, signal_pos, signal_size, signed, message, receiver_list)
                    self.signals[signal.name] = signal
                    index += 1
            elif line.startswith("BA_ \"GenSigStartValue\""):
                parts = line.split()
                signal = self.signals[parts[4]]
                signal.init_value = int(parts[5].strip(";"))
                index += 1
            else:
                index += 1

if __name__ == "__main__":
    db = Database("../database.dbc")
    print(db.messages)