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
import email.utils
import ipaddress
import json
import logging
import re
import signal
import socket
import threading
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.policy import default
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import requests
    from requests.auth import HTTPDigestAuth
except ImportError:
    requests = None  # type: ignore
    HTTPDigestAuth = None  # type: ignore

try:
    from aiosmtpd.controller import UnthreadedController
    from paho.mqtt import client as mqtt, publish
except ModuleNotFoundError as err:
    sys.stderr.write(f"Missing module: {err}. Attempting auto-install of dependencies...\n")
    packages = ["aiosmtpd", "paho-mqtt", "aiomqtt", "pillow", "requests"]
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
    "SMTP_SERVER_HOSTNAME": "smtp2mqtt",
    "ALLOWED_IPS": "192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12, 127.0.0.1",
    "MQTT_HOST": "localhost",
    "MQTT_PORT": 1883,
    "MQTT_USERNAME": "",
    "MQTT_PASSWORD": "",
    "MQTT_TOPIC": "smtp2mqtt",
    "MQTT_PAYLOAD": "1",
    "MQTT_RESET_TIME": "10",
    "MQTT_RESET_PAYLOAD": "0",
    "ENABLE_EVENT_TOPIC": "True",
    "ENABLE_METRICS": "True",
    "SAVE_ATTACHMENTS": "False",
    "SAVE_ATTACHMENTS_DURING_RESET_TIME": "False",
    "DEBUG": "False",
    "ENABLE_WEB": "True",
    "WEB_PORT": "8080",
    "CLEANUP_ATTACHMENTS_DAYS": "30",
    "CLEANUP_LOGS_DAYS": "30",
    "CLEANUP_INTERVAL_SECONDS": "86400",
    "ENABLE_ISAPI": "False",
    "ISAPI_CAMERAS": "",
    "ISAPI_USER": "admin",
    "ISAPI_PASSWORD": "",
    "ISAPI_FILTER_MODE": "smart_or_acusense",
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
    defaults["ENABLE_WEB"] = "True"

lb_mqtt_defaults = load_loxberry_mqtt_config(loxberry_paths)
file_defaults = load_file_config(loxberry_paths)


def parse_hikvision_event(subject: str, body: str) -> Dict[str, Any]:
    """Parses email subject and body text from Hikvision cameras / NVRs to extract detailed event metadata."""
    subject_clean = (subject or "").strip()
    body_clean = (body or "").strip()
    full_text = f"{subject_clean}\n{body_clean}"

    event_info = {
        "event_type": "motion",
        "event_label": "Motion Detection",
        "event_icon": "📹",
        "line_number": None,
        "region_number": None,
        "target_type": "unknown",
        "camera_name": None,
        "device_model": None,
        "event_time": None,
        "raw_details": {}
    }

    kv_pairs = {}
    for line in body_clean.splitlines():
        if ":" in line:
            parts = line.split(":", 1)
            k = parts[0].strip().upper()
            v = parts[1].strip()
            if k and v:
                kv_pairs[k] = v

    event_info["raw_details"] = kv_pairs

    for k, v in kv_pairs.items():
        if "CAMERA NAME" in k:
            event_info["camera_name"] = v
        elif "DEVICE NAME" in k or "DVR NAME" in k:
            event_info["device_model"] = v
        elif "EVENT TIME" in k or "ALARM TIME" in k:
            event_info["event_time"] = v
        elif "TARGET TYPE" in k or "DETECTION TARGET" in k:
            t_val = v.lower()
            if "human" in t_val:
                event_info["target_type"] = "human"
            elif "vehicle" in t_val:
                event_info["target_type"] = "vehicle"

    line_match = re.search(r'(?:line|lineitem|čára|čára číslo)\s*(\d+)', full_text, re.IGNORECASE)
    if line_match:
        try:
            event_info["line_number"] = int(line_match.group(1))
        except ValueError:
            pass

    region_match = re.search(r'(?:region|field|zone|zóna|oblast)\s*(\d+)', full_text, re.IGNORECASE)
    if region_match:
        try:
            event_info["region_number"] = int(region_match.group(1))
        except ValueError:
            pass

    if event_info["target_type"] == "unknown":
        if re.search(r'\b(?:human|person|člověk|postava)\b', full_text, re.IGNORECASE):
            event_info["target_type"] = "human"
        elif re.search(r'\b(?:vehicle|car|auto|vozidlo)\b', full_text, re.IGNORECASE):
            event_info["target_type"] = "vehicle"

    text_lower = full_text.lower()

    if "line crossing" in text_lower or "linedetection" in text_lower or "překročení" in text_lower:
        event_info["event_type"] = "line_crossing"
        line_str = f" (Line {event_info['line_number']})" if event_info['line_number'] else ""
        event_info["event_label"] = f"Line Crossing{line_str}"
        event_info["event_icon"] = "🚶"
    elif "field detection" in text_lower or "fielddetection" in text_lower or "intrusion" in text_lower or "narušení" in text_lower:
        event_info["event_type"] = "intrusion"
        reg_str = f" (Region {event_info['region_number']})" if event_info['region_number'] else ""
        event_info["event_label"] = f"Intrusion Detection{reg_str}"
        event_info["event_icon"] = "🛡️"
    elif "region entrance" in text_lower or "regionentrance" in text_lower or "vstup do oblasti" in text_lower:
        event_info["event_type"] = "region_entrance"
        event_info["event_label"] = "Region Entrance"
        event_info["event_icon"] = "🚪"
    elif "region exiting" in text_lower or "regionexiting" in text_lower or "opuštění oblasti" in text_lower:
        event_info["event_type"] = "region_exiting"
        event_info["event_label"] = "Region Exiting"
        event_info["event_icon"] = "🚪"
    elif "loitering" in text_lower or "postávání" in text_lower:
        event_info["event_type"] = "loitering"
        event_info["event_label"] = "Loitering Detection"
        event_info["event_icon"] = "⏳"
    elif "unattended baggage" in text_lower or "object left" in text_lower or "zavazadlo" in text_lower:
        event_info["event_type"] = "unattended_baggage"
        event_info["event_label"] = "Unattended Baggage"
        event_info["event_icon"] = "🧳"
    elif "object removal" in text_lower or "odebrání předmětu" in text_lower:
        event_info["event_type"] = "object_removal"
        event_info["event_label"] = "Object Removal"
        event_info["event_icon"] = "📦"
    elif "face detection" in text_lower or "facedetection" in text_lower or "obličej" in text_lower:
        event_info["event_type"] = "face_detection"
        event_info["event_label"] = "Face Detection"
        event_info["event_icon"] = "👤"
    elif "anpr" in text_lower or "license plate" in text_lower or "spz" in text_lower:
        event_info["event_type"] = "anpr"
        event_info["event_label"] = "Plate Recognition"
        event_info["event_icon"] = "🚗"
    elif "tamper" in text_lower or "sabotáž" in text_lower or "zakrytí" in text_lower:
        event_info["event_type"] = "tamper"
        event_info["event_label"] = "Video Tampering"
        event_info["event_icon"] = "⚠️"
    elif "scene change" in text_lower or "změna scény" in text_lower:
        event_info["event_type"] = "scene_change"
        event_info["event_label"] = "Scene Change"
        event_info["event_icon"] = "🔄"
    elif "defocus" in text_lower or "rozostření" in text_lower:
        event_info["event_type"] = "defocus"
        event_info["event_label"] = "Defocus Detection"
        event_info["event_icon"] = "🔍"
    elif "audio exception" in text_lower or "zvuková výjimka" in text_lower:
        event_info["event_type"] = "audio_exception"
        event_info["event_label"] = "Audio Exception"
        event_info["event_icon"] = "🔊"
    elif "pir" in text_lower:
        event_info["event_type"] = "pir"
        event_info["event_label"] = "PIR Alarm"
        event_info["event_icon"] = "🚨"
    elif "alarm input" in text_lower or "io alarm" in text_lower:
        event_info["event_type"] = "io_alarm"
        event_info["event_label"] = "IO Alarm Input"
        event_info["event_icon"] = "⚡"
    elif "disk full" in text_lower or "disk error" in text_lower or "diskfull" in text_lower or "diskerror" in text_lower:
        event_info["event_type"] = "disk_error"
        event_info["event_label"] = "Disk Exception / Error"
        event_info["event_icon"] = "💾"
    elif "ip conflict" in text_lower or "ipconflict" in text_lower or "nicbroken" in text_lower:
        event_info["event_type"] = "network_error"
        event_info["event_label"] = "Network / IP Error"
        event_info["event_icon"] = "🌐"
    elif "illegal access" in text_lower or "illaccess" in text_lower:
        event_info["event_type"] = "illegal_access"
        event_info["event_label"] = "Illegal Access Attempt"
        event_info["event_icon"] = "🔒"
    else:
        event_info["event_type"] = "motion"
        event_info["event_label"] = "Motion Detection"
        event_info["event_icon"] = "📹"

    return event_info


