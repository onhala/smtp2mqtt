import re
from smtp2mqtt.models.event import CameraEvent, EventType, TargetType
from smtp2mqtt.parsers.base import BaseCameraParser


class ReolinkParser(BaseCameraParser):
    """Parser specialized for Reolink smart camera emails."""

    @property
    def brand_name(self) -> str:
        return "reolink"

    def matches(self, subject: str, body: str) -> bool:
        text = f"{subject} {body}".lower()
        return "reolink" in text or "rlc-" in text

    def parse(self, subject: str, body: str) -> CameraEvent:
        subject_clean = (subject or "").strip()
        body_clean = (body or "").strip()
        full_text = f"{subject_clean}\n{body_clean}"

        event = CameraEvent()
        event.raw_details["brand"] = "reolink"

        if "person" in full_text.lower() or "human" in full_text.lower():
            event.event_type = EventType.MOTION
            event.event_label = "Reolink AI Person Detection"
            event.event_icon = "🚶"
            event.target_type = TargetType.HUMAN
        elif "vehicle" in full_text.lower() or "car" in full_text.lower():
            event.event_type = EventType.MOTION
            event.event_label = "Reolink AI Vehicle Detection"
            event.event_icon = "🚗"
            event.target_type = TargetType.VEHICLE
        elif "pet" in full_text.lower() or "animal" in full_text.lower():
            event.event_type = EventType.MOTION
            event.event_label = "Reolink AI Pet Detection"
            event.event_icon = "🐾"
            event.target_type = TargetType.PET
        else:
            event.event_type = EventType.MOTION
            event.event_label = "Reolink Motion Alarm"
            event.event_icon = "📹"

        return event
