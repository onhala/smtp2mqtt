#!/usr/bin/env python3
import sys
import os
import glob
import subprocess

# Robustly discover all potential site-packages / dist-packages directories on LoxBerry
extra_paths = (
    glob.glob("/opt/loxberry/.local/lib/python3.*/site-packages") +
    glob.glob("/home/*/.local/lib/python3.*/site-packages") +
    glob.glob("/root/.local/lib/python3.*/site-packages") +
    glob.glob("/var/www/.local/lib/python3.*/site-packages") +
    glob.glob("/usr/local/lib/python3.*/dist-packages") +
    glob.glob(os.path.expanduser("~/.local/lib/python3.*/site-packages"))
)
for site in extra_paths:
    if site not in sys.path:
        sys.path.insert(0, site)

import asyncio
import email
import ipaddress
import json
import logging
import signal
import socket
import urllib.request
import urllib.error
from datetime import datetime
from email.policy import default
from typing import Any, Dict, List, Optional, Union

try:
    from aiosmtpd.controller import UnthreadedController
    from paho.mqtt import client as mqtt, publish
except ModuleNotFoundError as err:
    sys.stderr.write(f"Missing module: {err}. Attempting auto-install of dependencies...\n")
    packages = ["aiosmtpd", "paho-mqtt", "aiomqtt", "pillow"]
    installed = False
    for pip_args in [
        [sys.executable, "-m", "pip", "install", "--break-system-packages", "--user"] + packages,
        [sys.executable, "-m", "pip", "install", "--break-system-packages"] + packages,
        ["pip3", "install", "--user", "--break-system-packages"] + packages,
        ["pip3", "install", "--break-system-packages"] + packages,
    ]:
        try:
            res = subprocess.run(pip_args, capture_output=True, text=True)
            if res.returncode == 0:
                installed = True
                break
        except Exception:
            pass

    # Re-scan site-packages after install
    extra_paths = (
        glob.glob("/opt/loxberry/.local/lib/python3.*/site-packages") +
        glob.glob("/home/*/.local/lib/python3.*/site-packages") +
        glob.glob("/root/.local/lib/python3.*/site-packages") +
        glob.glob("/var/www/.local/lib/python3.*/site-packages") +
        glob.glob("/usr/local/lib/python3.*/dist-packages") +
        glob.glob(os.path.expanduser("~/.local/lib/python3.*/site-packages"))
    )
    for site in extra_paths:
        if site not in sys.path:
            sys.path.insert(0, site)

    from aiosmtpd.controller import UnthreadedController
    from paho.mqtt import client as mqtt, publish

# Default configurations
defaults: Dict[str, Union[str, int]] = {
    "SMTP_PORT": 1025,
    "SMTP_HOST": "0.0.0.0",
    "ALLOWED_IPS": "192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12, 127.0.0.1",
    "MQTT_HOST": "localhost",
    "MQTT_PORT": 1883,
    "MQTT_USERNAME": "",
    "MQTT_PASSWORD": "",
    "MQTT_TOPIC": "smtp2mqtt",
    "MQTT_PAYLOAD": "ON",
    "MQTT_RESET_TIME": "10",
    "MQTT_RESET_PAYLOAD": "OFF",
    "SAVE_ATTACHMENTS": "False",
    "SAVE_ATTACHMENTS_DURING_RESET_TIME": "False",
    "DEBUG": "False",
    "ENABLE_WEB": "True",
    "WEB_PORT": "8080",
    "CLEANUP_ATTACHMENTS_DAYS": "30",
    "CLEANUP_LOGS_DAYS": "30",
    "CLEANUP_INTERVAL_SECONDS": "86400",
}

