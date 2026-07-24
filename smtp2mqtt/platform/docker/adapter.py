import os
import json
import sys
from typing import Dict, Any
from smtp2mqtt.platform.interface import PlatformAdapter

class DockerPlatformAdapter(PlatformAdapter):
    """Platform adapter for standard containerized Docker environments."""
    
    def initialize(self) -> None:
        pass

    def load_config(self) -> Dict[str, Any]:
        file_cfg = {}
        if os.path.exists("config.json"):
            try:
                with open("config.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        file_cfg = data
            except Exception as e:
                sys.stderr.write(f"Warning: Could not read config.json: {e}\n")
        return file_cfg

    def get_data_dir(self) -> str:
        return "."

    def get_log_dir(self) -> str:
        return "log" if os.path.exists("log") else ""
