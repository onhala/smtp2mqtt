import re
from smtp2mqtt.models.event import CameraEvent, EventType, TargetType
from smtp2mqtt.parsers.base import BaseCameraParser


class DahuaParser(BaseCameraParser):
    """Parser specialized for Dahua / IMOU / CP PLUS IVS smart camera emails."""

    @property
    def brand_name(self) -> str:
        return "dahua"

    def matches(self, subject: str, body: str) -> bool:
        text = f"{subject} {body}".lower()
        return any(term in text for term in [
            "dahua", "imou", "cp plus", "ipc-", "sd-", "nvr4", "dvr", "ivs"
        ])

    def parse(self, subject: str, body: str) -> CameraEvent:
        subject_clean = (subject or "").strip()
        body_clean = (body or "").strip()
        full_text = f"{subject_clean}\n{body_clean}"

        event = CameraEvent()
        event.raw_details["brand"] = "dahua"

        if "tripwire" in full_text.lower() or "cross line" in full_text.lower():
            event.event_type = EventType.LINE_CROSSING
            event.event_label = "IVS Tripwire (Line Crossing)"
            event.event_icon = "🚶"
        elif "intrusion" in full_text.lower() or "zone" in full_text.lower():
            event.event_type = EventType.INTRUSION
            event.event_label = "IVS Intrusion Detection"
            event.event_icon = "🛡️"
        else:
            event.event_type = EventType.MOTION
            event.event_label = "Motion Alarm"
            event.event_icon = "📹"

        if re.search(r'\b(?:human|person|postava)\b', full_text, re.IGNORECASE):
            event.target_type = TargetType.HUMAN
        elif re.search(r'\b(?:vehicle|car|auto)\b', full_text, re.IGNORECASE):
            event.target_type = TargetType.VEHICLE

        return event
