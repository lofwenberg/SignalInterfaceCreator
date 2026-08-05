import sys

from dbcreader import Database
from signal_interface_handler import SignalInterface

# Paths to the input files used by this generator.
DBC_FILE = r"..\database.dbc"
JSON_FILE = r"..\signal_interface.json"

# Load the signal_interface from the json_file
signal_interface = SignalInterface(JSON_FILE, DBC_FILE)

# Everything parsed, start building files
print(signal_interface)