def parse_hikvision_isapi_alert(xml_str: str) -> Dict[str, Any]:
    """Parses multipart XML alert chunk from Hikvision /ISAPI/Event/notification/alertStream."""
    info: Dict[str, Any] = {
        "event_type": "motion",
        "event_label": "Motion Detection",
        "event_icon": "📹",
        "target_type": "unknown",
        "channel_id": "1",
        "channel_name": None,
        "event_time": None,
        "event_state": "active",
        "raw_details": {}
    }

    if not xml_str:
        return info

    try:
        # Strip default XML namespace for clean ElementTree queries
        clean_xml = re.sub(r'\s+xmlns="[^"]+"', '', xml_str)
        root = ET.fromstring(clean_xml)

        ev_type_elem = root.find(".//eventType")
        if ev_type_elem is not None and ev_type_elem.text:
            raw_type = ev_type_elem.text.strip().lower()
            if "linedetection" in raw_type or "line" in raw_type:
                info["event_type"] = "line_crossing"
                info["event_label"] = "Line Crossing Detection"
                info["event_icon"] = "🚶"
            elif "fielddetection" in raw_type or "intrusion" in raw_type:
                info["event_type"] = "intrusion"
                info["event_label"] = "Intrusion Detection"
                info["event_icon"] = "🛡️"
            elif "regionentrance" in raw_type:
                info["event_type"] = "region_entrance"
                info["event_label"] = "Region Entrance"
                info["event_icon"] = "🚪"
            elif "regionexiting" in raw_type:
                info["event_type"] = "region_exiting"
                info["event_label"] = "Region Exiting"
                info["event_icon"] = "🚪"
            elif "facedetection" in raw_type or "facesnap" in raw_type or "face" in raw_type:
                info["event_type"] = "face"
                info["event_label"] = "Face Detection"
                info["event_icon"] = "👤"
            elif "tamper" in raw_type or "shelter" in raw_type:
                info["event_type"] = "tamper"
                info["event_label"] = "Tamper Alarm"
                info["event_icon"] = "⚠️"
            elif "scenechange" in raw_type:
                info["event_type"] = "scene_change"
                info["event_label"] = "Scene Change"
                info["event_icon"] = "🔄"
            elif "loitering" in raw_type:
                info["event_type"] = "loitering"
                info["event_label"] = "Loitering Detection"
                info["event_icon"] = "⏳"
            elif "unattendedbaggage" in raw_type or "objectleft" in raw_type:
                info["event_type"] = "unattended_baggage"
                info["event_label"] = "Unattended Baggage"
                info["event_icon"] = "🧳"
            elif "attendedbaggage" in raw_type or "objectremoval" in raw_type:
                info["event_type"] = "object_removal"
                info["event_label"] = "Object Removal"
                info["event_icon"] = "📦"
            elif "io" in raw_type or "alarm" in raw_type:
                info["event_type"] = "io_alarm"
                info["event_label"] = "IO Alarm Input"
                info["event_icon"] = "⚡"
            elif "disk" in raw_type:
                info["event_type"] = "disk_error"
                info["event_label"] = "Disk Exception / Error"
                info["event_icon"] = "💾"
            elif "ipconflict" in raw_type or "nicbroken" in raw_type:
                info["event_type"] = "network_error"
                info["event_label"] = "Network / IP Error"
                info["event_icon"] = "🌐"
            elif "illaccess" in raw_type:
                info["event_type"] = "illegal_access"
                info["event_label"] = "Illegal Access Attempt"
                info["event_icon"] = "🔒"
            else:
                info["event_type"] = "motion"
                info["event_label"] = "Motion Detection"
                info["event_icon"] = "📹"

        target_elem = root.find(".//targetType")
        if target_elem is None:
            target_elem = root.find(".//detectionTarget")
        if target_elem is not None and target_elem.text:
            t_val = target_elem.text.strip().lower()
            if "human" in t_val or "person" in t_val:
                info["target_type"] = "human"
            elif "vehicle" in t_val or "car" in t_val:
                info["target_type"] = "vehicle"

        ch_name_elem = root.find(".//channelName")
        if ch_name_elem is not None and ch_name_elem.text:
            info["channel_name"] = ch_name_elem.text.strip()

        ch_id_elem = root.find(".//channelID")
        if ch_id_elem is None:
            ch_id_elem = root.find(".//dynChannelID")
        if ch_id_elem is not None and ch_id_elem.text:
            info["channel_id"] = ch_id_elem.text.strip()

        dt_elem = root.find(".//dateTime")
        if dt_elem is not None and dt_elem.text:
            info["event_time"] = dt_elem.text.strip()

        st_elem = root.find(".//eventState")
        if st_elem is not None and st_elem.text:
            info["event_state"] = st_elem.text.strip().lower()

        desc_elem = root.find(".//eventDescription")
        if desc_elem is not None and desc_elem.text:
            info["raw_details"]["eventDescription"] = desc_elem.text.strip()

    except Exception as e:
        log.debug("Error parsing ISAPI alert XML: %s", e)

    return info


def is_isapi_event_permitted(event_type: str, target_type: str, filter_mode: str = "smart_or_acusense") -> bool:
    """Evaluates whether an ISAPI alert event matches the user-configured filter rule."""
    filter_mode = (filter_mode or "smart_or_acusense").strip().lower()
    
    if filter_mode in ("all", "none", "*", "off"):
        return True

    # Smart event types
    is_smart = event_type in (
        "line_crossing", "intrusion", "region_entrance", "region_exiting",
        "face", "loitering", "unattended_baggage", "object_removal"
    )
    is_acusense_target = target_type in ("human", "vehicle")

    if filter_mode == "acusense_only":
        # Strictly require human or vehicle classification
        return is_acusense_target

    if filter_mode == "smart_only":
        # Strictly require smart event types
        return is_smart

    if filter_mode == "smart_or_acusense":
        # Allow any smart event, OR basic motion if confirmed human/vehicle
        if is_smart or is_acusense_target:
            return True
        return False

    return True


