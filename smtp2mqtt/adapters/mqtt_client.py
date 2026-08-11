import asyncio
import logging
import time
from typing import Any, Dict, Optional
from paho.mqtt import client as mqtt

log = logging.getLogger("smtp2mqtt.mqtt")


class MQTTAdapter:
    """Robust MQTT adapter with exponential backoff reconnect and non-blocking publishing."""

    def __init__(self, loop: asyncio.AbstractEventLoop, config: Dict[str, Any]):
        self.loop = loop
        self.config = config
        self.client: Optional[mqtt.Client] = None
        self._connected = False
        self._lock = asyncio.Lock()

    def connect(self) -> None:
        """Initializes and connects the Paho MQTT client."""
        host = self.config.get("MQTT_HOST", "localhost")
        port = int(self.config.get("MQTT_PORT", 1883))
        user = self.config.get("MQTT_USER", "")
        password = self.config.get("MQTT_PASS", "")

        client_id = f"smtp2mqtt_{int(time.time())}"
        self.client = mqtt.Client(client_id=client_id)

        if user and password:
            self.client.username_pw_set(user, password)

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                log.info("MQTT Client successfully connected to %s:%s", host, port)
                self._connected = True
            else:
                log.warning("MQTT Connection failed with return code %s", rc)
                self._connected = False

        def on_disconnect(client, userdata, rc):
            log.warning("MQTT Client disconnected (rc=%s). Automatic reconnect pending...", rc)
            self._connected = False

        self.client.on_connect = on_connect
        self.client.on_disconnect = on_disconnect

        try:
            self.client.connect_async(host, port, keepalive=60)
            self.client.loop_start()
        except Exception as err:
            log.error("Error initiating MQTT connection: %s", err)

    def publish(self, topic: str, payload: str, retain: bool = False) -> bool:
        """Publishes a payload to an MQTT topic asynchronously."""
        if not self.client or not self._connected:
            log.warning("MQTT client not connected. Falling back to single-shot publish for %s", topic)
            return self._single_shot_publish(topic, payload, retain)

        try:
            info = self.client.publish(topic, payload, qos=0, retain=retain)
            return info.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as err:
            log.error("Error publishing to MQTT topic %s: %s", topic, err)
            return self._single_shot_publish(topic, payload, retain)

    def _single_shot_publish(self, topic: str, payload: str, retain: bool) -> bool:
        """Fallback single-shot publish using paho.mqtt.publish.single."""
        try:
            from paho.mqtt import publish as single_publish
            auth = None
            if self.config.get("MQTT_USER") and self.config.get("MQTT_PASS"):
                auth = {
                    "username": self.config.get("MQTT_USER"),
                    "password": self.config.get("MQTT_PASS"),
                }
            single_publish.single(
                topic,
                payload=payload,
                hostname=self.config.get("MQTT_HOST", "localhost"),
                port=int(self.config.get("MQTT_PORT", 1883)),
                auth=auth,
                retain=retain,
            )
            return True
        except Exception as err:
            log.error("Single-shot MQTT publish failed for %s: %s", topic, err)
            return False

    def disconnect(self) -> None:
        """Disconnects the MQTT client during shutdown."""
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
            self._connected = False
