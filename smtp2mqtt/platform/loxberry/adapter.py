import os
import sys
import json
import logging
from typing import Dict, Any
from smtp2mqtt.platform.interface import PlatformAdapter

log = logging.getLogger("smtp2mqtt")

class LoxBerryPlatformAdapter(PlatformAdapter):
    """Platform adapter for native LoxBerry plugin environment."""
    
    def __init__(self) -> None:
        self.lb_home = os.environ.get("LBHOME", "/opt/loxberry" if os.path.exists("/opt/loxberry") else None)

    def initialize(self) -> None:
        """Patch sys.path to include LoxBerry system python packages if present."""
        if self.lb_home and os.path.exists(self.lb_home):
            lb_python = os.path.join(self.lb_home, "system", "python")
            if os.path.exists(lb_python) and lb_python not in sys.path:
                sys.path.insert(0, lb_python)

    def get_loxberry_paths(self) -> Dict[str, str]:
        paths = {}
        if self.lb_home and os.path.exists(self.lb_home):
            paths["LBHOME"] = self.lb_home
            paths["LBPDATA"] = os.environ.get("LBPDATA", os.path.join(self.lb_home, "data", "plugins", "smtp2mqtt"))
            paths["LBPLOG"] = os.environ.get("LBPLOG", os.path.join(self.lb_home, "log", "plugins", "smtp2mqtt"))
            paths["LBPCONFIG"] = os.environ.get("LBPCONFIG", os.path.join(self.lb_home, "config", "plugins", "smtp2mqtt"))
            paths["LBPMQTT_JSON"] = os.path.join(self.lb_home, "config", "system", "mqttgateway.json")
            paths["LBPMQTT_INI"] = os.path.join(self.lb_home, "config", "system", "mqttgateway.ini")
        return paths

    def load_loxberry_mqtt_config(self, paths: Dict[str, str]) -> Dict[str, Any]:
        mqtt_cfg = {}
        mqtt_json = paths.get("LBPMQTT_JSON")
        mqtt_ini = paths.get("LBPMQTT_INI")

        if mqtt_json and os.path.exists(mqtt_json):
            try:
                with open(mqtt_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    main = data.get("Main", data.get("Credentials", data))
                    if "brokeraddress" in main or "mqttserver" in main or "server" in main:
                        mqtt_cfg["MQTT_HOST"] = main.get("brokeraddress") or main.get("mqttserver") or main.get("server") or "localhost"
                    if "brokerport" in main or "mqttport" in main or "port" in main:
                        mqtt_cfg["MQTT_PORT"] = main.get("brokerport") or main.get("mqttport") or main.get("port") or 1883
                    if "brokeruser" in main or "mqttuser" in main or "username" in main:
                        mqtt_cfg["MQTT_USERNAME"] = main.get("brokeruser") or main.get("mqttuser") or main.get("username") or ""
                    if "brokerpass" in main or "mqttpass" in main or "password" in main:
                        mqtt_cfg["MQTT_PASSWORD"] = main.get("brokerpass") or main.get("mqttpass") or main.get("password") or ""
            except Exception as e:
                sys.stderr.write(f"Warning: Failed to load LoxBerry MQTT Gateway JSON config: {e}\n")
        elif mqtt_ini and os.path.exists(mqtt_ini):
            try:
                import configparser
                parser = configparser.ConfigParser()
                parser.read(mqtt_ini)
                section = "Main" if "Main" in parser else ("MQTT" if "MQTT" in parser else None)
                if section:
                    sec = parser[section]
                    if "brokeraddress" in sec or "mqttserver" in sec or "server" in sec:
                        mqtt_cfg["MQTT_HOST"] = sec.get("brokeraddress") or sec.get("mqttserver") or sec.get("server") or "localhost"
                    if "brokerport" in sec or "mqttport" in sec or "port" in sec:
                        mqtt_cfg["MQTT_PORT"] = sec.get("brokerport") or sec.get("mqttport") or sec.get("port") or 1883
                    if "brokeruser" in sec or "mqttuser" in sec or "username" in sec:
                        mqtt_cfg["MQTT_USERNAME"] = sec.get("brokeruser") or sec.get("mqttuser") or sec.get("username") or ""
                    if "brokerpass" in sec or "mqttpass" in sec or "password" in sec:
                        mqtt_cfg["MQTT_PASSWORD"] = sec.get("brokerpass") or sec.get("mqttpass") or sec.get("password") or ""
            except Exception as e:
                sys.stderr.write(f"Warning: Failed to load LoxBerry MQTT Gateway INI config: {e}\n")

        return mqtt_cfg

    def load_config(self) -> Dict[str, Any]:
        paths = self.get_loxberry_paths()
        lb_mqtt = self.load_loxberry_mqtt_config(paths)
        file_cfg = {}
        
        config_paths = []
        if "LBPCONFIG" in paths:
            config_paths.append(os.path.join(paths["LBPCONFIG"], "config.json"))
        config_paths.append("config.json")

        for cfg_path in config_paths:
            if os.path.exists(cfg_path):
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            file_cfg.update(data)
                            break
                except Exception as e:
                    sys.stderr.write(f"Warning: Could not read config file {cfg_path}: {e}\n")

        merged = {}
        merged.update(lb_mqtt)
        merged.update(file_cfg)
        return merged

    def get_data_dir(self) -> str:
        paths = self.get_loxberry_paths()
        return paths.get("LBPDATA", ".")

    def get_log_dir(self) -> str:
        paths = self.get_loxberry_paths()
        return paths.get("LBPLOG", ".")
