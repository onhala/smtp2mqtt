#!/usr/bin/env python3
import asyncio
import email
import json
import logging
import os
import signal
import socket
import sys
from datetime import datetime
from email.policy import default

from aiosmtpd.controller import UnthreadedController
from paho.mqtt import publish

# Default configurations
defaults = {
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
}

def parse_bool(value) -> bool:
    """Helper to robustly parse boolean configuration values."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).lower() in ("true", "1", "yes", "on")

# Load and process configuration
config = {}
for setting, default_val in defaults.items():
    env_val = os.environ.get(setting, default_val)
    if setting in ("SAVE_ATTACHMENTS", "SAVE_ATTACHMENTS_DURING_RESET_TIME", "DEBUG", "ENABLE_WEB"):
        config[setting] = parse_bool(env_val)
    elif setting in ("SMTP_PORT", "MQTT_PORT", "MQTT_RESET_TIME", "WEB_PORT"):
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

# Log to file if "log" directory exists
if os.path.exists("log"):
    log.info("Setting up a file logger at log/smtp2mqtt.log")
    fh = logging.FileHandler("log/smtp2mqtt.log")
    fh.setFormatter(formatter)
    log.addHandler(fh)


class smtp2mqttHandler:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.reset_time = config["MQTT_RESET_TIME"]
        self.handles = {}
        
        # State tracking for Web Status Dashboard and gethomepage.dev
        self.start_time = datetime.now()
        self.processed_messages_count = 0
        self.last_publish_success = None
        self.last_publish_time = None
        self.recent_actions = []  # List of dicts
        
        # MQTT Broker connection monitoring
        self.mqtt_connected_status = None
        coro = self.monitor_mqtt_broker()
        if type(loop).__name__ in ("MagicMock", "Mock", "AsyncMock"):
            self.monitor_task = None
            coro.close()
        else:
            self.monitor_task = self.loop.create_task(coro)
            
        # SMTP Server connectivity monitoring
        self.smtp_connected_status_val = None
        coro_smtp = self.monitor_smtp_server()
        if type(loop).__name__ in ("MagicMock", "Mock", "AsyncMock"):
            self.monitor_smtp_task = None
            coro_smtp.close()
        else:
            self.monitor_smtp_task = self.loop.create_task(coro_smtp)
        
        if config["SAVE_ATTACHMENTS"]:
            log.info("Configured to save attachments to 'attachments' directory")

    def log_action(self, action_type: str, sender: str, topic: str, payload: str, success: bool):
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

    async def handle_DATA(self, server, session, envelope):
        """Processes incoming SMTP email messages."""
        mail_from = envelope.mail_from
        log.info("Received SMTP message from %s", mail_from)
        
        try:
            msg = email.message_from_bytes(envelope.original_content, policy=default)
            log.debug(
                "Message data (truncated): %s",
                envelope.content.decode("utf-8", errors="replace")[:250],
            )
        except Exception:
            log.exception("Failed to parse incoming email content")
            return "500 Error parsing message"

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

        saved_attachments = []
        if should_save:
            log.debug("Dispatching attachment save task...")
            saved_attachments = await asyncio.to_thread(self.save_attachments, msg, topic, is_triggered)
        else:
            log.debug("Skipping attachment storage (disabled or reset time constraint)")

        # Associate attachments with the recent trigger action logged inside mqtt_publish thread
        if saved_attachments and self.recent_actions:
            first_action = self.recent_actions[0]
            if (
                first_action["type"] == "trigger"
                and first_action["sender"] == mail_from
                and first_action["topic"] == topic
            ):
                first_action["attachments"] = saved_attachments

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

    def save_attachments(self, msg, topic: str, is_triggered: bool) -> list:
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
                os.makedirs("attachments", exist_ok=True)
                file_path = os.path.join("attachments", safe_filename)
                
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

    def mqtt_publish(self, topic: str, payload: str, action_type: str = "trigger", sender: str = "system"):
        """Publishes a payload to MQTT broker (synchronous blocking network call)."""
        log.info("Publishing payload '%s' to topic '%s'", payload, topic)
        success = False
        try:
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

    def _trigger_reset(self, topic: str):
        """Callback scheduled by call_later. Triggers topic reset back to default payload."""
        if topic in self.handles:
            self.handles.pop(topic)
        log.info("Reset timer expired. Resetting topic: %s", topic)
        
        # Schedule the blocking mqtt_publish call in a separate thread executor via create_task
        asyncio.create_task(
            asyncio.to_thread(self.mqtt_publish, topic, config["MQTT_RESET_PAYLOAD"], "reset", "system")
        )

    def cancel_all_resets(self):
        """Cancels all currently pending reset timers and background tasks (used for graceful shutdown)."""
        if hasattr(self, "monitor_task") and self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
        if hasattr(self, "monitor_smtp_task") and self.monitor_smtp_task and not self.monitor_smtp_task.done():
            self.monitor_smtp_task.cancel()
        if not self.handles:
            return
        log.info("Cancelling %d active reset timers...", len(self.handles))
        for topic, handle in list(self.handles.items()):
            handle.cancel()
        self.handles.clear()

    async def monitor_mqtt_broker(self):
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

    async def monitor_smtp_server(self):
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

    def get_status_json(self) -> dict:
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
        }

    def get_dashboard_html(self) -> str:
        """Returns the complete, responsive, premium dark mode HTML dashboard."""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>smtp2mqtt Gateway Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #050706;
            --card-bg: #0b0f0c;
            --border-color: #1a261d;
            --border-focus: #2e3d32;
            --text-primary: #e2e8f0;
            --text-secondary: #7fa384;
            --text-muted: #4e6351;
            --accent-primary: #7ec127;
            --accent-glow: rgba(126, 193, 39, 0.15);
            --success: #7ec127;
            --success-glow: rgba(126, 193, 39, 0.15);
            --danger: #ef4444;
            --danger-glow: rgba(239, 68, 68, 0.15);
            --system-color: #f59e0b;
            --system-glow: rgba(245, 158, 11, 0.12);
        }
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        body {
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 2rem 1.5rem;
            display: flex;
            justify-content: center;
        }
        .container {
            width: 100%;
            max-width: 1200px;
            display: flex;
            flex-direction: column;
            gap: 2rem;
        }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border-color);
        }
        .title-area h1 {
            font-family: 'Share Tech Mono', monospace;
            font-size: 1.85rem;
            font-weight: 700;
            color: var(--accent-primary);
            text-shadow: 0 0 10px rgba(126, 193, 39, 0.3);
            margin-bottom: 0.25rem;
            letter-spacing: -0.02em;
        }
        .title-area p {
            color: var(--text-secondary);
            font-size: 0.875rem;
        }
        .live-indicator {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            background: var(--accent-glow);
            border: 1px solid rgba(126, 193, 39, 0.3);
            color: var(--accent-primary);
            padding: 0.375rem 0.75rem;
            border-radius: 4px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.05em;
        }
        .live-dot {
            width: 8px;
            height: 8px;
            background-color: var(--accent-primary);
            border-radius: 50%;
            box-shadow: 0 0 10px var(--accent-primary);
            animation: pulse-green 2s infinite;
        }
        @keyframes pulse-green {
            0% { box-shadow: 0 0 0 0 rgba(126, 193, 39, 0.4); }
            70% { box-shadow: 0 0 0 8px rgba(126, 193, 39, 0); }
            100% { box-shadow: 0 0 0 0 rgba(126, 193, 39, 0); }
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 1.5rem;
        }
        .card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-left: 4px solid var(--accent-primary);
            border-radius: 4px;
            padding: 1.5rem;
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.4);
            transition: border-color 0.2s, box-shadow 0.2s;
        }
        .card:hover {
            border-color: var(--border-focus);
            box-shadow: 0 4px 35px rgba(126, 193, 39, 0.08);
        }
        .card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 1.25rem;
        }
        .card-title {
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.8125rem;
            color: var(--text-secondary);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .card-icon {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 2.25rem;
            height: 2.25rem;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 4px;
            color: var(--text-secondary);
        }
        .card-value {
            font-family: 'Share Tech Mono', monospace;
            font-size: 1.85rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
            color: var(--text-primary);
        }
        .card-subtext {
            font-size: 0.8125rem;
            color: var(--text-muted);
        }
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.375rem;
            padding: 0.25rem 0.625rem;
            border-radius: 4px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.75rem;
            font-weight: 600;
        }
        .status-badge.success {
            background-color: var(--success-glow);
            color: var(--accent-primary);
            border: 1px solid rgba(126, 193, 39, 0.25);
        }
        .status-badge.danger {
            background-color: var(--danger-glow);
            color: #f87171;
            border: 1px solid rgba(239, 68, 68, 0.25);
        }
        .status-badge.secondary {
            background-color: rgba(255, 255, 255, 0.03);
            color: var(--text-secondary);
            border: 1px solid var(--border-color);
        }
        .panel {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 4px;
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.4);
            display: flex;
            flex-direction: column;
        }
        .panel-header {
            padding: 1.5rem;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .panel-title {
            font-family: 'Share Tech Mono', monospace;
            font-size: 1.125rem;
            font-weight: 600;
            color: var(--text-primary);
            letter-spacing: 0.02em;
        }
        .table-container {
            overflow-x: auto;
            max-height: 450px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.875rem;
        }
        th {
            padding: 1rem 1.5rem;
            font-family: 'Share Tech Mono', monospace;
            font-weight: 600;
            color: var(--text-secondary);
            border-bottom: 1px solid var(--border-color);
            background-color: rgba(0, 0, 0, 0.2);
            position: sticky;
            top: 0;
            z-index: 10;
        }
        td {
            padding: 1rem 1.5rem;
            border-bottom: 1px solid var(--border-color);
            color: var(--text-primary);
        }
        tr:last-child td {
            border-bottom: none;
        }
        tr:hover td {
            background-color: rgba(255, 255, 255, 0.01);
        }
        .type-badge {
            display: inline-flex;
            padding: 0.1875rem 0.5rem;
            border-radius: 2px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.6875rem;
            font-weight: 700;
            letter-spacing: 0.05em;
        }
        .type-badge.trigger {
            background-color: var(--accent-glow);
            color: var(--accent-primary);
            border: 1px solid rgba(126, 193, 39, 0.25);
        }
        .type-badge.reset {
            background-color: rgba(255, 255, 255, 0.03);
            color: var(--text-secondary);
            border: 1px solid var(--border-color);
        }
        .type-badge.system {
            background-color: var(--system-glow);
            color: var(--system-color);
            border: 1px solid rgba(245, 158, 11, 0.25);
        }
        .empty-state {
            padding: 4rem 2rem;
            text-align: center;
            color: var(--text-secondary);
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 0.75rem;
        }
        .empty-state svg {
            opacity: 0.3;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="title-area">
                <h1>smtp2mqtt Gateway</h1>
                <p>Asynchronous SMTP-to-MQTT Trigger Converter</p>
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
                                    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 22c5.523 0 9-4.477 9-10S17.523 2 12 2 3 6.477 3 12s3.477 10 9 10zM12 8v4M12 16h.01"/></svg>
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
                
                const mqttStatusBadge = document.getElementById('mqtt-status');
                if (data.mqtt_connected) {
                    mqttStatusBadge.className = 'status-badge success';
                    mqttStatusBadge.innerHTML = '<span class="live-dot" style="background-color: var(--accent-primary); box-shadow: 0 0 10px var(--accent-primary); animation: pulse-green 2s infinite; width: 6px; height: 6px; margin-right: 4px;"></span>Connected';
                } else {
                    mqttStatusBadge.className = 'status-badge danger';
                    mqttStatusBadge.innerHTML = 'Disconnected';
                }
                
                const smtpStatusBadge = document.getElementById('smtp-status');
                if (data.smtp_connected) {
                    smtpStatusBadge.className = 'status-badge success';
                    smtpStatusBadge.innerHTML = '<span class="live-dot" style="background-color: var(--accent-primary); box-shadow: 0 0 10px var(--accent-primary); animation: pulse-green 2s infinite; width: 6px; height: 6px; margin-right: 4px;"></span>Active';
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
                                return `<div class="attachment-item" style="margin-bottom: 0.375rem;">
                                    <a href="/attachments/${safeName}" target="_blank" class="attachment-link" style="color: var(--accent-primary); text-decoration: none; font-weight: 600; font-family: 'Share Tech Mono', monospace; display: inline-flex; align-items: center; gap: 0.25rem;">
                                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
                                        ${safeName}
                                    </a>
                                    <div class="attachment-path" style="font-size: 0.7rem; color: #5c7c59; font-family: 'Share Tech Mono', monospace; word-break: break-all; margin-top: 0.05rem;">${safePath}</div>
                                </div>`;
                            }).join('');
                        }

                        const topicColor = typeLower === 'system' ? 'var(--text-muted)' : 'var(--accent-primary)';

                        return `<tr>
                            <td style="white-space: nowrap; font-family: 'Share Tech Mono', monospace;">${escapeHtml(act.timestamp)}</td>
                            <td><span class="${typeClass}">${escapeHtml(act.type.toUpperCase())}</span></td>
                            <td style="font-family: 'Share Tech Mono', monospace;">${escapeHtml(act.sender)}</td>
                            <td style="font-family: 'Share Tech Mono', monospace; font-size: 0.8125rem; color: ${topicColor};">${escapeHtml(act.topic)}</td>
                            <td><span style="font-family: 'Share Tech Mono', monospace; font-weight: 600;">${escapeHtml(act.payload)}</span></td>
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

    async def handle_web_client(self, reader, writer):
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
            elif path.startswith("/attachments/"):
                # Safety check against Path Traversal (CWE-22) by extracting only the base filename
                filename = os.path.basename(path)
                file_path = os.path.join("attachments", filename)
                
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

