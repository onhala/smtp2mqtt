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
    lb_home = os.environ.get("LBHOME", "/opt/loxberry" if os.path.exists("/opt/loxberry") else None)
    if lb_home and os.path.exists(lb_home):
        paths["LBHOME"] = lb_home
        paths["LBPDATA"] = os.environ.get("LBPDATA", os.path.join(lb_home, "data", "plugins", "smtp2mqtt"))
        paths["LBPLOG"] = os.environ.get("LBPLOG", os.path.join(lb_home, "log", "plugins", "smtp2mqtt"))
        paths["LBPCONFIG"] = os.environ.get("LBPCONFIG", os.path.join(lb_home, "config", "plugins", "smtp2mqtt"))
        paths["LBPMQTT_JSON"] = os.path.join(lb_home, "config", "system", "mqttgateway.json")
        paths["LBPMQTT_INI"] = os.path.join(lb_home, "config", "system", "mqttgateway.ini")
    return paths


def load_loxberry_mqtt_config(paths: Dict[str, str]) -> Dict[str, Any]:
    """Auto-detect MQTT broker configuration from LoxBerry MQTT Gateway V2."""
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
    # Cascading value resolution
    val = default_val
    if setting in lb_mqtt_defaults:
        val = lb_mqtt_defaults[setting]
    if setting in file_defaults:
        val = file_defaults[setting]
    env_val = os.environ.get(setting, val)

    if setting in ("SAVE_ATTACHMENTS", "SAVE_ATTACHMENTS_DURING_RESET_TIME", "DEBUG", "ENABLE_WEB"):
        config[setting] = parse_bool(env_val)
    elif setting in ("SMTP_PORT", "MQTT_PORT", "MQTT_RESET_TIME", "WEB_PORT", "CLEANUP_ATTACHMENTS_DAYS", "CLEANUP_LOGS_DAYS", "CLEANUP_INTERVAL_SECONDS"):
        try:
            config[setting] = int(env_val)
        except ValueError:
            config[setting] = int(default_val)
    else:
        config[setting] = env_val

# Logging configuration
level = logging.DEBUG if config["DEBUG"] else logging.INFO
log = logging.getLogger("smtp2mqtt")
log.setLevel(level)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Log to console
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(formatter)
log.addHandler(ch)

# File logging path resolution (LoxBerry log dir prioritized if available)
log_dir = loxberry_paths.get("LBPLOG") if "LBPLOG" in loxberry_paths else ("log" if os.path.exists("log") else None)
if log_dir:
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "smtp2mqtt.log")
        log.info(f"Setting up file logger at {log_file}")
        fh = logging.FileHandler(log_file)
        fh.setFormatter(formatter)
        log.addHandler(fh)
    except Exception as e:
        log.error(f"Failed to set up file logger: {e}. Continuing with console-only logging.")


VERSION = "1.8.15"


