from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from smtp2mqtt.models.event import CameraEvent


@dataclass
class ActionEntry:
    """Represents a logged gateway action (trigger, reset, security, system)."""
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    type: str = "trigger"
    sender: str = ""
    topic: str = ""
    payload: str = "1"
    status: str = "SUCCESS"
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    event: Optional[CameraEvent] = None

    def to_dict(self) -> Dict[str, Any]:
        evt_dict = self.event.to_dict() if self.event else {}
        return {
            "timestamp": self.timestamp,
            "type": self.type,
            "sender": self.sender,
            "topic": self.topic,
            "payload": self.payload,
            "status": self.status,
            "attachments": self.attachments,
            "event_type": evt_dict.get("event_type", "motion"),
            "event_label": evt_dict.get("event_label", "Motion Detection"),
            "event_icon": evt_dict.get("event_icon", "📹"),
            "event_details": evt_dict,
        }
