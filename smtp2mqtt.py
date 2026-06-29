#!/usr/bin/env python3
import asyncio
import email
import logging
import os
import signal
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
    if setting in ("SAVE_ATTACHMENTS", "SAVE_ATTACHMENTS_DURING_RESET_TIME", "DEBUG"):
        config[setting] = parse_bool(env_val)
    elif setting in ("SMTP_PORT", "MQTT_PORT", "MQTT_RESET_TIME"):
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
        if config["SAVE_ATTACHMENTS"]:
            log.info("Configured to save attachments to 'attachments' directory")

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

        # Construct topic based on sender
        topic = f"{config['MQTT_TOPIC']}/{mail_from.replace('@', '-')}"

        # Publish the primary payload asynchronously (in a thread executor to not block loop)
        log.debug("Dispatching MQTT publish for trigger payload...")
        await asyncio.to_thread(self.mqtt_publish, topic, config["MQTT_PAYLOAD"])

        # Determine whether to save attachments
        is_triggered = topic in self.handles
        should_save = config["SAVE_ATTACHMENTS"] and (
            not is_triggered or config["SAVE_ATTACHMENTS_DURING_RESET_TIME"]
        )

        if should_save:
            log.debug("Dispatching attachment save task...")
            await asyncio.to_thread(self.save_attachments, msg, topic, is_triggered)
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

    def save_attachments(self, msg, topic: str, is_triggered: bool):
        """Iterates through and saves image attachments to the local filesystem."""
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

                image_data = part.get_content()
                os.makedirs("attachments", exist_ok=True)
                file_path = os.path.join("attachments", filename)
                
                log.info("Saving attached image '%s' to '%s'", filename, file_path)
                with open(file_path, "wb") as f:
                    f.write(image_data)
        except Exception:
            log.exception("Exception occurred while saving attachments")

    def mqtt_publish(self, topic: str, payload: str):
        """Publishes a payload to MQTT broker (synchronous blocking network call)."""
        log.info("Publishing payload '%s' to topic '%s'", payload, topic)
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
        except Exception as e:
            log.error("Failed to publish MQTT message to %s: %s", topic, e, exc_info=True)

    def _trigger_reset(self, topic: str):
        """Callback scheduled by call_later. Triggers topic reset back to default payload."""
        if topic in self.handles:
            self.handles.pop(topic)
        log.info("Reset timer expired. Resetting topic: %s", topic)
        
        # Schedule the blocking mqtt_publish call in a separate thread executor via create_task
        asyncio.create_task(
            asyncio.to_thread(self.mqtt_publish, topic, config["MQTT_RESET_PAYLOAD"])
        )

    def cancel_all_resets(self):
        """Cancels all currently pending reset timers (used for graceful shutdown)."""
        if not self.handles:
            return
        log.info("Cancelling %d active reset timers...", len(self.handles))
        for topic, handle in list(self.handles.items()):
            handle.cancel()
        self.handles.clear()


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

    # Start the controller synchronously (schedules the server creation inside loop)
    controller.begin()
    log.info("SMTP server is listening on 0.0.0.0:%d", config["SMTP_PORT"])

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