def probe_camera_isapi(ip: str, port: int = 80, user: str = "admin", pwd: str = "") -> Dict[str, Any]:
    """Tests connectivity and credentials against Hikvision ISAPI /ISAPI/System/deviceInfo."""
    if requests is None or HTTPDigestAuth is None:
        return {"success": False, "error": "Missing python 'requests' module"}

    url = f"http://{ip}:{port}/ISAPI/System/deviceInfo"
    auth = HTTPDigestAuth(user, pwd) if user and pwd else None
    t0 = time.perf_counter()
    try:
        resp = requests.get(url, auth=auth, timeout=3.5)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code == 200:
            dev_name = ""
            model = ""
            fw = ""
            try:
                clean_xml = re.sub(r'\s+xmlns="[^"]+"', '', resp.text)
                root = ET.fromstring(clean_xml)
                dev_name_el = root.find(".//deviceName")
                model_el = root.find(".//model")
                fw_el = root.find(".//firmwareVersion")
                if dev_name_el is not None and dev_name_el.text:
                    dev_name = dev_name_el.text.strip()
                if model_el is not None and model_el.text:
                    model = model_el.text.strip()
                if fw_el is not None and fw_el.text:
                    fw = fw_el.text.strip()
            except Exception:
                pass
            return {
                "success": True,
                "status_code": 200,
                "latency_ms": elapsed_ms,
                "device_name": dev_name,
                "model": model,
                "firmware": fw,
                "message": f"Connected ({model or dev_name or 'Hikvision'}, FW: {fw}, {elapsed_ms}ms)"
            }
        elif resp.status_code == 401:
            return {
                "success": False,
                "status_code": 401,
                "latency_ms": elapsed_ms,
                "error": "Authentication Failed (401 Unauthorized) - Check username/password"
            }
        else:
            return {
                "success": False,
                "status_code": resp.status_code,
                "latency_ms": elapsed_ms,
                "error": f"HTTP Error {resp.status_code}"
            }
    except Exception as e:
        err_msg = str(e)
        if "timed out" in err_msg.lower():
            err_msg = "Connection timed out (Host unreachable)"
        elif "connection refused" in err_msg.lower():
            err_msg = f"Connection refused on {ip}:{port}"
        return {"success": False, "error": err_msg}