def parse_bool(value: Any) -> bool:
    """Helper to robustly parse boolean configuration values."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).lower() in ("true", "1", "yes", "on")


def get_loxberry_paths() -> Dict[str, str]:
    """Helper to detect LoxBerry environment variables and plugin directories."""
    paths = {}
    lb_home = os.environ.get("LBHOMEDIR") or os.environ.get("LBHOME") or ("/opt/loxberry" if os.path.exists("/opt/loxberry") else None)
    if lb_home and os.path.exists(lb_home):
        paths["LBHOME"] = lb_home
        paths["LBHOMEDIR"] = lb_home

        def _ensure_plugin_dir(val: Optional[str], default_path: str) -> str:
            if not val:
                return default_path
            val = val.rstrip("/\\")
            if not val.endswith("smtp2mqtt"):
                return os.path.join(val, "smtp2mqtt")
            return val

        paths["LBPDATA"] = _ensure_plugin_dir(os.environ.get("LBPDATA"), os.path.join(lb_home, "data", "plugins", "smtp2mqtt"))
        paths["LBPLOG"] = _ensure_plugin_dir(os.environ.get("LBPLOG"), os.path.join(lb_home, "log", "plugins", "smtp2mqtt"))
        paths["LBPCONFIG"] = _ensure_plugin_dir(os.environ.get("LBPCONFIG"), os.path.join(lb_home, "config", "plugins", "smtp2mqtt"))
        paths["LBPMQTT_JSON"] = os.path.join(lb_home, "config", "system", "mqttgateway.json")
        paths["LBPMQTT_INI"] = os.path.join(lb_home, "config", "system", "mqttgateway.ini")
    return paths



def load_loxberry_mqtt_config(paths: Dict[str, str]) -> Dict[str, Any]:
    """Auto-detect MQTT broker configuration from LoxBerry MQTT Gateway V2 / Mosquitto."""
    mqtt_cfg = {}

    # 1. Try LoxBerry PHP SDK mqtt_connectiondetails() call first (100% reliable on LoxBerry)
    if paths.get("LBHOME"):
        try:
            res = subprocess.run(
                ["php", "-r", 'require_once "loxberry_io.php"; if (function_exists("mqtt_connectiondetails")) { echo json_encode(mqtt_connectiondetails()); }'],
                capture_output=True,
                text=True,
                timeout=4
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout.strip())
                if isinstance(data, dict):
                    if data.get("brokerhost"):
                        mqtt_cfg["MQTT_HOST"] = str(data["brokerhost"])
                    if data.get("brokerport"):
                        try:
                            mqtt_cfg["MQTT_PORT"] = int(data["brokerport"])
                        except ValueError:
                            pass
                    if data.get("brokeruser"):
                        mqtt_cfg["MQTT_USERNAME"] = str(data["brokeruser"])
                    if data.get("brokerpass"):
                        mqtt_cfg["MQTT_PASSWORD"] = str(data["brokerpass"])
        except Exception:
            pass

    mqtt_json = paths.get("LBPMQTT_JSON")
    mqtt_ini = paths.get("LBPMQTT_INI")

    def _extract_from_dict(d: dict):
        user_keys = ["brokeruser", "mqttuser", "user", "username", "BrokerUser", "MQTTUser"]
        pass_keys = ["brokerpass", "mqttpass", "pass", "password", "BrokerPass", "MQTTPass"]
        host_keys = ["brokeraddress", "mqttserver", "server", "host", "BrokerAddress", "MQTTServer"]
        port_keys = ["brokerport", "mqttport", "port", "BrokerPort", "MQTTPort"]

        for k, v in d.items():
            if isinstance(v, dict):
                _extract_from_dict(v)
            else:
                if k in user_keys and v and "MQTT_USERNAME" not in mqtt_cfg:
                    mqtt_cfg["MQTT_USERNAME"] = str(v)
                if k in pass_keys and v and "MQTT_PASSWORD" not in mqtt_cfg:
                    mqtt_cfg["MQTT_PASSWORD"] = str(v)
                if k in host_keys and v and "MQTT_HOST" not in mqtt_cfg:
                    mqtt_cfg["MQTT_HOST"] = str(v)
                if k in port_keys and v and "MQTT_PORT" not in mqtt_cfg:
                    try:
                        mqtt_cfg["MQTT_PORT"] = int(v)
                    except ValueError:
                        pass

    if mqtt_json and os.path.exists(mqtt_json):
        try:
            with open(mqtt_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    main = data.get("Main", {})
                    creds = data.get("Credentials", {})
                    if "brokeraddress" in main:
                        mqtt_cfg["MQTT_HOST"] = str(main["brokeraddress"])
                    if "brokerport" in main:
                        try:
                            mqtt_cfg["MQTT_PORT"] = int(main["brokerport"])
                        except ValueError:
                            pass
                    if "brokeruser" in creds and creds["brokeruser"]:
                        mqtt_cfg["MQTT_USERNAME"] = str(creds["brokeruser"])
                    if "brokerpass" in creds and creds["brokerpass"]:
                        mqtt_cfg["MQTT_PASSWORD"] = str(creds["brokerpass"])

                    if "MQTT_HOST" not in mqtt_cfg or "MQTT_USERNAME" not in mqtt_cfg:
                        _extract_from_dict(data)
        except Exception as e:
            sys.stderr.write(f"Warning: Failed to load LoxBerry MQTT Gateway JSON config: {e}\n")

    if mqtt_ini and os.path.exists(mqtt_ini) and not (mqtt_cfg.get("MQTT_USERNAME") and mqtt_cfg.get("MQTT_PASSWORD")):
        try:
            import configparser
            parser = configparser.ConfigParser()
            parser.read(mqtt_ini)
            ini_dict = {sec: dict(parser[sec]) for sec in parser.sections()}
            _extract_from_dict(ini_dict)
        except Exception as e:
            sys.stderr.write(f"Warning: Failed to load LoxBerry MQTT Gateway INI config: {e}\n")

    return mqtt_cfg


def load_file_config(paths: Dict[str, str]) -> Dict[str, Any]:
    """Load configuration from config.json if present in LoxBerry config dir or working dir."""
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
    return file_cfg


loxberry_paths = get_loxberry_paths()
if "LBHOME" in loxberry_paths:
    defaults["ENABLE_WEB"] = "False"

lb_mqtt_defaults = load_loxberry_mqtt_config(loxberry_paths)
file_defaults = load_file_config(loxberry_paths)



def get_data_dir() -> str:
    """Returns the base data directory (LBPDATA if in LoxBerry mode, otherwise current dir)."""
    return loxberry_paths.get("LBPDATA", ".")


def get_attachments_dir() -> str:
    """Returns the attachments directory path."""
    data_dir = get_data_dir()
    att_dir = os.path.join(data_dir, "attachments") if data_dir != "." else "attachments"
    os.makedirs(att_dir, exist_ok=True)
    return att_dir

config: Dict[str, Any] = {}
for setting, default_val in defaults.items():
    config[setting] = default_val

for setting, file_val in file_defaults.items():
    config[setting] = file_val

for setting in defaults.keys():
    env_val = os.environ.get(setting)
    if env_val is not None:
        config[setting] = env_val

use_lb_mqtt = parse_bool(config.get("USE_LOXBERRY_MQTT", True))
if use_lb_mqtt and lb_mqtt_defaults:
    for k in ("MQTT_HOST", "MQTT_PORT", "MQTT_USERNAME", "MQTT_PASSWORD"):
        if k in lb_mqtt_defaults and lb_mqtt_defaults[k] not in (None, ""):
            config[k] = lb_mqtt_defaults[k]

for setting in ("SAVE_ATTACHMENTS", "SAVE_ATTACHMENTS_DURING_RESET_TIME", "DEBUG", "ENABLE_WEB", "USE_LOXBERRY_MQTT"):
    config[setting] = parse_bool(config.get(setting, defaults.get(setting, False)))

for setting in ("SMTP_PORT", "MQTT_PORT", "MQTT_RESET_TIME", "WEB_PORT", "CLEANUP_ATTACHMENTS_DAYS", "CLEANUP_LOGS_DAYS", "CLEANUP_INTERVAL_SECONDS"):
    try:
        config[setting] = int(config[setting])
    except (ValueError, TypeError):
        config[setting] = int(defaults.get(setting, 0))

def get_loxberry_loglevel(paths: Dict[str, str]) -> Optional[int]:
    """Reads LoxBerry system log level from plugin.cfg if available."""
    cfg_dir = paths.get("LBPCONFIG")
    if not cfg_dir:
        return None
    pcfg = os.path.join(cfg_dir, "plugin.cfg")
    if os.path.exists(pcfg):
        try:
            import configparser
            parser = configparser.ConfigParser()
            parser.read(pcfg)
            if "PLUGIN" in parser and "LOGLEVEL" in parser["PLUGIN"]:
                return int(parser["PLUGIN"]["LOGLEVEL"])
            if "SYSTEM" in parser and "LOGLEVEL" in parser["SYSTEM"]:
                return int(parser["SYSTEM"]["LOGLEVEL"])
        except Exception:
            pass
    return None

# Logging configuration
lb_loglevel = get_loxberry_loglevel(loxberry_paths)
if lb_loglevel is not None:
    if lb_loglevel >= 7:
        level = logging.DEBUG
    elif lb_loglevel >= 4:
        level = logging.INFO
    elif lb_loglevel >= 1:
        level = logging.ERROR
    else:
        level = logging.CRITICAL
elif config["DEBUG"]:
    level = logging.DEBUG
else:
    level = logging.INFO

log = logging.getLogger("smtp2mqtt")
log.setLevel(level)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Log to console
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(formatter)
log.addHandler(ch)

class FlushingFileHandler(logging.FileHandler):
    """Custom FileHandler that flushes log records to disk immediately."""
    def emit(self, record):
        super().emit(record)
        self.flush()

# File logging path resolution (LoxBerry log dir prioritized if available)
log_dir = loxberry_paths.get("LBPLOG") if "LBPLOG" in loxberry_paths else ("log" if os.path.exists("log") else None)
if not log_dir and loxberry_paths.get("LBHOME"):
    log_dir = os.path.join(loxberry_paths["LBHOME"], "log", "plugins", "smtp2mqtt")

if log_dir:
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "smtp2mqtt.log")
        fh = FlushingFileHandler(log_file, encoding="utf-8")
        fh.setFormatter(formatter)
        log.addHandler(fh)
        try:
            os.chmod(log_file, 0o666)
        except Exception:
            pass
        log.info(f"Setting up file logger at {log_file} (loglevel: {logging.getLevelName(level)})")
    except Exception as e:
        log.error(f"Failed to set up file logger: {e}. Continuing with console-only logging.")


VERSION = "1.8.26"


class smtp2mqttHandler:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.reset_time: float = float(config["MQTT_RESET_TIME"])
        self.handles: Dict[str, asyncio.TimerHandle] = {}
        self.background_tasks = set()
        
        # State tracking for Web Status Dashboard and gethomepage.dev
        self.start_time = datetime.now()
        self.processed_messages_count = 0
        self.last_publish_success: Optional[bool] = None
        self.last_publish_time: Optional[str] = None
        self.recent_actions: List[Dict[str, Any]] = []  # List of dicts
        self.recent_blocked_attempts: List[Dict[str, Any]] = []  # Track blocked IPs
        self.latest_version: Optional[str] = None
        self.update_available: bool = False
        self.version_check_status: str = "pending"
        
        # MQTT Broker connection monitoring
        self.mqtt_connected_status: Optional[bool] = None
        
        # Initialize persistent MQTT client
        if type(loop).__name__ in ("MagicMock", "Mock", "AsyncMock") or "pytest" in sys.modules:
            self._mqtt_client = None
        else:
            self._mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
            if config["MQTT_USERNAME"]:
                log.info(f"MQTT authentication configured for user '{config['MQTT_USERNAME']}'")
                self._mqtt_client.username_pw_set(config["MQTT_USERNAME"], config["MQTT_PASSWORD"])
            else:
                log.warning("No MQTT username configured. Connecting to broker without authentication.")

            self._mqtt_client.on_connect = self._on_mqtt_connect
            self._mqtt_client.on_disconnect = self._on_mqtt_disconnect
            
            # Start background thread loop and initiate asynchronous connection
            self._mqtt_client.loop_start()
            try:
                log.info(f"Connecting to MQTT broker at {config['MQTT_HOST']}:{config['MQTT_PORT']}...")
                self._mqtt_client.connect_async(config["MQTT_HOST"], config["MQTT_PORT"], keepalive=60)
            except Exception as e:
                log.error("Failed to connect_async to MQTT broker: %s", e)

        coro = self.monitor_mqtt_broker()
        if type(loop).__name__ in ("MagicMock", "Mock", "AsyncMock"):
            self.monitor_task = None
            coro.close()
        else:
            self.monitor_task = self.loop.create_task(coro)
            
        # SMTP Server connectivity monitoring
        self.smtp_connected_status_val: Optional[bool] = None
        coro_smtp = self.monitor_smtp_server()
        if type(loop).__name__ in ("MagicMock", "Mock", "AsyncMock"):
            self.monitor_smtp_task = None
            coro_smtp.close()
        else:
            self.monitor_smtp_task = self.loop.create_task(coro_smtp)
        
        # Periodic file and log cleanup task
        coro_cleanup = self.run_periodic_cleanup()
        if type(loop).__name__ in ("MagicMock", "Mock", "AsyncMock"):
            self.cleanup_task = None
            coro_cleanup.close()
        else:
            self.cleanup_task = self.loop.create_task(coro_cleanup)
            
        # Periodic version and updates checker task
        coro_update = self.check_version_updates_loop()
        if type(loop).__name__ in ("MagicMock", "Mock", "AsyncMock"):
            self.update_check_task = None
            coro_update.close()
        else:
            self.update_check_task = self.loop.create_task(coro_update)
        
        if config["SAVE_ATTACHMENTS"]:
            log.info("Configured to save attachments to 'attachments' directory")

    def log_action(self, action_type: str, sender: str, topic: str, payload: str, success: bool) -> None:
        """Helper to thread-safely record an action status update."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_publish_success = success
        self.last_publish_time = timestamp
        if success:
            self.processed_messages_count += 1
            status = "SUCCESS"
        else:
            status = "FAILED"
            
        action = {
            "timestamp": timestamp,
            "type": action_type,
            "sender": sender,
            "topic": topic,
            "payload": payload,
            "status": status,
        }
        self.recent_actions.insert(0, action)
        if len(self.recent_actions) > 20:
            self.recent_actions.pop()
        self.save_status_file()

    def save_status_file(self) -> None:
        """Saves current status JSON to status.json on disk for PHP WebAdmin (non-blocking)."""
        if hasattr(self, "loop") and self.loop and self.loop.is_running():
            self.loop.create_task(asyncio.to_thread(self._write_status_file_sync))
        else:
            self._write_status_file_sync()

    def _write_status_file_sync(self) -> None:
        data_dir = get_data_dir()
        try:
            os.makedirs(data_dir, exist_ok=True)
            status_file = os.path.join(data_dir, "status.json")
            with open(status_file, "w", encoding="utf-8") as f:
                json.dump(self.get_status_json(), f, indent=2)
            try:
                os.chmod(status_file, 0o666)
            except Exception:
                pass
        except Exception as e:
            log.error("Failed to write status.json: %s", e)

    def _on_mqtt_connect(self, client: Any, userdata: Any, flags: Dict[str, Any], rc: int, properties: Any = None) -> None:
        if rc == 0:
            log.info("Persistent MQTT client connected successfully to %s:%s", config["MQTT_HOST"], config["MQTT_PORT"])
            self.mqtt_connected_status = True
        else:
            log.error("Persistent MQTT client failed to connect: return code %s", rc)
            self.mqtt_connected_status = False
        self.save_status_file()

    def _on_mqtt_disconnect(self, client: Any, userdata: Any, disconnect_flags: Any, rc: int, properties: Any = None) -> None:
        log.warning("Persistent MQTT client disconnected: return code %s", rc)
        self.mqtt_connected_status = False
        self.save_status_file()

    def is_ip_allowed(self, peer_ip: Optional[str]) -> bool:
        """Verifies whether client peer_ip is permitted by ALLOWED_IPS config."""
        allowed_ips_setting = str(config.get("ALLOWED_IPS", "")).strip()
        if not allowed_ips_setting or allowed_ips_setting == "*":
            return True
        if not peer_ip:
            return False

        try:
            client_addr = ipaddress.ip_address(peer_ip)
        except ValueError:
            return False

        for net_str in allowed_ips_setting.split(","):
            net_str = net_str.strip()
            if not net_str:
                continue
            if net_str == "*":
                return True
            try:
                if "/" not in net_str:
                    net = ipaddress.ip_network(f"{net_str}/32", strict=False)
                else:
                    net = ipaddress.ip_network(net_str, strict=False)
                if client_addr in net:
                    return True
            except ValueError as e:
                log.warning("Invalid IP network pattern in ALLOWED_IPS: %s (%s)", net_str, e)

        return False

    async def handle_CONNECT(self, server: Any, session: Any, envelope: Any) -> str:
        """Enforces IP Whitelist filtering on incoming SMTP connections."""
        peer_ip = session.peer[0] if session and hasattr(session, "peer") and session.peer else None
        if not self.is_ip_allowed(peer_ip):
            log.warning("Rejected SMTP connection from unauthorized IP: %s", peer_ip)
            if peer_ip:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if not hasattr(self, "recent_blocked_attempts"):
                    self.recent_blocked_attempts = []
                found = False
                for attempt in self.recent_blocked_attempts:
                    if attempt.get("ip") == peer_ip:
                        attempt["count"] = attempt.get("count", 1) + 1
                        attempt["timestamp"] = timestamp
                        found = True
                        break
                if not found:
                    self.recent_blocked_attempts.insert(0, {
                        "ip": peer_ip,
                        "timestamp": timestamp,
                        "count": 1
                    })
                    if len(self.recent_blocked_attempts) > 10:
                        self.recent_blocked_attempts.pop()
                self.log_action("security", peer_ip, "smtp/connect", "554 IP Blocked", False)
            return f"554 5.7.1 Access denied: IP address {peer_ip} not allowed"
        return "220 Welcome to smtp2mqtt"

    async def handle_MAIL(self, server: Any, session: Any, envelope: Any, address: str, mail_options: List[str]) -> str:
        """Processes MAIL FROM command with instant Early-Trigger (< 10 ms latency)."""
        envelope.mail_from = address
        if hasattr(envelope, "mail_options") and isinstance(envelope.mail_options, list):
            envelope.mail_options.extend(mail_options)

        log.info("Received SMTP MAIL FROM from %s", address)

        # Construct topic based on sender, sanitizing dangerous MQTT wildcard characters
        sanitized_sender = (
            address.replace("@", "-")
            .replace("/", "_")
            .replace("+", "_")
            .replace("#", "_")
        )
        topic = f"{config['MQTT_TOPIC']}/{sanitized_sender}"
        setattr(envelope, "_early_triggered_topic", topic)

        # Check if topic is currently triggered (in reset time window)
        is_triggered = topic in self.handles

        if not is_triggered:
            log.debug("Early-dispatching MQTT publish for trigger payload on MAIL FROM...")
            await asyncio.to_thread(self.mqtt_publish, topic, config["MQTT_PAYLOAD"], "trigger", address)
        else:
            log.info("Topic %s is already in triggered state. Extending reset timer (Variant B) without duplicate ON publish.", topic)
            self.log_action("trigger (extended)", address, topic, config["MQTT_PAYLOAD"], True)

        # Cancel existing reset timer if active and reschedule for new window (sliding window)
        if topic in self.handles:
            log.debug("Cancelling existing reset timer for topic: %s", topic)
            self.handles.pop(topic).cancel()

        # Schedule a new reset timer in seconds
        if self.reset_time > 0:
            reset_time_seconds = float(self.reset_time)
            log.debug("Scheduling topic reset in %.3f seconds: %s", reset_time_seconds, topic)
            self.handles[topic] = self.loop.call_later(
                reset_time_seconds, self._trigger_reset, topic
            )

        return "250 OK"

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:
        """Processes incoming SMTP email messages."""
        mail_from = envelope.mail_from
        log.info("Received SMTP DATA payload from %s", mail_from)

        sanitized_sender = (
            mail_from.replace("@", "-")
            .replace("/", "_")
            .replace("+", "_")
            .replace("#", "_")
        )
        topic = f"{config['MQTT_TOPIC']}/{sanitized_sender}"

        # Fallback check: if handle_MAIL was not called or didn't trigger
        early_triggered_topic = getattr(envelope, "_early_triggered_topic", None)
        if early_triggered_topic != topic:
            is_triggered = topic in self.handles
            if not is_triggered:
                log.debug("Fallback dispatching MQTT publish for trigger payload in handle_DATA...")
                await asyncio.to_thread(self.mqtt_publish, topic, config["MQTT_PAYLOAD"], "trigger", mail_from)
            else:
                log.info("Topic %s is already in triggered state in handle_DATA. Extending reset timer.", topic)
                self.log_action("trigger (extended)", mail_from, topic, config["MQTT_PAYLOAD"], True)

            if topic in self.handles:
                self.handles.pop(topic).cancel()

            if self.reset_time > 0:
                reset_time_seconds = float(self.reset_time)
                self.handles[topic] = self.loop.call_later(
                    reset_time_seconds, self._trigger_reset, topic
                )

        # Determine whether to save attachments - always save if enabled
        should_save = config["SAVE_ATTACHMENTS"]
        if should_save:
            log.debug("Dispatching background attachment save task...")
            is_triggered = topic in self.handles
            task = self.loop.create_task(
                self._process_attachments_background(envelope.original_content, topic, mail_from, is_triggered)
            )
            self.background_tasks.add(task)
        else:
            log.debug("Skipping attachment storage (disabled in config)")

        return "250 Message accepted for delivery"

    async def _process_attachments_background(self, original_content: bytes, topic: str, mail_from: str, is_triggered: bool) -> None:
        """Parses the email content and saves attachments in the background."""
        try:
            # Parse the email message bytes in an executor to avoid blocking the main event loop
            msg = await asyncio.to_thread(email.message_from_bytes, original_content, policy=default)
            
            # Save attachments in the thread executor
            saved_attachments = await asyncio.to_thread(self.save_attachments, msg, topic, is_triggered)
            
            # Associate attachments with the recent trigger action
            if saved_attachments and self.recent_actions:
                for action in self.recent_actions:
                    if (
                        action["type"] == "trigger"
                        and action["sender"] == mail_from
                        and action["topic"] == topic
                    ):
                        action["attachments"] = saved_attachments
                        log.debug("Associated %d saved attachments with trigger action", len(saved_attachments))
                        break
        except Exception:
            log.exception("Error processing email message or attachments in the background")
        finally:
            task = asyncio.current_task()
            if task in self.background_tasks:
                self.background_tasks.remove(task)

    def save_attachments(self, msg: Any, topic: str, is_triggered: bool) -> List[Dict[str, Any]]:
        """Iterates through and saves image attachments to the local filesystem.
        
        Returns:
            A list of dicts with keys "filename" and "path" of the saved attachments.
        """
        saved_files = []
        try:
            log.debug(
                "Saving attachments. Topic '%s' already triggered: %s, "
                "Save during reset override: %s",
                topic,
                is_triggered,
                config["SAVE_ATTACHMENTS_DURING_RESET_TIME"],
            )
            
            for part in msg.iter_attachments():
                content_type = part.get_content_type()
                # Hikvision camera emails typically attach images
                if not content_type.startswith("image"):
                    log.debug("Skipping non-image attachment of type: %s", content_type)
                    continue

                filename = part.get_filename()
                if not filename:
                    log.debug("Attachment has no filename, skipping")
                    continue

                # Prevent Path Traversal (CWE-22) by extracting only the base filename
                safe_filename = os.path.basename(filename)
                if not safe_filename:
                    log.debug("Sanitized attachment filename is empty, skipping")
                    continue

                image_data = part.get_content()
                att_dir = get_attachments_dir()
                file_path = os.path.join(att_dir, safe_filename)
                
                log.info("Saving attached image '%s' to '%s'", safe_filename, file_path)
                with open(file_path, "wb") as f:
                    f.write(image_data)
                
                saved_files.append({
                    "filename": safe_filename,
                    "path": os.path.abspath(file_path)
                })
        except Exception:
            log.exception("Exception occurred while saving attachments")
        return saved_files

    def mqtt_publish(self, topic: str, payload: str, action_type: str = "trigger", sender: str = "system", wait_for_publish: bool = False) -> None:
        """Publishes a payload to MQTT broker."""
        log.info("Publishing payload '%s' to topic '%s'", payload, topic)
        success = False
        try:
            if hasattr(self, "_mqtt_client") and self._mqtt_client is not None:
                # Send instantly and asynchronously via the persistent background client connection
                info = self._mqtt_client.publish(topic, payload, qos=0)
                if wait_for_publish:
                    info.wait_for_publish(timeout=2.0)
                    success = info.is_published()
                else:
                    success = (info.rc == mqtt.MQTT_ERR_SUCCESS)
            else:
                # Fallback to single publish if persistent client is not active (e.g. mock testing)
                auth_dict = None
                if config["MQTT_USERNAME"]:
                    auth_dict = {
                        "username": config["MQTT_USERNAME"],
                        "password": config["MQTT_PASSWORD"],
                    }

                publish.single(
                    topic,
                    payload,
                    hostname=config["MQTT_HOST"],
                    port=config["MQTT_PORT"],
                    auth=auth_dict,
                )
                success = True
        except Exception as e:
            log.error("Failed to publish MQTT message to %s: %s", topic, e, exc_info=True)
        finally:
            self.log_action(action_type, sender, topic, payload, success)

    def _trigger_reset(self, topic: str) -> None:
        """Callback scheduled by call_later. Triggers topic reset back to default payload."""
        if topic in self.handles:
            self.handles.pop(topic)
        log.info("Reset timer expired. Resetting topic: %s", topic)
        
        # Schedule the fast-path publish or thread-fallback
        if hasattr(self, "_mqtt_client") and self._mqtt_client is not None:
            self.mqtt_publish(topic, config["MQTT_RESET_PAYLOAD"], "reset", "system", wait_for_publish=False)
        else:
            asyncio.create_task(
                asyncio.to_thread(self.mqtt_publish, topic, config["MQTT_RESET_PAYLOAD"], "reset", "system", False)
            )

    def cancel_all_resets(self) -> None:
        """Cancels all currently pending reset timers and background tasks (used for graceful shutdown)."""
        if hasattr(self, "monitor_task") and self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
        if hasattr(self, "monitor_smtp_task") and self.monitor_smtp_task and not self.monitor_smtp_task.done():
            self.monitor_smtp_task.cancel()
        if hasattr(self, "cleanup_task") and self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
        if hasattr(self, "update_check_task") and self.update_check_task and not self.update_check_task.done():
            self.update_check_task.cancel()
        
        # Cancel any active background attachment tasks
        if hasattr(self, "background_tasks") and self.background_tasks:
            log.info("Cancelling %d background attachment tasks...", len(self.background_tasks))
            for task in list(self.background_tasks):
                task.cancel()
            self.background_tasks.clear()
        
        # Stop and disconnect persistent MQTT client
        if hasattr(self, "_mqtt_client") and self._mqtt_client is not None:
            log.info("Stopping persistent MQTT client loop...")
            try:
                self._mqtt_client.loop_stop()
                self._mqtt_client.disconnect()
            except Exception as e:
                log.error("Error stopping persistent MQTT client: %s", e)

        if not self.handles:
            return
        log.info("Cancelling %d active reset timers...", len(self.handles))
        for topic, handle in list(self.handles.items()):
            handle.cancel()
        self.handles.clear()

    async def run_periodic_cleanup(self) -> None:
        """Periodically scans and cleans up old attachments and log files."""
        interval = config["CLEANUP_INTERVAL_SECONDS"]
        log.info("Starting periodic file cleanup task (interval: %d seconds)", interval)
        try:
            while True:
                await self.perform_cleanup()
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            log.info("Periodic file cleanup task cancelled.")
        except Exception as e:
            log.exception("Unexpected error in periodic cleanup loop: %s", e)

    async def perform_cleanup(self) -> None:
        """Deletes files in attachments and log directories that exceed configuration thresholds."""
        attachments_days = config["CLEANUP_ATTACHMENTS_DAYS"]
        logs_days = config["CLEANUP_LOGS_DAYS"]

        log.debug("Initiating automatic directory cleanup check...")
        
        # Cleanup attachments folder
        if config["SAVE_ATTACHMENTS"] and attachments_days > 0:
            await asyncio.to_thread(self._cleanup_directory, get_attachments_dir(), attachments_days)

        # Cleanup log folder
        if logs_days > 0:
            log_dir_target = loxberry_paths.get("LBPLOG", "log")
            await asyncio.to_thread(self._cleanup_directory, log_dir_target, logs_days)

    def _cleanup_directory(self, directory: str, max_age_days: int) -> None:
        """Safely scans a directory and deletes files older than max_age_days."""
        import time
        if not os.path.exists(directory) or not os.path.isdir(directory):
            return

        now = time.time()
        cutoff_timestamp = now - (max_age_days * 86400)
        deleted_count = 0

        try:
            for filename in os.listdir(directory):
                # Avoid deleting .gitkeep or other hidden system files
                if filename.startswith("."):
                    continue
                file_path = os.path.join(directory, filename)
                if os.path.isfile(file_path):
                    mtime = os.path.getmtime(file_path)
                    if mtime < cutoff_timestamp:
                        try:
                            os.remove(file_path)
                            deleted_count += 1
                            log.debug("Deleted old file: %s", file_path)
                        except Exception as delete_error:
                            log.error("Failed to delete %s: %s", file_path, delete_error)
            if deleted_count > 0:
                log.info("Directory cleanup of '%s' completed: deleted %d files older than %d days", directory, deleted_count, max_age_days)
        except Exception as scan_error:
            log.error("Failed to scan directory '%s' for cleanup: %s", directory, scan_error)

    async def check_version_updates_loop(self) -> None:
        """Periodically checks GitHub API for newer container versions (disabled in LoxBerry environment)."""
        if loxberry_paths.get("LBHOME"):
            log.info("LoxBerry environment detected. Skipping automatic GitHub version check (managed by LoxBerry Plugin Manager).")
            self.version_check_status = "disabled_loxberry"
            return

        # Initial safety delay to ensure startup is unblocked and fast
        await asyncio.sleep(2)
        log.info("Starting periodic version check task (interval: 24h)")
        try:
            while True:
                await self.perform_version_check()
                # Sleep for 24 hours (86400 seconds)
                await asyncio.sleep(86400)
        except asyncio.CancelledError:
            log.info("Periodic version check task cancelled.")
        except Exception as e:
            log.exception("Unexpected error in periodic version check loop: %s", e)

    async def perform_version_check(self) -> None:
        """Queries GitHub for the latest version and compares it to the local version."""
        self.version_check_status = "checking"
        try:
            latest = await asyncio.to_thread(self._fetch_latest_release_from_github)
            if latest:
                self.latest_version = latest
                self.update_available = self._is_update_available(VERSION, latest)
                self.version_check_status = "success"
                if self.update_available:
                    log.info("Newer version available on GitHub: %s (current: %s)", latest, VERSION)
                else:
                    log.info("smtp2mqtt is up to date (current: %s, latest: %s)", VERSION, latest)
            else:
                self.version_check_status = "failed"
        except Exception as e:
            self.version_check_status = "failed"
            log.error("Failed to perform version check: %s", e)

    def _fetch_latest_release_from_github(self) -> Optional[str]:
        """Queries the GitHub Releases API to fetch the latest tag_name."""
        url = "https://api.github.com/repos/onhala/smtp2mqtt/releases/latest"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": f"smtp2mqtt-gateway/{VERSION}"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    return data.get("tag_name")
        except urllib.error.HTTPError as e:
            log.warning("GitHub Releases API returned status %d. Cached latest_version remains %s", e.code, self.latest_version)
        except Exception as e:
            log.warning("Failed to connect to GitHub Releases API: %s. Cached latest_version remains %s", e, self.latest_version)
        return None

    def _is_update_available(self, current: str, latest: Optional[str]) -> bool:
        """Compares current and latest version semver strings to check if an update is available."""
        if not latest:
            return False
        curr_clean = current.strip().lower().lstrip('v')
        lat_clean = latest.strip().lower().lstrip('v')
        
        if curr_clean == lat_clean:
            return False
            
        try:
            curr_parts = [int(x) for x in curr_clean.split('.')]
            lat_parts = [int(x) for x in lat_clean.split('.')]
            max_len = max(len(curr_parts), len(lat_parts))
            curr_parts += [0] * (max_len - len(curr_parts))
            lat_parts += [0] * (max_len - len(lat_parts))
            return lat_parts > curr_parts
        except ValueError:
            return lat_clean > curr_clean

    async def monitor_mqtt_broker(self) -> None:
        """Periodically checks connection to the MQTT broker and logs status changes."""
        host = config["MQTT_HOST"]
        port = config["MQTT_PORT"]
        log.info("Starting MQTT broker connectivity monitor for %s:%d", host, port)
        while True:
            try:
                is_socket_open = await asyncio.to_thread(self._check_socket_connection, host, port)
                
                if self.mqtt_connected_status is None:
                    if self._mqtt_client is None or not is_socket_open:
                        self.mqtt_connected_status = is_socket_open
                        if is_socket_open:
                            log.info("Initial MQTT connectivity check: Online")
                        else:
                            log.warning("Initial MQTT connectivity check: Offline (Broker at %s:%d is unreachable)", host, port)
                            self.log_action("system", "system", f"MQTT Broker ({host}:{port})", "Offline (Unreachable)", False)
                else:
                    if not is_socket_open:
                        if self.mqtt_connected_status is not False:
                            self.mqtt_connected_status = False
                            log.warning("MQTT broker at %s:%d is offline (Unreachable)", host, port)
                            self.log_action("system", "system", f"MQTT Broker ({host}:{port})", "Offline (Unreachable)", False)
                    else:
                        if self._mqtt_client is None and not self.mqtt_connected_status:
                            self.mqtt_connected_status = True
                            log.info("MQTT broker at %s:%d has reconnected (Online)", host, port)
                            self.log_action("system", "system", f"MQTT Broker ({host}:{port})", "Online (Reconnected)", True)
            except Exception as e:
                log.error("Error in MQTT broker monitor: %s", e)
            
            self.save_status_file()
            try:
                await asyncio.sleep(10)  # Check every 10 seconds
            except asyncio.CancelledError:
                break

    def _check_socket_connection(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except Exception:
            return False

    async def monitor_smtp_server(self) -> None:
        """Periodically checks the SMTP server status and logs status changes."""
        port = config["SMTP_PORT"]
        log.info("Starting SMTP server connectivity monitor on port %d", port)
        while True:
            try:
                # Direct check of SMTP controller's internal state if available
                is_available = False
                if hasattr(self, "smtp_controller") and self.smtp_controller is not None:
                    try:
                        is_available = (
                            self.smtp_controller.server is not None
                            and self.smtp_controller.server.is_serving()
                        )
                    except Exception:
                        is_available = False
                
                # Check actual socket reachability as fallback/verification
                if not is_available:
                    is_available = await asyncio.to_thread(self._check_socket_connection, "127.0.0.1", port)
                
                if self.smtp_connected_status_val is None:
                    # Initial state
                    self.smtp_connected_status_val = is_available
                    if is_available:
                        log.info("Initial SMTP server connectivity check: Active")
                    else:
                        log.warning("Initial SMTP server connectivity check: Inactive (SMTP server on port %d is unreachable)", port)
                elif self.smtp_connected_status_val != is_available:
                    # Change in state
                    self.smtp_connected_status_val = is_available
                    if is_available:
                        log.info("SMTP server on port %d is active (Active)", port)
                    else:
                        log.warning("SMTP server on port %d is inactive (Unreachable)", port)
            except Exception as e:
                log.error("Error in SMTP server monitor: %s", e)
            
            self.save_status_file()
            try:
                await asyncio.sleep(10)  # Check every 10 seconds
            except asyncio.CancelledError:
                break

    @property
    def smtp_connected_status(self) -> bool:
        """Checks if the local SMTP server is active and serving."""
        return self.smtp_connected_status_val if self.smtp_connected_status_val is not None else False

    def get_status_json(self) -> Dict[str, Any]:
        """Generates dynamic JSON status data for gethomepage.dev and other dashboard widgets."""
        uptime = int((datetime.now() - self.start_time).total_seconds())
        
        mqtt_ok = self.mqtt_connected_status if self.mqtt_connected_status is not None else False
        smtp_ok = self.smtp_connected_status
        
        mqtt_status_text = "Connected" if mqtt_ok else "Disconnected"
        smtp_status_text = "Active" if smtp_ok else "Inactive"
        
        if uptime < 60:
            uptime_formatted = f"{uptime}s"
        elif uptime < 3600:
            minutes = uptime // 60
            seconds = uptime % 60
            uptime_formatted = f"{minutes}m {seconds}s"
        else:
            hours = uptime // 3600
            minutes = (uptime % 3600) // 60
            uptime_formatted = f"{hours}h {minutes}m"

        return {
            "status": "online",
            "mqtt_host": config["MQTT_HOST"],
            "mqtt_port": config["MQTT_PORT"],
            "mqtt_connected": mqtt_ok,
            "mqtt_status_text": mqtt_status_text,
            "smtp_port": config["SMTP_PORT"],
            "smtp_connected": smtp_ok,
            "smtp_status_text": smtp_status_text,
            "last_publish_success": self.last_publish_success,
            "last_publish_time": self.last_publish_time,
            "processed_messages_count": self.processed_messages_count,
            "uptime_seconds": uptime,
            "uptime_formatted": uptime_formatted,
            "recent_actions": self.recent_actions,
            "recent_blocked_attempts": getattr(self, "recent_blocked_attempts", []),
            "version": VERSION,
            "latest_version": self.latest_version,
            "update_available": self.update_available,
            "version_check_status": self.version_check_status,
        }

    def get_dashboard_html(self) -> str:
        """Returns the complete, responsive, premium dark mode HTML dashboard."""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>smtp2mqtt Gateway Dashboard</title>
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0f14;
            --card-bg: #161b22;
            --border-color: #30363d;
            --border-focus: #444c56;
            --text-primary: #f0f6fc;
            --text-secondary: #c9d1d9;
            --text-muted: #8b949e;
            
            --accent-primary: #7ec127;
            --accent-glow: rgba(126, 193, 39, 0.12);
            --accent-hover: #90d635;
            
            --success: #7ec127;
            --success-glow: rgba(126, 193, 39, 0.15);
            --danger: #f85149;
            --danger-glow: rgba(248, 81, 73, 0.15);
            --warning: #d29922;
            --warning-glow: rgba(210, 153, 34, 0.15);
        }
    </style>
