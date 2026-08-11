from typing import List
from smtp2mqtt.models.event import CameraEvent
from smtp2mqtt.parsers.base import BaseCameraParser
from smtp2mqtt.parsers.dahua import DahuaParser
from smtp2mqtt.parsers.generic import GenericParser
from smtp2mqtt.parsers.hikvision import HikvisionParser
from smtp2mqtt.parsers.reolink import ReolinkParser


class ParserRegistry:
    """Registry managing camera brand event parsers with priority matching."""

    def __init__(self):
        self._parsers: List[BaseCameraParser] = [
            HikvisionParser(),
            DahuaParser(),
            ReolinkParser(),
            GenericParser(),  # Fallback must be last
        ]

    def register(self, parser: BaseCameraParser) -> None:
        """Registers a custom brand parser at top priority."""
        self._parsers.insert(0, parser)

    def parse(self, subject: str, body: str) -> CameraEvent:
        """Finds the first matching parser for the email payload and extracts CameraEvent."""
        for parser in self._parsers:
            if parser.matches(subject, body):
                return parser.parse(subject, body)
        return GenericParser().parse(subject, body)


_global_registry = ParserRegistry()


def parse_camera_event(subject: str, body: str) -> CameraEvent:
    """Global helper function to parse email subject & body into a CameraEvent."""
    return _global_registry.parse(subject, body)