def mask_sensitive_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Returns a sanitized copy of configuration dictionary with passwords and sensitive credentials masked."""
    if not isinstance(cfg, dict):
        return cfg
    masked = {}
    sensitive_keys = {
        "mqtt_password", "isapi_password", "password", "pwd", "secret", "token", "brokerpass", "mqttpass"
    }
    for k, v in cfg.items():
        k_lower = str(k).lower()
        if k_lower in sensitive_keys or any(s in k_lower for s in ("password", "secret", "token")):
            masked[k] = "******" if v else ""
        elif k == "ISAPI_CAMERAS":
            if isinstance(v, list):
                cam_list = []
                for cam in v:
                    if isinstance(cam, dict):
                        cam_copy = dict(cam)
                        if cam_copy.get("password"):
                            cam_copy["password"] = "******"
                        cam_list.append(cam_copy)
                    else:
                        cam_list.append(cam)
                masked[k] = cam_list
            else:
                masked[k] = v
        elif isinstance(v, dict):
            masked[k] = mask_sensitive_config(v)
        else:
            masked[k] = v
    return masked


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

for setting in ("SAVE_ATTACHMENTS", "SAVE_ATTACHMENTS_DURING_RESET_TIME", "DEBUG", "ENABLE_WEB", "USE_LOXBERRY_MQTT", "ENABLE_ISAPI"):
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


# Application version
VERSION = "2.2.0"


class smtp2mqttHandler:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.reset_time: float = float(config["MQTT_RESET_TIME"])
        self.handles: Dict[str, asyncio.TimerHandle] = {}
        self.background_tasks = set()
        self._lock = threading.Lock()
        
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

        # Debounced disk write timer handle for status.json
        self._status_dirty = False
        self._status_write_handle: Optional[asyncio.TimerHandle] = None

        # ISAPI Stream status and tasks
        self.isapi_running = False
        self.isapi_stream_tasks: List[asyncio.Task] = []
        self.isapi_status: Dict[str, Dict[str, Any]] = {}

        # Prometheus metrics datastructures (bounded with MAX_METRICS_ENTRIES)
        self.MAX_METRICS_ENTRIES = 500
        self.metrics_events_count: Dict[Tuple[str, str, str], int] = {}
        self.metrics_messages_received_count: Dict[str, int] = {}
        self.metrics_mqtt_published_count: Dict[Tuple[str, str, str], int] = {}
        self.metrics_errors_count: Dict[str, int] = {}
        self.metrics_firewall_rejected_count: Dict[str, int] = {}
        self.metrics_camera_latencies: Dict[str, float] = {}
        self.metrics_trigger_durations: Dict[str, float] = {}
        self.metrics_processing_durations: List[float] = []

        # Pre-compile allowed IP networks for zero-latency connection checks
        self.allowed_networks: List[Any] = []
        allowed_str = str(config.get("ALLOWED_IPS", "")).strip()
        if allowed_str and allowed_str != "*":
            for net_str in allowed_str.split(","):
                net_str = net_str.strip()
                if net_str and net_str != "*":
                    try:
                        if "/" not in net_str:
                            self.allowed_networks.append(ipaddress.ip_network(f"{net_str}/32", strict=False))
                        else:
                            self.allowed_networks.append(ipaddress.ip_network(net_str, strict=False))
                    except ValueError as e:
                        log.warning("Invalid IP network pattern in ALLOWED_IPS: %s (%s)", net_str, e)
        
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

    def log_action(self, action_type: str, sender: str, topic: str, payload: str, success: bool, event_info: Optional[Dict[str, Any]] = None) -> None:
        """Helper to thread-safely record an action status update."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_publish_success = success
        self.last_publish_time = timestamp
        if success:
            self.processed_messages_count += 1
            status = "SUCCESS"
        else:
            status = "FAILED"
            
        sender_final = sender if sender else "system"
        source = "system"
        if action_type == "reset":
            source = "reset"
            event_type = "reset"
            event_label = "Auto-Reset (0)"
            event_icon = "🔄"
        elif action_type == "system":
            source = "system"
            event_type = "system"
            event_label = "System Action"
            event_icon = "⚙️"
        elif event_info and event_info.get("event_type"):
            source = event_info.get("source", "smtp")
            event_type = event_info.get("event_type", "motion")
            event_label = event_info.get("event_label", "Motion Detection")
            event_icon = event_info.get("event_icon", "📹")
        else:
            source = "smtp"
            event_type = "motion"
            event_label = "Motion Detection"
            event_icon = "📹"

        action = {
            "timestamp": timestamp,
            "type": action_type,
            "source": source,
            "sender": sender_final,
            "topic": topic,
            "payload": payload,
            "status": status,
            "attachments": [],
            "event_type": event_type,
            "event_label": event_label,
            "event_icon": event_icon,
            "event_details": event_info or {}
        }
        with self._lock:
            self.recent_actions.insert(0, action)
            if len(self.recent_actions) > 20:
                self.recent_actions.pop()
        self.save_status_file()

    def save_status_file(self, immediate: bool = False) -> None:
        """Schedules debounced writing of status.json to disk (max 1 write per 2.5s to preserve SD card)."""
        self._status_dirty = True
        
        if immediate:
            self._write_status_file_sync()
            return

        if not hasattr(self, "loop") or not self.loop or not self.loop.is_running():
            self._write_status_file_sync()
            return

        # Schedule or debounce write in the event loop
        def _schedule_debounce():
            if self._status_write_handle is None:
                self._status_write_handle = self.loop.call_later(2.5, self._debounced_flush_status)

        try:
            # Check if running in current event loop thread
            current_loop = None
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

            if current_loop is self.loop:
                _schedule_debounce()
            else:
                self.loop.call_soon_threadsafe(_schedule_debounce)
        except Exception:
            _schedule_debounce()

    def _debounced_flush_status(self) -> None:
        """Flushes status.json to disk if dirty."""
        self._status_write_handle = None
        if self._status_dirty:
            self._status_dirty = False
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
            with self._lock:
                self.mqtt_connected_status = True
            # Schedule startup zero-sync across all known camera topics safely from MQTT background thread
            if hasattr(self, "loop") and self.loop and self.loop.is_running():
                try:
                    self.loop.call_soon_threadsafe(
                        lambda: self.loop.create_task(self.sync_startup_resets())
                    )
                except Exception as e:
                    log.warning("Could not schedule sync_startup_resets in loop: %s", e)
        else:
            log.error("Persistent MQTT client failed to connect: return code %s", rc)
            with self._lock:
                self.mqtt_connected_status = False
        self.save_status_file()

    def _on_mqtt_disconnect(self, client: Any, userdata: Any, disconnect_flags: Any, rc: int, properties: Any = None) -> None:
        log.warning("Persistent MQTT client disconnected: return code %s", rc)
        with self._lock:
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

        if not hasattr(self, "_cached_allowed_str") or self._cached_allowed_str != allowed_ips_setting:
            self._cached_allowed_str = allowed_ips_setting
            self._cached_allowed_nets = []
            for net_str in allowed_ips_setting.split(","):
                net_str = net_str.strip()
                if not net_str:
                    continue
                if net_str == "*":
                    self._cached_allowed_nets = None
                    break
                try:
                    if "/" not in net_str:
                        self._cached_allowed_nets.append(ipaddress.ip_network(f"{net_str}/32", strict=False))
                    else:
                        self._cached_allowed_nets.append(ipaddress.ip_network(net_str, strict=False))
                except ValueError as e:
                    log.warning("Invalid IP network pattern in ALLOWED_IPS: %s (%s)", net_str, e)

        if self._cached_allowed_nets is None:
            return True
        return any(client_addr in net for net in self._cached_allowed_nets)

    async def handle_CONNECT(self, server: Any, session: Any, envelope: Any) -> str:
        """Enforces IP Whitelist filtering on incoming SMTP connections."""
        if session:
            setattr(session, "_connect_time", time.perf_counter())
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
                if not hasattr(self, "metrics_firewall_rejected_count"):
                    self.metrics_firewall_rejected_count = {}
                with self._lock:
                    if len(self.metrics_firewall_rejected_count) >= self.MAX_METRICS_ENTRIES and peer_ip not in self.metrics_firewall_rejected_count:
                        self.metrics_firewall_rejected_count.pop(next(iter(self.metrics_firewall_rejected_count)))
                    self.metrics_firewall_rejected_count[peer_ip] = self.metrics_firewall_rejected_count.get(peer_ip, 0) + 1
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
        t_start = getattr(session, "_connect_time", None) or time.perf_counter()

        if not is_triggered:
            log.debug("Early-dispatching MQTT publish for trigger payload on MAIL FROM...")
            await asyncio.to_thread(self.mqtt_publish, topic, config["MQTT_PAYLOAD"], "trigger", address)
        else:
            log.info("Topic %s is already in triggered state. Extending reset timer (Variant B) without duplicate ON publish.", topic)
            self.log_action("trigger (extended)", address, topic, config["MQTT_PAYLOAD"], True)

        trigger_dur = max(0.0001, time.perf_counter() - t_start)
        if not hasattr(self, "metrics_trigger_durations"):
            self.metrics_trigger_durations = {}
        with self._lock:
            if len(self.metrics_trigger_durations) >= self.MAX_METRICS_ENTRIES and address not in self.metrics_trigger_durations:
                self.metrics_trigger_durations.pop(next(iter(self.metrics_trigger_durations)))
            self.metrics_trigger_durations[address] = trigger_dur

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

        if not hasattr(self, "metrics_messages_received_count"):
            self.metrics_messages_received_count = {}
        with self._lock:
            if len(self.metrics_messages_received_count) >= self.MAX_METRICS_ENTRIES and mail_from not in self.metrics_messages_received_count:
                self.metrics_messages_received_count.pop(next(iter(self.metrics_messages_received_count)))
            self.metrics_messages_received_count[mail_from] = self.metrics_messages_received_count.get(mail_from, 0) + 1

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

        log.debug("Dispatching background email parsing and telemetry task...")
        is_triggered = topic in self.handles
        task = self.loop.create_task(
            self._process_email_background(envelope.original_content, topic, mail_from, is_triggered)
        )
        self.background_tasks.add(task)

        return "250 Message accepted for delivery"

    async def _process_email_background(self, original_content: bytes, topic: str, mail_from: str, is_triggered: bool) -> None:
        """Parses the email content, extracts Hikvision event telemetry, saves attachments, and publishes event JSON in background."""
        try:
            msg = await asyncio.to_thread(email.message_from_bytes, original_content, policy=default)
            if msg is None or not hasattr(msg, "get"):
                try:
                    msg = email.message_from_bytes(original_content, policy=default)
                except Exception:
                    msg = None

            subject = str(msg.get("Subject", "")) if msg and hasattr(msg, "get") else ""
            body_text = ""
            try:
                if msg and hasattr(msg, "is_multipart") and msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() in ("text/plain", "text/html"):
                            body_text += str(part.get_content() or "") + "\n"
                elif msg and hasattr(msg, "get_content"):
                    body_text = str(msg.get_content() or "")
                elif isinstance(original_content, bytes):
                    body_text = original_content.decode("utf-8", errors="ignore")
            except Exception:
                pass

            event_info = parse_hikvision_event(subject, body_text)

            # Record Prometheus metrics for event types and end-to-end camera latency
            cam_name = event_info.get("camera_name") or mail_from
            ev_key = (cam_name, event_info.get("event_type", "motion"), event_info.get("target_type", "unknown"))
            if not hasattr(self, "metrics_events_count"):
                self.metrics_events_count = {}
            self.metrics_events_count[ev_key] = self.metrics_events_count.get(ev_key, 0) + 1

            ev_time_str = event_info.get("event_time") or (msg.get("Date") if msg and hasattr(msg, "get") else None)
            if ev_time_str:
                try:
                    ev_timestamp = None
                    # 1. Try RFC 2822 date parsing with timezone offset first
                    parsed_tz = email.utils.parsedate_tz(str(ev_time_str))
                    if parsed_tz:
                        ev_timestamp = email.utils.mktime_tz(parsed_tz)
                    else:
                        clean_t = str(ev_time_str).replace(",", " ").strip()
                        try:
                            dt = datetime.fromisoformat(clean_t)
                            if dt.tzinfo is None:
                                ev_timestamp = dt.astimezone().timestamp()
                            else:
                                ev_timestamp = dt.timestamp()
                        except Exception:
                            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
                                try:
                                    dt = datetime.strptime(clean_t, fmt)
                                    ev_timestamp = dt.astimezone().timestamp()
                                    break
                                except ValueError:
                                    continue

                    if ev_timestamp is not None:
                        now_ts = datetime.now().timestamp()
                        latency = max(0.0, now_ts - ev_timestamp)
                        if latency < 86400:
                            if not hasattr(self, "metrics_camera_latencies"):
                                self.metrics_camera_latencies = {}
                            self.metrics_camera_latencies[cam_name] = latency
                except Exception:
                    pass

            saved_attachments = []
            if config.get("SAVE_ATTACHMENTS", True):
                saved_attachments = await asyncio.to_thread(self.save_attachments, msg, topic, is_triggered)

            # Associate event metadata & attachments with recent action
            if self.recent_actions:
                for action in self.recent_actions:
                    if (
                        action["type"] in ("trigger", "trigger (extended)")
                        and action["sender"] == mail_from
                        and action["topic"] == topic
                    ):
                        if saved_attachments:
                            action["attachments"] = saved_attachments
                        action["event_type"] = event_info["event_type"]
                        action["event_label"] = event_info["event_label"]
                        action["event_icon"] = event_info["event_icon"]
                        action["event_details"] = event_info
                        log.debug("Associated event %s %s with action", event_info["event_icon"], event_info["event_label"])
                        break

            self.save_status_file()

            # Publish detailed MQTT JSON Event Sub-topic: <topic>/event if enabled
            if parse_bool(config.get("ENABLE_EVENT_TOPIC", True)):
                event_topic = f"{topic}/event"
                event_payload = json.dumps({
                    "event": event_info["event_type"],
                    "label": event_info["event_label"],
                    "line": event_info["line_number"],
                    "region": event_info["region_number"],
                    "target": event_info["target_type"],
                    "camera_name": event_info["camera_name"],
                    "device_model": event_info["device_model"],
                    "event_time": event_info["event_time"],
                    "attachments": [a["filename"] for a in saved_attachments] if saved_attachments else []
                }, ensure_ascii=False)

                await asyncio.to_thread(self.mqtt_publish, event_topic, event_payload, "event_metadata", mail_from)
            else:
                log.debug("Detailed event sub-topic publishing is disabled by ENABLE_EVENT_TOPIC configuration.")

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

    def mqtt_publish(self, topic: str, payload: str, action_type: str = "trigger", sender: str = "system", wait_for_publish: bool = False, event_info: Optional[Dict[str, Any]] = None) -> None:
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
            self.log_action(action_type, sender, topic, payload, success, event_info)

    async def trigger_camera_event(
        self,
        sender: str,
        event_type: str = "motion",
        target_type: str = "unknown",
        details: Optional[Dict[str, Any]] = None,
        source: str = "isapi"
    ) -> None:
        """Processes instant camera event trigger (< 5 ms latency) from ISAPI stream."""
        sanitized_sender = (
            sender.replace("@", "-")
            .replace("/", "_")
            .replace("+", "_")
            .replace("#", "_")
        )
        topic = f"{config['MQTT_TOPIC']}/{sanitized_sender}"
        is_triggered = topic in self.handles
        t_start = time.perf_counter()

        event_label = details.get("event_label") if details else "Motion Detection"
        event_icon = details.get("event_icon") if details else "📹"

        event_meta = {
            "event_type": event_type,
            "event_label": event_label,
            "event_icon": event_icon,
            "target_type": target_type,
            "camera_name": details.get("channel_name") if details else None,
            "event_time": details.get("event_time") if details else datetime.now().isoformat(),
            "source": source,
            "raw_details": details or {}
        }

        if not is_triggered:
            log.info("[%s] Early ISAPI trigger publishing MQTT payload for topic: %s (event: %s, target: %s)", sender, topic, event_type, target_type)
            await asyncio.to_thread(self.mqtt_publish, topic, config["MQTT_PAYLOAD"], "trigger", sender, False, event_meta)
        else:
            log.debug("[%s] Topic %s already triggered. Extending reset timer (Variant B, source: %s).", sender, topic, source)
            # Update latest active action in recent_actions without creating flood of duplicate rows
            updated_existing = False
            for act in self.recent_actions:
                if act.get("topic") == topic and act.get("status") == "SUCCESS" and "trigger" in act.get("type", ""):
                    act["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    act["event_details"] = event_meta
                    updated_existing = True
                    break
            if not updated_existing:
                self.log_action("trigger (extended)", sender, topic, config["MQTT_PAYLOAD"], True, event_meta)

        trigger_dur = max(0.0001, time.perf_counter() - t_start)
        if not hasattr(self, "metrics_trigger_durations"):
            self.metrics_trigger_durations = {}
        self.metrics_trigger_durations[sender] = trigger_dur

        # Cancel existing reset timer and schedule new sliding window
        if topic in self.handles:
            self.handles.pop(topic).cancel()

        if self.reset_time > 0:
            reset_time_seconds = float(self.reset_time)
            self.handles[topic] = self.loop.call_later(
                reset_time_seconds, self._trigger_reset, topic
            )

        # Publish event metadata topic if enabled (only on initial trigger)
        if parse_bool(config.get("ENABLE_EVENT_TOPIC", True)) and not is_triggered:
            event_topic = f"{topic}/event"
            event_payload = json.dumps({
                "event": event_type,
                "label": event_label,
                "target": target_type,
                "source": source,
                "camera_name": details.get("channel_name") if details else None,
                "event_time": details.get("event_time") if details else datetime.now().isoformat(),
                "details": details or {}
            })
            await asyncio.to_thread(self.mqtt_publish, event_topic, event_payload, "event_metadata", sender)

        # Update metrics
        cam_key = sender
        ev_key = (cam_key, event_type, target_type)
        if not hasattr(self, "metrics_events_count"):
            self.metrics_events_count = {}
        self.metrics_events_count[ev_key] = self.metrics_events_count.get(ev_key, 0) + 1

    async def start_isapi_streams(self) -> None:
        """Parses ISAPI_CAMERAS (JSON list or comma-delimited string) and starts persistent alertStream background workers."""
        if not parse_bool(config.get("ENABLE_ISAPI", False)):
            return
        
        cameras_cfg = config.get("ISAPI_CAMERAS", "")
        if not cameras_cfg:
            log.info("ISAPI stream enabled but ISAPI_CAMERAS is empty. No streams to start.")
            return

        default_user = str(config.get("ISAPI_USER", "admin")).strip()
        default_pwd = str(config.get("ISAPI_PASSWORD", "")).strip()
        
        self.isapi_running = True
        self.isapi_stream_tasks = []
        
        camera_entries: List[Dict[str, Any]] = []
        # Try JSON format first
        if isinstance(cameras_cfg, list):
            camera_entries = cameras_cfg
        elif isinstance(cameras_cfg, str) and (cameras_cfg.strip().startswith("[") or cameras_cfg.strip().startswith("{")):
            try:
                parsed = json.loads(cameras_cfg)
                if isinstance(parsed, list):
                    camera_entries = parsed
                elif isinstance(parsed, dict):
                    camera_entries = [parsed]
            except Exception:
                camera_entries = []

        if not camera_entries and isinstance(cameras_cfg, str):
            # Parse legacy comma-delimited list: "10.0.40.103:cam3@nm315.cz, 10.0.40.104:cam4@nm315.cz"
            for entry in cameras_cfg.split(","):
                entry = entry.strip()
                if not entry:
                    continue
                parts = entry.split(":")
                if len(parts) == 1:
                    ip = parts[0].strip()
                    port = 80
                    sender = f"cam_{ip}"
                elif len(parts) == 2:
                    ip = parts[0].strip()
                    if parts[1].strip().isdigit():
                        port = int(parts[1].strip())
                        sender = f"cam_{ip}"
                    else:
                        port = 80
                        sender = parts[1].strip()
                else:
                    ip = parts[0].strip()
                    port = int(parts[1].strip()) if parts[1].strip().isdigit() else 80
                    sender = parts[2].strip()
                
                camera_entries.append({
                    "ip": ip,
                    "port": port,
                    "sender": sender,
                    "user": default_user,
                    "password": default_pwd
                })

        for cam in camera_entries:
            ip = str(cam.get("ip", "")).strip()
            if not ip:
                continue
            try:
                port = int(cam.get("port", 80))
            except (ValueError, TypeError):
                port = 80
            sender = str(cam.get("sender") or f"cam_{ip}").strip()
            user = str(cam.get("user") or default_user).strip()
            pwd = str(cam.get("password") if cam.get("password") is not None else default_pwd)

            self.isapi_status[sender] = {
                "ip": ip,
                "port": port,
                "sender": sender,
                "user": user,
                "status": "initializing",
                "last_event_time": None,
                "last_event_type": None,
                "events_count": 0,
            }
            
            task = self.loop.create_task(self._isapi_camera_worker(ip, port, sender, user, pwd))
            self.isapi_stream_tasks.append(task)
            log.info("Registered ISAPI stream task for %s (%s:%d)", sender, ip, port)

    def stop_isapi_streams(self) -> None:
        """Stops all running ISAPI alertStream workers."""
        self.isapi_running = False
        if hasattr(self, "isapi_stream_tasks") and self.isapi_stream_tasks:
            log.info("Stopping %d ISAPI stream tasks...", len(self.isapi_stream_tasks))
            for task in self.isapi_stream_tasks:
                task.cancel()
            self.isapi_stream_tasks.clear()

    async def _isapi_camera_worker(self, ip: str, port: int, sender: str, user: str, pwd: str) -> None:
        """Maintains persistent HTTP Digest Auth alertStream connection with automatic exponential backoff reconnect."""
        log.info("[%s] ISAPI stream worker started for %s:%d", sender, ip, port)
        retry_delay = 2
        while self.isapi_running:
            try:
                self.isapi_status[sender]["status"] = "connecting"
                await asyncio.to_thread(self._run_isapi_stream_sync, ip, port, sender, user, pwd)
                # Successful run: reset retry delay
                retry_delay = 2
            except asyncio.CancelledError:
                log.info("[%s] ISAPI stream worker cancelled.", sender)
                break
            except Exception as e:
                log.warning("[%s] ISAPI stream connection error: %s", sender, e)
            
            if not self.isapi_running:
                break
            self.isapi_status[sender]["status"] = "reconnecting"
            try:
                log.debug("[%s] Reconnecting ISAPI stream in %d seconds...", sender, retry_delay)
                await asyncio.sleep(retry_delay)
                retry_delay = min(60, int(retry_delay * 2.5))
            except asyncio.CancelledError:
                break

    def _run_isapi_stream_sync(self, ip: str, port: int, sender: str, user: str, pwd: str) -> None:
        """Synchronously reads multipart/mixed boundary chunks from /ISAPI/Event/notification/alertStream."""
        if requests is None or HTTPDigestAuth is None:
            log.error("[%s] 'requests' module not available for ISAPI AlertStream", sender)
            self.isapi_status[sender]["status"] = "error_missing_requests"
            return

        url = f"http://{ip}:{port}/ISAPI/Event/notification/alertStream"
        auth = HTTPDigestAuth(user, pwd) if user and pwd else None
        
        try:
            with requests.get(url, auth=auth, stream=True, timeout=(8, None)) as resp:
                if resp.status_code != 200:
                    log.error("[%s] ISAPI AlertStream failed with HTTP status %d", sender, resp.status_code)
                    self.isapi_status[sender]["status"] = f"error_http_{resp.status_code}"
                    return

                log.info("[%s] ISAPI AlertStream connected successfully (HTTP 200 OK)", sender)
                self.isapi_status[sender]["status"] = "connected"
                self.isapi_status[sender]["connected_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                buffer: List[str] = []
                in_alert = False
                for line_bytes in resp.iter_lines(chunk_size=1024):
                    if not self.isapi_running:
                        break
                    if line_bytes is None:
                        continue
                    line = line_bytes.decode("utf-8", errors="ignore").strip()
                    if "<EventNotificationAlert" in line:
                        buffer = [line]
                        in_alert = True
                    elif "</EventNotificationAlert>" in line and in_alert:
                        buffer.append(line)
                        xml_content = "\n".join(buffer)
                        in_alert = False
                        buffer = []
                        
                        alert_info = parse_hikvision_isapi_alert(xml_content)
                        if alert_info.get("event_state") != "inactive":
                            ev_type = alert_info.get("event_type", "motion")
                            tg_type = alert_info.get("target_type", "unknown")
                            filter_mode = str(config.get("ISAPI_FILTER_MODE", "smart_or_acusense"))

                            if not is_isapi_event_permitted(ev_type, tg_type, filter_mode):
                                log.debug("[%s] Filtered out ISAPI event '%s' (target: %s) by filter_mode '%s'", sender, ev_type, tg_type, filter_mode)
                                continue

                            self.isapi_status[sender]["events_count"] = self.isapi_status[sender].get("events_count", 0) + 1
                            self.isapi_status[sender]["last_event_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            self.isapi_status[sender]["last_event_type"] = ev_type
                            
                            asyncio.run_coroutine_threadsafe(
                                self.trigger_camera_event(
                                    sender=sender,
                                    event_type=ev_type,
                                    target_type=tg_type,
                                    details=alert_info,
                                    source="isapi"
                                ),
                                self.loop
                            )
                    elif in_alert:
                        buffer.append(line)
        except Exception as e:
            if self.isapi_running:
                log.warning("[%s] ISAPI stream connection dropped: %s", sender, e)
                self.isapi_status[sender]["status"] = "disconnected"
            raise

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

    def get_all_known_camera_topics(self) -> List[str]:
        """Collects all configured or recently triggered camera MQTT topics."""
        root_topic = str(config.get("MQTT_TOPIC", "smtp2mqtt")).strip()
        topics = set()

        # 1. From ISAPI_CAMERAS configuration
        cameras_cfg = config.get("ISAPI_CAMERAS", "")
        if isinstance(cameras_cfg, list):
            for cam in cameras_cfg:
                sender = str(cam.get("sender") or ("cam_" + str(cam.get("ip", "")))).strip()
                if sender:
                    sanitized = sender.replace("@", "-").replace("/", "_").replace("+", "_").replace("#", "_")
                    topics.add(f"{root_topic}/{sanitized}")
        elif isinstance(cameras_cfg, str) and cameras_cfg.strip():
            try:
                parsed = json.loads(cameras_cfg)
                if isinstance(parsed, list):
                    for cam in parsed:
                        sender = str(cam.get("sender") or ("cam_" + str(cam.get("ip", "")))).strip()
                        if sender:
                            sanitized = sender.replace("@", "-").replace("/", "_").replace("+", "_").replace("#", "_")
                            topics.add(f"{root_topic}/{sanitized}")
            except Exception:
                for entry in cameras_cfg.split(","):
                    parts = entry.strip().split(":")
                    if len(parts) >= 3:
                        sender = parts[2].strip()
                    elif len(parts) == 2 and not parts[1].strip().isdigit():
                        sender = parts[1].strip()
                    elif len(parts) >= 1 and parts[0].strip():
                        sender = f"cam_{parts[0].strip()}"
                    else:
                        sender = ""
                    if sender:
                        sanitized = sender.replace("@", "-").replace("/", "_").replace("+", "_").replace("#", "_")
                        topics.add(f"{root_topic}/{sanitized}")

        # 2. From recent actions
        for act in self.recent_actions:
            t = act.get("topic")
            if t and t.startswith(root_topic) and not t.endswith("/event"):
                topics.add(t)

        # 3. From active timer handles
        for t in self.handles.keys():
            if t and t.startswith(root_topic) and not t.endswith("/event"):
                topics.add(t)

        return sorted(list(topics))

    def reset_all_camera_topics(self, reason: str = "manual") -> int:
        """Immediately publishes reset payload (0) to all known camera topics and cancels pending handles."""
        topics = self.get_all_known_camera_topics()
        reset_payload = str(config.get("MQTT_RESET_PAYLOAD", "0"))
        log.info("Resetting %d camera topic(s) to '%s' (reason: %s)...", len(topics), reset_payload, reason)

        # Cancel active in-memory timer handles
        for t, handle in list(self.handles.items()):
            try:
                handle.cancel()
            except Exception:
                pass
        self.handles.clear()

        # Publish 0 to all topics
        count = 0
        for topic in topics:
            try:
                self.mqtt_publish(topic, reset_payload, "reset", "system", wait_for_publish=True)
                count += 1
            except Exception as e:
                log.error("Failed to reset topic %s: %s", topic, e)

        return count

    async def sync_startup_resets(self) -> None:
        """Runs once on startup / MQTT reconnect to ensure all camera signals in Loxone are cleanly set to 0."""
        await asyncio.sleep(0.5)
        topics = self.get_all_known_camera_topics()
        if not topics:
            return
        log.info("Startup Zero-Sync: Broadcasting reset payload '%s' to %d known camera topic(s)...", config.get("MQTT_RESET_PAYLOAD", "0"), len(topics))
        for topic in topics:
            await asyncio.to_thread(
                self.mqtt_publish,
                topic,
                config["MQTT_RESET_PAYLOAD"],
                "reset",
                "system",
                False,
                {"event_type": "reset", "event_label": "Startup Zero-Sync (0)", "event_icon": "🧹", "source": "reset"}
            )

    def cancel_all_resets(self) -> None:
        """Flushes reset payload (0) to active topics, cancels pending timers, and gracefully stops tasks."""
        self.stop_isapi_streams()
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

        # Graceful Shutdown Flush: send 0 to all currently active triggered topics before closing MQTT
        if self.handles:
            log.info("Graceful Shutdown: Flushing reset payload '0' to %d active topic(s)...", len(self.handles))
            for topic, handle in list(self.handles.items()):
                try:
                    handle.cancel()
                except Exception:
                    pass
                try:
                    self.mqtt_publish(topic, config["MQTT_RESET_PAYLOAD"], "reset", "system", wait_for_publish=True)
                except Exception as e:
                    log.error("Failed to flush shutdown reset for %s: %s", topic, e)
            self.handles.clear()
        
        # Stop and disconnect persistent MQTT client
        if hasattr(self, "_mqtt_client") and self._mqtt_client is not None:
            log.info("Stopping persistent MQTT client loop...")
            try:
                self._mqtt_client.loop_stop()
                self._mqtt_client.disconnect()
            except Exception as e:
                log.error("Error stopping persistent MQTT client: %s", e)

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

        sanitized_isapi_status = {}
        for s_key, s_val in getattr(self, "isapi_status", {}).items():
            if isinstance(s_val, dict):
                s_copy = dict(s_val)
                if "password" in s_copy:
                    s_copy["password"] = "******"
                if "pwd" in s_copy:
                    s_copy["pwd"] = "******"
                sanitized_isapi_status[s_key] = s_copy
            else:
                sanitized_isapi_status[s_key] = s_val

        with self._lock:
            recent_acts_copy = list(self.recent_actions)

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
            "recent_actions": recent_acts_copy,
            "recent_blocked_attempts": list(getattr(self, "recent_blocked_attempts", [])),
            "version": VERSION,
            "latest_version": self.latest_version,
            "update_available": self.update_available,
            "version_check_status": self.version_check_status,
            "isapi_enabled": parse_bool(config.get("ENABLE_ISAPI", False)),
            "isapi_status": sanitized_isapi_status,
        }

    def generate_prometheus_metrics(self) -> str:
        """Generates native OpenMetrics / Prometheus text output for scraping."""
        if not parse_bool(config.get("ENABLE_METRICS", True)):
            return (
                "# HELP smtp2mqtt_metrics_enabled Metrics exporter status (0 = disabled by config)\n"
                "# TYPE smtp2mqtt_metrics_enabled gauge\n"
                "smtp2mqtt_metrics_enabled 0\n"
            )

        lines = []
        uptime = int((datetime.now() - self.start_time).total_seconds())
        mqtt_ok = 1 if (self.mqtt_connected_status if self.mqtt_connected_status is not None else False) else 0
        smtp_ok = 1 if self.smtp_connected_status else 0

        lines.append("# HELP smtp2mqtt_up Service operational status (1 = up)")
        lines.append("# TYPE smtp2mqtt_up gauge")
        lines.append("smtp2mqtt_up 1")

        lines.append("# HELP smtp2mqtt_uptime_seconds Total uptime of the service in seconds")
        lines.append("# TYPE smtp2mqtt_uptime_seconds counter")
        lines.append(f"smtp2mqtt_uptime_seconds {uptime}")

        lines.append("# HELP smtp2mqtt_mqtt_connected Connection status to MQTT broker (1 = connected, 0 = disconnected)")
        lines.append("# TYPE smtp2mqtt_mqtt_connected gauge")
        lines.append(f"smtp2mqtt_mqtt_connected {mqtt_ok}")

        lines.append("# HELP smtp2mqtt_smtp_listener_active SMTP listener status (1 = active, 0 = inactive)")
        lines.append("# TYPE smtp2mqtt_smtp_listener_active gauge")
        lines.append(f"smtp2mqtt_smtp_listener_active {smtp_ok}")

        lines.append("# HELP smtp2mqtt_processed_messages_total Total count of processed SMTP messages")
        lines.append("# TYPE smtp2mqtt_processed_messages_total counter")
        lines.append(f"smtp2mqtt_processed_messages_total {self.processed_messages_count}")

        lines.append("# HELP smtp2mqtt_active_reset_timers Current number of active topic reset timers")
        lines.append("# TYPE smtp2mqtt_active_reset_timers gauge")
        lines.append(f"smtp2mqtt_active_reset_timers {len(self.handles)}")

        # ISAPI streams status
        isapi_streams = getattr(self, "isapi_status", {})
        if isapi_streams:
            lines.append("# HELP smtp2mqtt_isapi_stream_connected ISAPI stream connection status (1 = connected, 0 = disconnected)")
            lines.append("# TYPE smtp2mqtt_isapi_stream_connected gauge")
            for sender, s_info in isapi_streams.items():
                safe_sender = str(sender).replace('"', '\\"')
                safe_ip = str(s_info.get("ip", "")).replace('"', '\\"')
                s_val = 1 if s_info.get("status") == "connected" else 0
                lines.append(f'smtp2mqtt_isapi_stream_connected{{camera="{safe_sender}",ip="{safe_ip}"}} {s_val}')

        # Camera Motion / Trigger Active State (1 = motion active / holding timer, 0 = idle)
        lines.append("# HELP smtp2mqtt_camera_motion_state Real-time motion detection state per camera (1 = active/holding, 0 = idle)")
        lines.append("# TYPE smtp2mqtt_camera_motion_state gauge")
        all_cams = set()
        if isapi_streams:
            all_cams.update(isapi_streams.keys())
        if hasattr(self, "metrics_events_count"):
            for c, _, _ in self.metrics_events_count.keys():
                all_cams.add(c)
        if hasattr(self, "allowed_senders") and self.allowed_senders:
            all_cams.update(self.allowed_senders)
        if not all_cams:
            all_cams.add("default")
        for cam in sorted(all_cams):
            sanitized_sender = str(cam).replace("@", "-").replace("/", "_").replace("+", "_").replace("#", "_")
            topic = f"{config.get('MQTT_TOPIC', 'smtp2mqtt')}/{sanitized_sender}"
            is_active = 1 if topic in self.handles else 0
            safe_cam = str(cam).replace('"', '\\"')
            lines.append(f'smtp2mqtt_camera_motion_state{{camera="{safe_cam}"}} {is_active}')

        # Camera to MQTT Latencies
        lines.append("# HELP smtp2mqtt_camera_to_mqtt_latency_seconds Estimated event age / clock skew from camera detection timestamp in seconds")
        lines.append("# TYPE smtp2mqtt_camera_to_mqtt_latency_seconds gauge")
        cam_latencies = getattr(self, "metrics_camera_latencies", {})
        if cam_latencies:
            for cam, lat in cam_latencies.items():
                safe_cam = str(cam).replace('"', '\\"')
                lines.append(f'smtp2mqtt_camera_to_mqtt_latency_seconds{{camera="{safe_cam}"}} {lat:.4f}')
        else:
            lines.append('smtp2mqtt_camera_to_mqtt_latency_seconds{camera="default"} 0.0')

        # Real Trigger Execution Duration
        lines.append("# HELP smtp2mqtt_trigger_duration_seconds Real execution duration from SMTP connection/MAIL FROM to MQTT publish in seconds")
        lines.append("# TYPE smtp2mqtt_trigger_duration_seconds gauge")
        trig_durations = getattr(self, "metrics_trigger_durations", {})
        if trig_durations:
            for cam, dur in trig_durations.items():
                safe_cam = str(cam).replace('"', '\\"')
                lines.append(f'smtp2mqtt_trigger_duration_seconds{{camera="{safe_cam}"}} {dur:.4f}')
        else:
            lines.append('smtp2mqtt_trigger_duration_seconds{camera="default"} 0.0')

        # Events breakdown
        lines.append("# HELP smtp2mqtt_events_detected_total Total count of security events detected by camera, type, and target")
        lines.append("# TYPE smtp2mqtt_events_detected_total counter")
        events_counter = getattr(self, "metrics_events_count", {})
        if events_counter:
            for (cam, ev_type, target), count in events_counter.items():
                safe_cam = str(cam).replace('"', '\\"')
                lines.append(f'smtp2mqtt_events_detected_total{{camera="{safe_cam}",event_type="{ev_type}",target="{target}"}} {count}')
        else:
            lines.append('smtp2mqtt_events_detected_total{camera="default",event_type="motion",target="unknown"} 0')

        # Firewall rejected attempts
        lines.append("# HELP smtp2mqtt_firewall_rejected_total Total connection attempts blocked by ALLOWED_IPS firewall")
        lines.append("# TYPE smtp2mqtt_firewall_rejected_total counter")
        blocked_counter = getattr(self, "metrics_firewall_rejected_count", {})
        if blocked_counter:
            for ip, count in blocked_counter.items():
                lines.append(f'smtp2mqtt_firewall_rejected_total{{ip="{ip}"}} {count}')
        else:
            lines.append('smtp2mqtt_firewall_rejected_total{ip="none"} 0')

        return "\n".join(lines) + "\n"

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
            elif path.startswith("/api/probe_camera"):
                import urllib.parse
                parsed_url = urllib.parse.urlparse(path)
                q_params = urllib.parse.parse_qs(parsed_url.query)
                probe_ip = q_params.get("ip", [""])[0]
                probe_port = int(q_params.get("port", ["80"])[0]) if q_params.get("port", ["80"])[0].isdigit() else 80
                probe_user = q_params.get("user", [str(config.get("ISAPI_USER", "admin"))])[0]
                probe_pwd = q_params.get("password", q_params.get("pwd", [str(config.get("ISAPI_PASSWORD", ""))]))[0]

                if not probe_ip:
                    probe_res = {"success": False, "error": "Missing 'ip' query parameter"}
                else:
                    probe_res = await asyncio.to_thread(probe_camera_isapi, probe_ip, probe_port, probe_user, probe_pwd)

            elif path.startswith("/api/reset_all") or path.startswith("/reset_all"):
                reset_count = self.reset_all_camera_topics(reason="web_api")
                res = {
                    "success": True,
                    "reset_count": reset_count,
                    "message": f"Successfully published reset payload ('{config.get('MQTT_RESET_PAYLOAD', '0')}') to {reset_count} camera topic(s)."
                }
                body = json.dumps(res, indent=2).encode("utf-8")
                content_type = "application/json"
            elif path == "/metrics":
                body = self.generate_prometheus_metrics().encode("utf-8")
                content_type = "text/plain; version=0.0.4; charset=utf-8"
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


def register_loxberry_log(loxberry_paths: Dict[str, str]) -> None:
    """Registers the daemon logfile in LoxBerry's SQLite Log Database so logmanager.cgi displays it."""
    log_dir = loxberry_paths.get("LBPLOG", "")
    if not log_dir:
        return
    log_file = os.path.join(log_dir, "smtp2mqtt.log")
    perl_cmd = f"""
use LoxBerry::Log;
my $log = LoxBerry::Log->new(
    name => 'daemon',
    package => 'smtp2mqtt',
    filename => '{log_file}',
    append => 1,
    addtime => 1
);
$log->LOGSTART('smtp2mqtt gateway session');
"""
    try:
        subprocess.run(["perl", "-e", perl_cmd], capture_output=True, timeout=5)
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to register log in LoxBerry LogDB: {e}\n")


def main():
    if "LBHOME" in loxberry_paths:
        register_loxberry_log(loxberry_paths)

    log.info("Starting smtp2mqtt gateway...")

    masked_cfg = mask_sensitive_config(config)
    log.debug("Configuration: %s", ", ".join([f"{k}={v}" for k, v in masked_cfg.items()]))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    handler = smtp2mqttHandler(loop)
    
    # Use UnthreadedController to run in the main asyncio event loop
    controller = UnthreadedController(
        handler=handler,
        loop=loop,
        hostname=config.get("SMTP_HOST", "0.0.0.0"),
        port=config["SMTP_PORT"],
        server_hostname=str(config.get("SMTP_SERVER_HOSTNAME", "smtp2mqtt")),
    )
    handler.smtp_controller = controller

    # Start the controller synchronously (schedules the server creation inside loop)
    controller.begin()
    log.info("SMTP server is listening on %s:%d", config.get("SMTP_HOST", "0.0.0.0"), config["SMTP_PORT"])

    # Start the web server if enabled
    web_server = None
    if parse_bool(config.get("ENABLE_WEB", True)):
        try:
            web_port = int(config.get("WEB_PORT", 8080))
            web_server = loop.run_until_complete(
                asyncio.start_server(
                    handler.handle_web_client,
                    "0.0.0.0",
                    web_port
                )
            )
            log.info("Web server is listening on http://0.0.0.0:%d", web_port)
        except Exception as e:
            log.error("Failed to start web server on port %s: %s", config.get("WEB_PORT"), e)

    # Start ISAPI alertStream listeners if enabled
    if parse_bool(config.get("ENABLE_ISAPI", False)):
        log.info("Starting Hikvision ISAPI AlertStream listeners...")
        loop.create_task(handler.start_isapi_streams())

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