</head>
<body>
    <h1>smtp2mqtt</h1>
</body>
</html>"""

def register_loxberry_log(paths: Dict[str, str]) -> None:
    """Registers smtp2mqtt.log in LoxBerry system log database if in LoxBerry environment."""
    log_dir = paths.get("LBPLOG")
    lb_home = paths.get("LBHOME")
    if not log_dir or not lb_home:
        return

    log_file = os.path.join(log_dir, "smtp2mqtt.log")
    perl_cmd = f"use LoxBerry::Log; my $log = LoxBerry::Log->new(name => 'smtp2mqtt', filename => '{log_file}', append => 1, stderr => 1); $log->open();"
    try:
        subprocess.run(["perl", "-e", perl_cmd], capture_output=True, timeout=5)
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to register log in LoxBerry LogDB: {e}\n")


def main():
    if "LBHOME" in loxberry_paths:
        register_loxberry_log(loxberry_paths)

    log.info("Starting smtp2mqtt gateway...")

    log.debug("Configuration: %s", ", ".join([f"{k}={v}" for k, v in config.items()]))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    handler = smtp2mqttHandler(loop)
    
    # Use UnthreadedController to run in the main asyncio event loop
    controller = UnthreadedController(
        handler=handler,
        loop=loop,
        hostname=config.get("SMTP_HOST", "0.0.0.0"),
        port=config["SMTP_PORT"],
    )
    handler.smtp_controller = controller

    # Start the controller synchronously (schedules the server creation inside loop)
    controller.begin()
    log.info("SMTP server is listening on %s:%d", config.get("SMTP_HOST", "0.0.0.0"), config["SMTP_PORT"])

    # Start the web server if enabled
    web_server = None
    if config["ENABLE_WEB"]:
        try:
            web_server = loop.run_until_complete(
                asyncio.start_server(
                    handler.handle_web_client,
                    "0.0.0.0",
                    config["WEB_PORT"]
                )
            )
            log.info("Web server is listening on http://0.0.0.0:%d", config["WEB_PORT"])
        except Exception as e:
            log.error("Failed to start web server on port %d: %s", config["WEB_PORT"], e)

    # Graceful shutdown orchestration
    def handle_shutdown():
        log.info("Received termination signal. Stopping event loop...")
        loop.stop()

    # Register OS signals
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, handle_shutdown)
        except Exception:
            log.warning("Could not register signal handler for %s", sig)

    try:
        # Keep the event loop running forever
        loop.run_forever()
    except Exception:
        log.exception("Unhandled exception in event loop")
    finally:
        log.info("Stopping SMTP server...")
        try:
            controller.end()
        except Exception:
            log.exception("Error while stopping SMTP controller")
        
        if web_server:
            log.info("Stopping Web server...")
            web_server.close()
            try:
                loop.run_until_complete(web_server.wait_closed())
            except Exception:
                pass
        
        # Cancel any remaining pending reset tasks
        handler.cancel_all_resets()
        
        # Close the loop
        loop.close()
        log.info("smtp2mqtt gateway stopped successfully.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Process interrupted by user. Exiting.")
    except Exception:
        log.exception("Unhandled exception in main execution loop")
        sys.exit(1)
