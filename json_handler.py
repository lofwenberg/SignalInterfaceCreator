import json
from pathlib import Path

# Default path to the signals JSON file.
DEFAULT_JSON_PATH = r"..\signals.json"


def create_model_class(name: str, field_names):
    """Create a dynamic class whose attributes match the provided field names."""
    field_names = list(field_names)

    def __init__(self, **kwargs):
        for field_name in field_names:
            setattr(self, field_name, kwargs.get(field_name))

    return type(name, (), {"__init__": __init__})


class SignalsJsonReader:
    """Load and convert a JSON file into dynamic Python objects."""

    def __init__(self, file_path: str = DEFAULT_JSON_PATH):
        self.file_path = Path(file_path)

    def read(self):
        if not self.file_path.exists():
            raise FileNotFoundError(f"JSON file not found: {self.file_path}")

        with self.file_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _collect_fields(items):
        """Collect all field names present across the provided list items."""
        fields = []
        for item in items:
            if isinstance(item, dict):
                for key in item:
                    if key not in fields:
                        fields.append(key)
        return fields

    def read_signals(self):
        """Load root-level JSON arrays into dynamically generated objects."""
        data = self.read()
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object at the root")

        root_classes = []
        for key, value in data.items():
            if isinstance(value, list) and value:
                fields = self._collect_fields(value)
                model_class = create_model_class(key, fields)
                instances = [model_class(**item) for item in value if isinstance(item, dict)]
                root_classes.append((key, instances))

        return {key: value for key, value in root_classes}


def load_signals(file_path: str = DEFAULT_JSON_PATH):
    """Convenience wrapper for loading the signals JSON file."""
    return SignalsJsonReader(file_path).read_signals()
