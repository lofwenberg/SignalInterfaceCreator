import sys

from dbcreader import Database
from json_handler import load_signals

# Paths to the input files used by this generator.
DBC_FILE = r"..\database.dbc"
JSON_FILE = r"..\signals.json"

# Load the JSON payload into dynamically generated objects.
json_data = load_signals(JSON_FILE)

# Validate the required sections and their child fields in one pass.
required_fields = {
    "ioSignals": ["name", "pin_connection"],
    "signals": ["name", "size", "signed"],
}

for section_name, fields in required_fields.items():
    if section_name not in json_data:
        print(f"Missing required JSON section: {section_name}")
        sys.exit(0)

    items = json_data[section_name]
    for index, item in enumerate(items):
        missing_fields = [field for field in fields if field not in item.__dict__]
        if missing_fields:
            print(
                f"Missing required field(s) for {section_name}[{index}]: "
                + ", ".join(missing_fields)
            )
            sys.exit(0)

# Expose the parsed sections for later use.
io_signals = json_data["ioSignals"]
signals = json_data["signals"]

# Initialize the DBC database reader.
db = Database(DBC_FILE)

# Initialize CAN-signals
can_signals = list()

# Initialize internal-signals
internal_signals = list()

# Parse signals and find matching can-signals
for signal in signals:
    if signal.name in db.signals.keys():
        can_signal = db.signals[signal.name]
        # This is a can-signal, make sure it matches definition
        if signal.size != can_signal.size:
            print(f"Defined signal \"{signal.name}\" has different size to can-signal with same name. Assumes this to not be can-signal")
            internal_signals.append(signal.name)
        elif signal.signed != can_signal.signed:
            print(f"Defined signal \"{signal.name}\" has different sign compared to can-signal with same name. Assumes this to not be can-signal")
            internal_signals.append(signal.name)
        else:
            can_signals.append(can_signal)
    else:
        internal_signals.append(signal.name)

# Everything parsed, start building files