import re
from typing import Any, Dict
from smtp2mqtt.models.event import CameraEvent, EventType, TargetType
from smtp2mqtt.parsers.base import BaseCameraParser


class HikvisionParser(BaseCameraParser):
    """Parser specialized for Hikvision / HiLook / Ezviz AcuSense and VCA camera emails."""

    @property
    def brand_name(self) -> str:
        return "hikvision"

    def matches(self, subject: str, body: str) -> bool:
        text = f"{subject} {body}".lower()
        return any(term in text for term in [
            "hikvision", "hilook", "hik cam", "ds-2cd", "hwi-", "nvr-",
            "line crossing", "field detection", "intrusion", "linedetection",
            "fielddetection", "regionentrance", "regionexiting", "event type:"
        ])

    def parse(self, subject: str, body: str) -> CameraEvent:
        subject_clean = (subject or "").strip()
        body_clean = (body or "").strip()
        full_text = f"{subject_clean}\n{body_clean}"

        event = CameraEvent()
        kv_pairs: Dict[str, Any] = {}

        for line in body_clean.splitlines():
            if ":" in line:
                parts = line.split(":", 1)
                k = parts[0].strip().upper()
                v = parts[1].strip()
                if k and v:
                    kv_pairs[k] = v

        event.raw_details = kv_pairs

        for k, v in kv_pairs.items():
            if "CAMERA NAME" in k:
                event.camera_name = v
            elif "DEVICE NAME" in k or "DVR NAME" in k:
                event.device_model = v
            elif "EVENT TIME" in k or "ALARM TIME" in k:
                event.event_time = v
            elif "TARGET TYPE" in k or "DETECTION TARGET" in k:
                t_val = str(v).lower()
                if "human" in t_val:
                    event.target_type = TargetType.HUMAN
                elif "vehicle" in t_val:
                    event.target_type = TargetType.VEHICLE

        line_match = re.search(r'(?:line|lineitem|čára|čára číslo)\s*(\d+)', full_text, re.IGNORECASE)
        if line_match:
            try:
                event.line_number = int(line_match.group(1))
            except ValueError:
                pass

        region_match = re.search(r'(?:region|field|zone|zóna|oblast)\s*(\d+)', full_text, re.IGNORECASE)
        if region_match:
            try:
                event.region_number = int(region_match.group(1))
            except ValueError:
                pass

        if event.target_type == TargetType.UNKNOWN:
            if re.search(r'\b(?:human|person|člověk|postava)\b', full_text, re.IGNORECASE):
                event.target_type = TargetType.HUMAN
            elif re.search(r'\b(?:vehicle|car|auto|vozidlo)\b', full_text, re.IGNORECASE):
                event.target_type = TargetType.VEHICLE

        text_lower = full_text.lower()

        if "line crossing" in text_lower or "linedetection" in text_lower or "překročení" in text_lower:
            event.event_type = EventType.LINE_CROSSING
            line_str = f" (Line {event.line_number})" if event.line_number else ""
            event.event_label = f"Line Crossing{line_str}"
            event.event_icon = "🚶"
        elif "field detection" in text_lower or "fielddetection" in text_lower or "intrusion" in text_lower or "narušení" in text_lower:
            event.event_type = EventType.INTRUSION
            reg_str = f" (Region {event.region_number})" if event.region_number else ""
            event.event_label = f"Intrusion Detection{reg_str}"
            event.event_icon = "🛡️"
        elif "region entrance" in text_lower or "regionentrance" in text_lower or "vstup do oblasti" in text_lower:
            event.event_type = EventType.REGION_ENTRANCE
            event.event_label = "Region Entrance"
            event.event_icon = "🚪"
        elif "region exiting" in text_lower or "regionexiting" in text_lower or "opuštění oblasti" in text_lower:
            event.event_type = EventType.REGION_EXITING
            event.event_label = "Region Exiting"
            event.event_icon = "🚪"
        elif "loitering" in text_lower or "postávání" in text_lower:
            event.event_type = EventType.LOITERING
            event.event_label = "Loitering Detection"
            event.event_icon = "⏳"
        elif "unattended baggage" in text_lower or "object left" in text_lower or "zavazadlo" in text_lower:
            event.event_type = EventType.UNATTENDED_BAGGAGE
            event.event_label = "Unattended Baggage"
            event.event_icon = "🧳"
        elif "object removal" in text_lower or "odebrání předmětu" in text_lower:
            event.event_type = EventType.OBJECT_REMOVAL
            event.event_label = "Object Removal"
            event.event_icon = "📦"
        elif "face detection" in text_lower or "facedetection" in text_lower or "obličej" in text_lower:
            event.event_type = EventType.FACE_DETECTION
            event.event_label = "Face Detection"
            event.event_icon = "👤"
        elif "anpr" in text_lower or "license plate" in text_lower or "spz" in text_lower:
            event.event_type = EventType.ANPR
            event.event_label = "Plate Recognition"
            event.event_icon = "🚗"
        elif "tamper" in text_lower or "sabotáž" in text_lower or "zakrytí" in text_lower:
            event.event_type = EventType.TAMPER
            event.event_label = "Video Tampering"
            event.event_icon = "⚠️"
        elif "scene change" in text_lower or "změna scény" in text_lower:
            event.event_type = EventType.SCENE_CHANGE
            event.event_label = "Scene Change"
            event.event_icon = "🔄"
        elif "defocus" in text_lower or "rozostření" in text_lower:
            event.event_type = EventType.DEFOCUS
            event.event_label = "Defocus Detection"
            event.event_icon = "🔍"
        elif "audio exception" in text_lower or "zvuková výjimka" in text_lower:
            event.event_type = EventType.AUDIO_EXCEPTION
            event.event_label = "Audio Exception"
            event.event_icon = "🔊"
        elif "pir" in text_lower:
            event.event_type = EventType.PIR
            event.event_label = "PIR Alarm"
            event.event_icon = "🚨"
        elif "alarm input" in text_lower or "io alarm" in text_lower:
            event.event_type = EventType.IO_ALARM
            event.event_label = "IO Alarm Input"
            event.event_icon = "⚡"
        elif "disk full" in text_lower or "disk error" in text_lower or "diskfull" in text_lower or "diskerror" in text_lower:
            event.event_type = EventType.DISK_ERROR
            event.event_label = "Disk Exception / Error"
            event.event_icon = "💾"
        elif "ip conflict" in text_lower or "ipconflict" in text_lower or "nicbroken" in text_lower:
            event.event_type = EventType.NETWORK_ERROR
            event.event_label = "Network / IP Error"
            event.event_icon = "🌐"
        elif "illegal access" in text_lower or "illaccess" in text_lower:
            event.event_type = EventType.ILLEGAL_ACCESS
            event.event_label = "Illegal Access Attempt"
            event.event_icon = "🔒"
        else:
            event.event_type = EventType.MOTION
            event.event_label = "Motion Detection"
            event.event_icon = "📹"

        return event
