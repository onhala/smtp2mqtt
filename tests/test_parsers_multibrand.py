import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from smtp2mqtt.models.event import EventType, TargetType
from smtp2mqtt.parsers.dahua import DahuaParser
from smtp2mqtt.parsers.generic import GenericParser
from smtp2mqtt.parsers.hikvision import HikvisionParser
from smtp2mqtt.parsers.registry import ParserRegistry, parse_camera_event
from smtp2mqtt.parsers.reolink import ReolinkParser


def test_hikvision_parser_vca_events():
    parser = HikvisionParser()
    assert parser.matches("Line Crossing Alarm", "EVENT TYPE: Line Crossing Detection")
    
    evt = parser.parse("Line Crossing Alarm", "EVENT TYPE: Line Crossing Detection\nEVENT INPUT: Line 2\nTARGET TYPE: Human")
    assert evt.event_type == EventType.LINE_CROSSING
    assert evt.line_number == 2
    assert evt.target_type == TargetType.HUMAN
    assert evt.event_icon == "🚶"


def test_dahua_parser_ivs_events():
    parser = DahuaParser()
    assert parser.matches("Dahua IPC-HFW Tripwire", "IVS Tripwire Event")
    
    evt = parser.parse("Dahua Alarm", "IVS Tripwire Event\nTarget: Person")
    assert evt.event_type == EventType.LINE_CROSSING
    assert "IVS Tripwire" in evt.event_label
    assert evt.target_type == TargetType.HUMAN


def test_reolink_parser_ai_events():
    parser = ReolinkParser()
    assert parser.matches("Reolink RLC-810A", "AI Person Detection")
    
    evt_person = parser.parse("Reolink Motion", "Person detected on Front Door")
    assert evt_person.target_type == TargetType.HUMAN
    assert evt_person.event_icon == "🚶"

    evt_vehicle = parser.parse("Reolink Motion", "Vehicle detected on Driveway")
    assert evt_vehicle.target_type == TargetType.VEHICLE
    assert evt_vehicle.event_icon == "🚗"

    evt_pet = parser.parse("Reolink Motion", "Pet detected in Garden")
    assert evt_pet.target_type == TargetType.PET
    assert evt_pet.event_icon == "🐾"


def test_generic_parser_fallback():
    parser = GenericParser()
    assert parser.matches("Axis P3245", "Motion alarm")
    
    evt = parser.parse("Axis P3245", "Motion alarm triggered")
    assert evt.event_type == EventType.MOTION
    assert evt.event_label == "Motion Detection"


def test_parser_registry_autodetect():
    registry = ParserRegistry()
    
    # Hikvision
    e1 = registry.parse("HiK Cam 3 Line Crossing", "EVENT TYPE: Line Crossing Detection\nEVENT INPUT: Line 1")
    assert e1.event_type == EventType.LINE_CROSSING
    
    # Dahua
    e2 = registry.parse("Dahua IPC Camera", "IVS Tripwire alarm")
    assert e2.event_type == EventType.LINE_CROSSING
    
    # Reolink
    e3 = registry.parse("Reolink RLC-811A", "Person detected")
    assert e3.target_type == TargetType.HUMAN
    
    # Fallback
    e4 = registry.parse("Unknown Camera", "Regular alert")
    assert e4.event_type == EventType.MOTION
