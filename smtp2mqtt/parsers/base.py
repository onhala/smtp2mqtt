from abc import ABC, abstractmethod
from typing import Optional
from smtp2mqtt.models.event import CameraEvent


class BaseCameraParser(ABC):
    """Abstract base class for camera brand email event parsers."""

    @property
    @abstractmethod
    def brand_name(self) -> str:
        """Returns the brand name identifier (e.g. hikvision, dahua, reolink, generic)."""
        pass

    @abstractmethod
    def matches(self, subject: str, body: str) -> bool:
        """Determines if this parser is suitable for the given email payload."""
        pass

    @abstractmethod
    def parse(self, subject: str, body: str) -> CameraEvent:
        """Parses email subject and body into a rich CameraEvent domain model."""
        pass
