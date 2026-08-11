from smtp2mqtt.models.event import CameraEvent, EventType, TargetType
from smtp2mqtt.parsers.base import BaseCameraParser


class GenericParser(BaseCameraParser):
    """Fallback parser for Axis, Mobotix, Uniview, and unclassified security cameras."""

    @property
    def brand_name(self) -> str:
        return "generic"

    def matches(self, subject: str, body: str) -> bool:
        return True

    def parse(self, subject: str, body: str) -> CameraEvent:
        event = CameraEvent()
        event.event_type = EventType.MOTION
        event.event_label = "Motion Detection"
        event.event_icon = "📹"
        event.target_type = TargetType.UNKNOWN
        event.raw_details["subject"] = subject
        return event