class smtp2mqttHandler:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.reset_time: int = config["MQTT_RESET_TIME"]
        self.handles: Dict[str, asyncio.TimerHandle] = {}
        self.background_tasks = set()
        
        # State tracking for Web Status Dashboard and gethomepage.dev
        self.start_time = datetime.now()
        self.processed_messages_count = 0
        self.last_publish_success: Optional[bool] = None
        self.last_publish_time: Optional[str] = None
        self.recent_actions: List[Dict[str, Any]] = []  # List of dicts
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
                self._mqtt_client.username_pw_set(config["MQTT_USERNAME"], config["MQTT_PASSWORD"])
            self._mqtt_client.on_connect = self._on_mqtt_connect
            self._mqtt_client.on_disconnect = self._on_mqtt_disconnect
            
            # Start background thread loop and initiate asynchronous connection
            self._mqtt_client.loop_start()
            try:
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

    def _on_mqtt_connect(self, client: Any, userdata: Any, flags: Dict[str, Any], rc: int, properties: Any = None) -> None:
        if rc == 0:
            log.info("Persistent MQTT client connected successfully.")
            self.mqtt_connected_status = True
        else:
            log.error("Persistent MQTT client failed to connect: return code %s", rc)
            self.mqtt_connected_status = False

    def _on_mqtt_disconnect(self, client: Any, userdata: Any, disconnect_flags: Any, rc: int, properties: Any = None) -> None:
        log.warning("Persistent MQTT client disconnected: return code %s", rc)
        self.mqtt_connected_status = False

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:
        """Processes incoming SMTP email messages."""
        mail_from = envelope.mail_from
        log.info("Received SMTP message from %s", mail_from)

        # Construct topic based on sender, sanitizing dangerous MQTT wildcard characters
        sanitized_sender = (
            mail_from.replace("@", "-")
            .replace("/", "_")
            .replace("+", "_")
            .replace("#", "_")
        )
        topic = f"{config['MQTT_TOPIC']}/{sanitized_sender}"

        # Publish the primary payload asynchronously (in a thread executor to not block loop)
        log.debug("Dispatching MQTT publish for trigger payload...")
        await asyncio.to_thread(self.mqtt_publish, topic, config["MQTT_PAYLOAD"], "trigger", mail_from)

        # Determine whether to save attachments
        is_triggered = topic in self.handles
        should_save = config["SAVE_ATTACHMENTS"] and (
            not is_triggered or config["SAVE_ATTACHMENTS_DURING_RESET_TIME"]
        )

        if should_save:
            log.debug("Dispatching background attachment save task...")
            # Schedule non-blocking background task to parse email and save attachments
            task = self.loop.create_task(
                self._process_attachments_background(envelope.original_content, topic, mail_from, is_triggered)
            )
            self.background_tasks.add(task)
        else:
            log.debug("Skipping attachment storage (disabled or reset time constraint)")

        # Cancel any pending reset timers for this topic
        if topic in self.handles:
            log.debug("Cancelling existing reset timer for topic: %s", topic)
            self.handles.pop(topic).cancel()

        # Schedule a new reset timer if reset time is non-zero
        if self.reset_time > 0:
            log.debug("Scheduling topic reset in %d seconds: %s", self.reset_time, topic)
            self.handles[topic] = self.loop.call_later(
                self.reset_time, self._trigger_reset, topic
            )

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
        """Periodically checks GitHub API for newer container versions."""
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
                is_available = await asyncio.to_thread(self._check_socket_connection, host, port)
                
                if self.mqtt_connected_status is None:
                    # Initial state
                    self.mqtt_connected_status = is_available
                    if is_available:
                        log.info("Initial MQTT connectivity check: Online")
                    else:
                        log.warning("Initial MQTT connectivity check: Offline (Broker at %s:%d is unreachable)", host, port)
                        self.log_action("system", "system", f"MQTT Broker ({host}:{port})", "Offline (Unreachable)", False)
                elif self.mqtt_connected_status != is_available:
                    # Change in state
                    self.mqtt_connected_status = is_available
                    if is_available:
                        log.info("MQTT broker at %s:%d has reconnected (Online)", host, port)
                        self.log_action("system", "system", f"MQTT Broker ({host}:{port})", "Online (Reconnected)", True)
                    else:
                        log.warning("MQTT broker at %s:%d is offline (Unreachable)", host, port)
                        self.log_action("system", "system", f"MQTT Broker ({host}:{port})", "Offline (Unreachable)", False)
            except Exception as e:
                log.error("Error in MQTT broker monitor: %s", e)
            
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
            /* Refined Premium High-Contrast Loxone Palette */
            --bg-color: #0b0f14;          /* Deep rich dark blue-black base */
            --card-bg: #161b22;           /* Crisp secondary charcoal background */
            --border-color: #30363d;       /* High-visibility contrast borders */
            --border-focus: #444c56;       /* Elevated active border color */
            --text-primary: #f0f6fc;       /* Off-white primary header for maximum readability */
            --text-secondary: #c9d1d9;     /* Light slate-gray for perfectly readable regular text */
            --text-muted: #8b949e;         /* Medium-gray for muted/secondary information */
            
            --accent-primary: #7ec127;     /* Vibrant Loxone Green */
            --accent-glow: rgba(126, 193, 39, 0.12);
            --accent-hover: #90d635;
            
            --success: #7ec127;
            --success-glow: rgba(126, 193, 39, 0.15);
            --danger: #ff7b72;             /* High-contrast pastel red for reliable dark mode errors */
            --danger-glow: rgba(255, 123, 114, 0.15);
            --system-color: #f0883e;       /* Warm orange for system actions */
            --system-glow: rgba(240, 136, 62, 0.12);
        }
        body.theme-loxberry, html[data-theme="loxberry"] {
            --bg-color: #f8fafc;
            --card-bg: #ffffff;
            --border-color: #e2e8f0;
            --border-focus: #cbd5e1;
            --text-primary: #0f172a;
            --text-secondary: #334155;
            --text-muted: #64748b;
            --accent-primary: #6fb738;
            --accent-glow: rgba(111, 183, 56, 0.15);
            --accent-hover: #5ea02f;
            --success: #2e7d32;
            --danger: #dc2626;
            --system-color: #d97706;
        }
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        body {
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-secondary);
            min-height: 100vh;
            padding: 3rem 2rem;
            display: flex;
            justify-content: center;
        }
        /* Custom Modern Scrollbars for extreme premium feel */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        ::-webkit-scrollbar-track {
            background: var(--bg-color);
        }
        ::-webkit-scrollbar-thumb {
            background: var(--border-color);
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: var(--border-focus);
        }

        .container {
            width: 100%;
            max-width: 1200px;
            display: flex;
            flex-direction: column;
            gap: 2.5rem;
        }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 2rem;
            border-bottom: 1px solid var(--border-color);
        }
        .title-area h1 {
            font-family: 'Share Tech Mono', monospace;
            font-size: 2.1rem;
            font-weight: 700;
            color: var(--accent-primary);
            text-shadow: 0 0 15px rgba(126, 193, 39, 0.35);
            margin-bottom: 0.35rem;
            letter-spacing: -0.01em;
        }
        .title-area p {
            color: var(--text-muted);
            font-size: 0.95rem;
            font-weight: 500;
        }
        .live-indicator {
            display: flex;
            align-items: center;
            gap: 0.625rem;
            background: var(--accent-glow);
            border: 1px solid rgba(126, 193, 39, 0.4);
            color: var(--accent-primary);
            padding: 0.5rem 1rem;
            border-radius: 6px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.8rem;
            font-weight: 600;
            letter-spacing: 0.08em;
            box-shadow: 0 0 10px rgba(126, 193, 39, 0.1);
        }
        .live-dot {
            width: 8px;
            height: 8px;
            background-color: var(--accent-primary);
            border-radius: 50%;
            box-shadow: 0 0 8px var(--accent-primary);
            animation: pulse-green 2s infinite;
        }
        @keyframes pulse-green {
            0% { box-shadow: 0 0 0 0 rgba(126, 193, 39, 0.5); }
            70% { box-shadow: 0 0 0 8px rgba(126, 193, 39, 0); }
            100% { box-shadow: 0 0 0 0 rgba(126, 193, 39, 0); }
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 1.75rem;
        }
        .card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-left: 4px solid var(--accent-primary);
            border-radius: 8px;
            padding: 1.75rem;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
            transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
        }
        .card:hover {
            border-color: var(--border-focus);
            box-shadow: 0 6px 30px rgba(126, 193, 39, 0.1);
            transform: translateY(-2px);
        }
        .card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 1.25rem;
        }
        .card-title {
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.875rem;
            color: var(--text-muted);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.1em;
        }
        .card-icon {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 2.25rem;
            height: 2.25rem;
            background: rgba(255, 255, 255, 0.04);
            border-radius: 6px;
            color: var(--text-muted);
        }
        .card-value {
            font-family: 'Share Tech Mono', monospace;
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
            color: var(--text-primary);
        }
        .card-subtext {
            font-size: 0.875rem;
            color: var(--text-muted);
            font-weight: 400;
        }
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            padding: 0.35rem 0.75rem;
            border-radius: 6px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.8rem;
            font-weight: 600;
            letter-spacing: 0.02em;
        }
        .status-badge.success {
            background-color: var(--success-glow);
            color: var(--accent-primary);
            border: 1px solid rgba(126, 193, 39, 0.4);
        }
        .status-badge.danger {
            background-color: var(--danger-glow);
            color: var(--danger);
            border: 1px solid rgba(255, 123, 114, 0.4);
        }
        .status-badge.secondary {
            background-color: rgba(255, 255, 255, 0.03);
            color: var(--text-secondary);
            border: 1px solid var(--border-color);
        }
        .panel {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.35);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .panel-header {
            padding: 1.75rem 2rem;
            border-bottom: 1px solid var(--border-color);
            background-color: rgba(0, 0, 0, 0.15);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .panel-title {
            font-family: 'Share Tech Mono', monospace;
            font-size: 1.25rem;
            font-weight: 600;
            color: var(--text-primary);
            letter-spacing: 0.02em;
        }
        .table-container {
            overflow-x: auto;
            max-height: 480px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.95rem;
        }
        th {
            padding: 1.25rem 2rem;
            font-family: 'Share Tech Mono', monospace;
            font-weight: 600;
            color: var(--text-muted);
            border-bottom: 2px solid var(--border-color);
            background-color: rgba(11, 15, 20, 0.8);
            position: sticky;
            top: 0;
            z-index: 10;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        td {
            padding: 1.25rem 2rem;
            border-bottom: 1px solid var(--border-color);
            color: var(--text-secondary);
            vertical-align: middle;
        }
        tr:last-child td {
            border-bottom: none;
        }
        tr:hover td {
            background-color: rgba(255, 255, 255, 0.015);
        }
        .type-badge {
            display: inline-flex;
            padding: 0.25rem 0.625rem;
            border-radius: 4px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.08em;
        }
        .type-badge.trigger {
            background-color: var(--accent-glow);
            color: var(--accent-primary);
            border: 1px solid rgba(126, 193, 39, 0.4);
        }
        .type-badge.reset {
            background-color: rgba(255, 255, 255, 0.04);
            color: var(--text-secondary);
            border: 1px solid var(--border-color);
        }
        .type-badge.system {
            background-color: var(--system-glow);
            color: var(--system-color);
            border: 1px solid rgba(240, 136, 62, 0.4);
        }
        .empty-state {
            padding: 5rem 2rem;
            text-align: center;
            color: var(--text-muted);
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 1rem;
            font-size: 1rem;
        }
        .empty-state svg {
            color: var(--text-muted);
            opacity: 0.5;
            margin-bottom: 0.5rem;
        }
        
        /* Modern Attachment Download Capsules */
        .attachment-item {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 0.5rem 0.75rem;
            transition: border-color 0.2s, background-color 0.2s;
        }
        .attachment-item:hover {
            border-color: var(--accent-primary);
            background: rgba(126, 193, 39, 0.04);
        }
        .attachment-link {
            transition: color 0.2s;
        }
        .update-badge {
            display: inline-flex;
            align-items: center;
            padding: 0.25rem 0.625rem;
            border-radius: 6px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.75rem;
            font-weight: 700;
            text-decoration: none;
            letter-spacing: 0.02em;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .update-badge.warning {
            background-color: rgba(240, 136, 62, 0.12);
            color: var(--system-color);
            border: 1px solid rgba(240, 136, 62, 0.4);
            box-shadow: 0 0 10px rgba(240, 136, 62, 0.05);
        }
        .update-badge.warning:hover {
            transform: translateY(-1px);
            box-shadow: 0 0 15px rgba(240, 136, 62, 0.2);
            background-color: rgba(240, 136, 62, 0.18);
        }
        .update-badge.success-badge {
            background-color: rgba(126, 193, 39, 0.08);
            color: var(--accent-primary);
            border: 1px solid rgba(126, 193, 39, 0.25);
        }
        .update-badge.pending-badge {
            background-color: rgba(255, 255, 255, 0.04);
            color: var(--text-muted);
            border: 1px solid var(--border-color);
        }
        .update-badge.failed-badge {
            background-color: rgba(239, 68, 68, 0.04);
            color: rgba(239, 68, 68, 0.85);
            border: 1px solid rgba(239, 68, 68, 0.25);
            cursor: help;
        }
        .update-pulse-gray {
            width: 6px;
            height: 6px;
            background-color: var(--text-muted);
            border-radius: 50%;
            box-shadow: 0 0 6px var(--text-muted);
            margin-right: 6px;
            animation: pulse-gray 2s infinite;
        }
        @keyframes pulse-gray {
            0% { box-shadow: 0 0 0 0 rgba(255, 255, 255, 0.2); }
            70% { box-shadow: 0 0 0 6px rgba(255, 255, 255, 0); }
            100% { box-shadow: 0 0 0 0 rgba(255, 255, 255, 0); }
        }
        .update-pulse {
            width: 6px;
            height: 6px;
            background-color: var(--system-color);
            border-radius: 50%;
            box-shadow: 0 0 6px var(--system-color);
            margin-right: 6px;
            animation: pulse-orange 2s infinite;
        }
        @keyframes pulse-orange {
            0% { box-shadow: 0 0 0 0 rgba(240, 136, 62, 0.6); }
            70% { box-shadow: 0 0 0 6px rgba(240, 136, 62, 0); }
            100% { box-shadow: 0 0 0 0 rgba(240, 136, 62, 0); }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="title-area" style="display: flex; align-items: center; gap: 1.25rem;">
                <img src="/logo.svg" alt="logo" style="width: 52px; height: 52px; display: block; filter: drop-shadow(0 0 10px rgba(126, 193, 39, 0.4));" />
                <div>
                    <h1 style="display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap;">
                        smtp2mqtt Gateway
                        <span class="version-tag" id="version-tag" style="font-size: 0.85rem; font-weight: 600; color: var(--text-muted); background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-color); padding: 0.15rem 0.5rem; border-radius: 4px; font-family: 'Share Tech Mono', monospace; text-shadow: none; letter-spacing: normal; display: inline-block;">v1.6.0</span>
                        <span id="update-badge-container" style="display: inline-block;"></span>
                    </h1>
                    <p>Asynchronous SMTP-to-MQTT Trigger Converter</p>
                </div>
            </div>
            <div class="live-indicator">
                <div class="live-dot"></div>
                LIVE STATS
            </div>
        </header>

        <div class="stats-grid">
            <!-- Gateway Status -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Gateway Uptime</span>
                    <div class="card-icon">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
                    </div>
                </div>
                <div class="card-value" id="uptime-text">0h 0m 0s</div>
                <div class="card-subtext">Total gateway running time</div>
            </div>

            <!-- SMTP Server Status -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">SMTP Server</span>
                    <div class="card-icon">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
                    </div>
                </div>
                <div class="card-value">
                    <span id="smtp-status" class="status-badge secondary">Checking...</span>
                </div>
                <div class="card-subtext">Listening on port <span id="smtp-port-info" style="font-weight: 600;">-</span></div>
            </div>

            <!-- MQTT Status -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">MQTT Connection</span>
                    <div class="card-icon">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
                    </div>
                </div>
                <div class="card-value">
                    <span id="mqtt-status" class="status-badge secondary">Checking...</span>
                </div>
                <div class="card-subtext" id="mqtt-broker-info">-</div>
            </div>

            <!-- Messages Processed -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Processed Messages</span>
                    <div class="card-icon">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                    </div>
                </div>
                <div class="card-value" id="processed-count">0</div>
                <div class="card-subtext">Last publish: <span id="last-publish-time" style="font-weight: 600;">Never</span></div>
            </div>
        </div>

        <!-- Recent Actions Panel -->
        <div class="panel">
            <div class="panel-header">
                <span class="panel-title">Recent Actions Log (Current Session)</span>
            </div>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Timestamp</th>
                            <th>Action Type</th>
                            <th>Sender (SMTP)</th>
                            <th>Target Topic (MQTT)</th>
                            <th>Value</th>
                            <th>Attachments</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody id="actions-table-body">
                        <tr>
                            <td colspan="7">
                                <div class="empty-state">
                                    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                                    Waiting for API data...
                                </div>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.get('theme') === 'loxberry') {
            document.documentElement.setAttribute('data-theme', 'loxberry');
            document.body.classList.add('theme-loxberry');
        }

        function escapeHtml(str) {
            if (!str) return '';
            return String(str)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }

        function formatUptime(seconds) {
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            const s = seconds % 60;
            return `${h}h ${m}m ${s}s`;
        }
        
        async function updateStats() {
            try {
                const res = await fetch('/api');
                const data = await res.json();
                
                document.getElementById('processed-count').innerText = data.processed_messages_count;
                document.getElementById('uptime-text').innerText = formatUptime(data.uptime_seconds);
                document.getElementById('last-publish-time').innerText = data.last_publish_time || 'Never';
                document.getElementById('mqtt-broker-info').innerText = `${data.mqtt_host}:${data.mqtt_port}`;
                document.getElementById('smtp-port-info').innerText = data.smtp_port || '-';
                
                const versionTag = document.getElementById('version-tag');
                if (versionTag && data.version) {
                    versionTag.innerText = `v${data.version}`;
                }
                const updateBadgeContainer = document.getElementById('update-badge-container');
                if (updateBadgeContainer) {
                    const status = data.version_check_status || 'pending';
                    if (status === 'pending' || status === 'checking') {
                        updateBadgeContainer.innerHTML = `
                            <span class="update-badge pending-badge">
                                <span class="update-pulse-gray"></span>
                                Checking updates...
                            </span>`;
                    } else if (status === 'success') {
                        if (data.update_available && data.latest_version) {
                            updateBadgeContainer.innerHTML = `
                                <a href="https://github.com/onhala/smtp2mqtt/releases/latest" target="_blank" class="update-badge warning">
                                    <span class="update-pulse"></span>
                                    Update Available: v${data.latest_version}
                                </a>`;
                        } else {
                            updateBadgeContainer.innerHTML = `
                                <span class="update-badge success-badge">
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" style="margin-right: 4px; display: inline-block; vertical-align: middle;"><polyline points="20 6 9 17 4 12"/></svg>
                                    Up to date
                                </span>`;
                        }
                    } else if (status === 'failed') {
                        updateBadgeContainer.innerHTML = `
                            <span class="update-badge failed-badge" title="Failed to check for updates. GitHub API may be rate-limited or offline.">
                                Update check failed
                            </span>`;
                    } else {
                        updateBadgeContainer.innerHTML = '';
                    }
                }
                
                const mqttStatusBadge = document.getElementById('mqtt-status');
                if (data.mqtt_connected) {
                    mqttStatusBadge.className = 'status-badge success';
                    mqttStatusBadge.innerHTML = '<span class="live-dot" style="background-color: var(--accent-primary); box-shadow: 0 0 8px var(--accent-primary); animation: pulse-green 2s infinite; width: 6px; height: 6px; margin-right: 4px;"></span>Connected';
                } else {
                    mqttStatusBadge.className = 'status-badge danger';
                    mqttStatusBadge.innerHTML = 'Disconnected';
                }
                
                const smtpStatusBadge = document.getElementById('smtp-status');
                if (data.smtp_connected) {
                    smtpStatusBadge.className = 'status-badge success';
                    smtpStatusBadge.innerHTML = '<span class="live-dot" style="background-color: var(--accent-primary); box-shadow: 0 0 8px var(--accent-primary); animation: pulse-green 2s infinite; width: 6px; height: 6px; margin-right: 4px;"></span>Active';
                } else {
                    smtpStatusBadge.className = 'status-badge danger';
                    smtpStatusBadge.innerHTML = 'Inactive';
                }
                
                const tbody = document.getElementById('actions-table-body');
                if (!data.recent_actions || data.recent_actions.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state">
                        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                        No actions captured in this session yet.
                    </div></td></tr>`;
                } else {
                    tbody.innerHTML = data.recent_actions.map(act => {
                        const statusClass = act.status === 'SUCCESS' ? 'status-badge success' : 'status-badge danger';
                        const typeLower = act.type.toLowerCase();
                        const typeClass = 'type-badge ' + (typeLower === 'trigger' ? 'trigger' : (typeLower === 'system' ? 'system' : 'reset'));
                        
                        let attsHtml = '<span style="color: var(--text-muted);">-</span>';
                        if (act.attachments && act.attachments.length > 0) {
                            attsHtml = act.attachments.map(att => {
                                const safeName = escapeHtml(att.filename);
                                const safePath = escapeHtml(att.path);
                                return `<div class="attachment-item" style="margin-bottom: 0.5rem;">
                                    <a href="/attachments/${safeName}" target="_blank" class="attachment-link" style="color: var(--accent-primary); text-decoration: none; font-weight: 600; font-family: 'Share Tech Mono', monospace; display: inline-flex; align-items: center; gap: 0.35rem;">
                                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
                                        ${safeName}
                                    </a>
                                    <div class="attachment-path" style="font-size: 0.75rem; color: #7fa384; font-family: 'Share Tech Mono', monospace; word-break: break-all; margin-top: 0.15rem;">${safePath}</div>
                                </div>`;
                            }).join('');
                        }

                        const topicColor = typeLower === 'system' ? 'var(--text-muted)' : 'var(--accent-primary)';

                        return `<tr>
                            <td style="white-space: nowrap; font-family: 'Share Tech Mono', monospace;">${escapeHtml(act.timestamp)}</td>
                            <td><span class="${typeClass}">${escapeHtml(act.type.toUpperCase())}</span></td>
                            <td style="font-family: 'Share Tech Mono', monospace;">${escapeHtml(act.sender)}</td>
                            <td style="font-family: 'Share Tech Mono', monospace; font-size: 0.875rem; color: ${topicColor};">${escapeHtml(act.topic)}</td>
                            <td><span style="font-family: 'Share Tech Mono', monospace; font-weight: 600; color: var(--text-primary);">${escapeHtml(act.payload)}</span></td>
                            <td>${attsHtml}</td>
                            <td><span class="${statusClass}">${escapeHtml(act.status)}</span></td>
                        </tr>`;
                    }).join('');
                }
                
            } catch (err) {
                console.error('Failed to fetch stats', err);
            }
        }
        
        setInterval(updateStats, 3000);
        updateStats();
    </script>
</body>
</html>"""

    async def handle_web_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Asynchronously parses incoming GET requests and serves JSON status or premium HTML dashboard."""
        try:
            data = await reader.readline()
            line = data.decode("utf-8", errors="ignore").strip()
            if not line:
                return
            
            parts = line.split()
            if len(parts) < 2:
                return
            
            method, path = parts[0], parts[1]
            
            # Consume the remaining HTTP request headers (max 100 to prevent DoS)
            header_count = 0
            while header_count < 100:
                header_line = await reader.readline()
                if not header_line or header_line == b"\r\n" or header_line == b"\n":
                    break
                header_count += 1
            
            if method != "GET":
                response_headers = (
                    "HTTP/1.1 405 Method Not Allowed\r\n"
                    "Content-Type: text/plain\r\n"
                    "Content-Length: 18\r\n"
                    "Connection: close\r\n\r\n"
                    "Method Not Allowed"
                )
                writer.write(response_headers.encode())
                await writer.drain()
                return

            if path in ("/api", "/api/status", "/status"):
                status_dict = self.get_status_json()
                body = json.dumps(status_dict, indent=2).encode("utf-8")
                content_type = "application/json"
            elif path == "/":
                body = self.get_dashboard_html().encode("utf-8")
                content_type = "text/html; charset=utf-8"
            elif path in ("/logo.svg", "/favicon.svg", "/favicon.ico"):
                filename = "logo.svg" if path == "/logo.svg" else "favicon.svg"
                file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
                if os.path.exists(file_path) and os.path.isfile(file_path):
                    content_type = "image/svg+xml"
                    try:
                        body = await asyncio.to_thread(self._read_file_binary, file_path)
                    except Exception as e:
                        log.error("Failed to read image file %s: %s", file_path, e)
                        body = b"Internal Server Error"
                        content_type = "text/plain"
                        response_headers = (
                            f"HTTP/1.1 500 Internal Server Error\r\n"
                            f"Content-Type: {content_type}\r\n"
                            f"Content-Length: {len(body)}\r\n"
                            "Connection: close\r\n\r\n"
                        )
                        writer.write(response_headers.encode() + body)
                        await writer.drain()
                        return
                else:
                    body = b"File Not Found"
                    content_type = "text/plain"
                    response_headers = (
                        f"HTTP/1.1 404 Not Found\r\n"
                        f"Content-Type: {content_type}\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        "Connection: close\r\n\r\n"
                    )
                    writer.write(response_headers.encode() + body)
                    await writer.drain()
                    return
            elif path.startswith("/attachments/"):
                # Safety check against Path Traversal (CWE-22) by extracting only the base filename
                filename = os.path.basename(path)
                file_path = os.path.join(get_attachments_dir(), filename)
                
                # Make sure the file exists and is indeed a file within the 'attachments' directory
                if os.path.exists(file_path) and os.path.isfile(file_path):
                    # Guess MIME type
                    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
                    mime_types = {
                        "jpg": "image/jpeg",
                        "jpeg": "image/jpeg",
                        "png": "image/png",
                        "gif": "image/gif",
                        "pdf": "application/pdf"
                    }
                    content_type = mime_types.get(ext, "application/octet-stream")
                    
                    try:
                        body = await asyncio.to_thread(self._read_file_binary, file_path)
                        response_headers = (
                            f"HTTP/1.1 200 OK\r\n"
                            f"Content-Type: {content_type}\r\n"
                            f"Content-Length: {len(body)}\r\n"
                            f"Content-Disposition: inline; filename=\"{filename}\"\r\n"
                            "Connection: close\r\n\r\n"
                        )
                        writer.write(response_headers.encode() + body)
                        await writer.drain()
                        return
                    except Exception as e:
                        log.error("Failed to read attachment file %s: %s", file_path, e)
                        body = b"Internal Server Error"
                        content_type = "text/plain"
                        response_headers = (
                            f"HTTP/1.1 500 Internal Server Error\r\n"
                            f"Content-Type: {content_type}\r\n"
                            f"Content-Length: {len(body)}\r\n"
                            "Connection: close\r\n\r\n"
                        )
                        writer.write(response_headers.encode() + body)
                        await writer.drain()
                        return
                else:
                    body = b"Attachment Not Found"
                    content_type = "text/plain"
                    response_headers = (
                        f"HTTP/1.1 404 Not Found\r\n"
                        f"Content-Type: {content_type}\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        "Connection: close\r\n\r\n"
                    )
                    writer.write(response_headers.encode() + body)
                    await writer.drain()
                    return
            else:
                body = b"Not Found"
                content_type = "text/plain"
                response_headers = (
                    f"HTTP/1.1 404 Not Found\r\n"
                    f"Content-Type: {content_type}\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    "Connection: close\r\n\r\n"
                )
                writer.write(response_headers.encode() + body)
                await writer.drain()
                return

            response_headers = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: {content_type}\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n\r\n"
            )
            writer.write(response_headers.encode() + body)
            await writer.drain()
        except Exception as e:
            log.error("Error serving web request: %s", e)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    def _read_file_binary(self, file_path: str) -> bytes:
        with open(file_path, "rb") as f:
            return f.read()


def main():
    log.info("Starting smtp2mqtt gateway...")
    log.debug("Configuration: %s", ", ".join([f"{k}={v}" for k, v in config.items()]))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    handler = smtp2mqttHandler(loop)
    
    # Use UnthreadedController to run in the main asyncio event loop
    controller = UnthreadedController(
        handler=handler,
        loop=loop,
        hostname="0.0.0.0",
        port=config["SMTP_PORT"],
    )
    handler.smtp_controller = controller

    # Start the controller synchronously (schedules the server creation inside loop)
    controller.begin()
    log.info("SMTP server is listening on 0.0.0.0:%d", config["SMTP_PORT"])

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

