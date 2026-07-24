import os
import sys
import importlib.util

# Discover and load root smtp2mqtt.py script symbols
root_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "smtp2mqtt.py")
if os.path.exists(root_file):
    spec = importlib.util.spec_from_file_location("smtp2mqtt_legacy_mod", root_file)
    if spec and spec.loader:
        _mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_mod)
        globals()["_legacy_mod"] = _mod
        for attr, val in _mod.__dict__.items():
            if not attr.startswith("__"):
                globals()[attr] = val





