from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class EventType(str, Enum):
    LINE_CROSSING = "line_crossing"
    INTRUSION = "intrusion"
    REGION_ENTRANCE = "region_entrance"
    REGION_EXITING = "region_exiting"
    LOITERING = "loitering"
    UNATTENDED_BAGGAGE = "unattended_baggage"
    OBJECT_REMOVAL = "object_removal"
    FACE_DETECTION = "face_detection"
    ANPR = "anpr"
    VMD = "vmd"
    MOTION = "motion"
    PIR = "pir"
    TAMPER = "tamper"
    SCENE_CHANGE = "scene_change"
    DEFOCUS = "defocus"
    AUDIO_EXCEPTION = "audio_exception"
    IO_ALARM = "io_alarm"
    DISK_ERROR = "disk_error"
    NETWORK_ERROR = "network_error"
    ILLEGAL_ACCESS = "illegal_access"
    UNKNOWN = "unknown"


class TargetType(str, Enum):
    HUMAN = "human"
    VEHICLE = "vehicle"
    PET = "pet"
    UNKNOWN = "unknown"


@dataclass
class CameraEvent:
    """Rich domain model representing a camera or NVR event."""
    event_type: EventType = EventType.MOTION
    event_label: str = "Motion Detection"
    event_icon: str = "📹"
    line_number: Optional[int] = None
    region_number: Optional[int] = None
    target_type: TargetType = TargetType.UNKNOWN
    camera_name: Optional[str] = None
    device_model: Optional[str] = None
    event_time: Optional[str] = None
    raw_details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "event_label": self.event_label,
            "event_icon": self.event_icon,
            "line_number": self.line_number,
            "region_number": self.region_number,
            "target_type": self.target_type.value,
            "camera_name": self.camera_name,
            "device_model": self.device_model,
            "event_time": self.event_time,
            "raw_details": self.raw_details,
        }
