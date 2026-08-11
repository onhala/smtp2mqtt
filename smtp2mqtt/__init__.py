"""smtp2mqtt v2.0 - Universal Email-to-MQTT Bridge for IP Cameras & Smart Home."""

import importlib.util
import os
import sys

__version__ = "2.0.0"
__author__ = "Ondřej Hála"

# Expose domain models & parsers
from smtp2mqtt.models.event import CameraEvent, EventType, TargetType
from smtp2mqtt.models.action import ActionEntry
from smtp2mqtt.parsers.registry import parse_camera_event, ParserRegistry

# Seamlessly load root smtp2mqtt.py script symbols when `import smtp2mqtt` is called
_root_script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smtp2mqtt.py"))
if os.path.isfile(_root_script_path):
    spec = importlib.util.spec_from_file_location("_smtp2mqtt_root", _root_script_path)
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        # Avoid circular import recursion
        sys.modules["_smtp2mqtt_root"] = mod
        try:
            spec.loader.exec_module(mod)
            for attr in dir(mod):
                if not attr.startswith("__"):
                    globals()[attr] = getattr(mod, attr)
        except Exception:
            pass
