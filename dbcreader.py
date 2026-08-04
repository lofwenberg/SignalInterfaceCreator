class Message:
    """Represents a CAN message parsed from a DBC file."""

    def __init__(self, message_id, name, size):
        self.id = message_id
        self.name = name
        self.size = size
        self.signals = {}

    def __repr__(self):
        return self.name

    def add_signal(self, signal):
        """Store a signal by its bit position inside the message."""
        self.signals[signal.position] = signal


class Signal:
    """Represents a single signal that belongs to a CAN message."""

    def __init__(self, name, position, size, signed, message):
        self.name = name
        self.position = position
        self.size = size
        self.signed = signed
        self.message = message
        message.add_signal(self)

    def __repr__(self):
        return self.name


class Database:
    """Parse a DBC file and build an in-memory model of its messages and signals."""

    def __init__(self, filename):
        self.filename = filename
        self.messages = {}
        self.signals = {}
        self._parse(filename)

    def _parse(self, filename):
        # Read the DBC file into memory so we can walk it line by line.
        with open(filename) as handle:
            lines = [line.rstrip("\n") for line in handle]

        index = 0
        while index < len(lines):
            line = lines[index]

            # Skip anything that is not the start of a message block.
            if not line.startswith("BO_"):
                index += 1
                continue

            # Parse the message header: ID, name, and size.
            parts = line.split()
            if len(parts) < 4:
                index += 1
                continue

            message_id = int(parts[1])
            message_name = parts[2][:-1]
            message_size = int(parts[3])

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
                    self.messages[message_id] = message

                # Parse the signal definition from the DBC line.
                parts = line.split()
                signal_name = parts[1]
                sub_parts = parts[3].split("|")
                signal_pos = int(sub_parts[0])
                sub_parts = sub_parts[1].split("@")
                signal_size = int(sub_parts[0])
                signed = False if sub_parts[1] == "-" else True

                # Create the signal object and register it in the database.
                signal = Signal(signal_name, signal_pos, signal_size, signed, message)
                self.signals[signal.name] = signal
                index += 1