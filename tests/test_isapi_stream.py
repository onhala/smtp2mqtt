import asyncio
import os
import sys
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bin.smtp2mqtt import (
    parse_hikvision_isapi_alert,
    smtp2mqttHandler,
    config,
)


def test_parse_hikvision_isapi_line_crossing():
    xml_str = """<EventNotificationAlert version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
<ipAddress>10.0.40.103</ipAddress>
<channelID>1</channelID>
<dateTime>2026-08-16T21:47:00+01:00</dateTime>
<eventType>linedetection</eventType>
<eventState>active</eventState>
<eventDescription>linedetection alarm</eventDescription>
<channelName>NM315 Vchod</channelName>
<DetectionTargetList>
  <DetectionTarget>
    <targetType>human</targetType>
  </DetectionTarget>
</DetectionTargetList>
</EventNotificationAlert>"""

    alert = parse_hikvision_isapi_alert(xml_str)
    assert alert["event_type"] == "line_crossing"
    assert alert["event_icon"] == "🚶"
    assert alert["target_type"] == "human"
    assert alert["channel_name"] == "NM315 Vchod"
    assert alert["channel_id"] == "1"
    assert alert["event_state"] == "active"


def test_parse_hikvision_isapi_field_intrusion():
    xml_str = """<EventNotificationAlert version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
<ipAddress>10.0.40.104</ipAddress>
<channelID>1</channelID>
<dateTime>2026-08-16T21:48:00+01:00</dateTime>
<eventType>fielddetection</eventType>
<eventState>active</eventState>
<eventDescription>fielddetection alarm</eventDescription>
<channelName>NM315 Zahrada</channelName>
<DetectionTargetList>
  <DetectionTarget>
    <targetType>vehicle</targetType>
  </DetectionTarget>
</DetectionTargetList>
</EventNotificationAlert>"""

    alert = parse_hikvision_isapi_alert(xml_str)
    assert alert["event_type"] == "intrusion"
    assert alert["event_icon"] == "🛡️"
    assert alert["target_type"] == "vehicle"
    assert alert["channel_name"] == "NM315 Zahrada"


def test_parse_hikvision_isapi_motion_and_empty():
    empty_alert = parse_hikvision_isapi_alert("")
    assert empty_alert["event_type"] == "motion"
    assert empty_alert["target_type"] == "unknown"

    motion_xml = """<EventNotificationAlert version="2.0">
<eventType>VMD</eventType>
<eventState>active</eventState>
<channelName>Parking</channelName>
</EventNotificationAlert>"""
    motion_alert = parse_hikvision_isapi_alert(motion_xml)
    assert motion_alert["event_type"] == "motion"
    assert motion_alert["channel_name"] == "Parking"


@pytest.mark.asyncio
async def test_trigger_camera_event_instant_publish():
    loop = asyncio.get_event_loop()
    handler = smtp2mqttHandler(loop)

    with patch.object(handler, "mqtt_publish") as mock_pub:
        details = {
            "event_label": "Line Crossing Detection",
            "event_icon": "🚶",
            "channel_name": "NM315 Vchod",
            "event_time": "2026-08-16T21:50:00+01:00",
        }
        await handler.trigger_camera_event(
            sender="cam3@nm315.cz",
            event_type="line_crossing",
            target_type="human",
            details=details,
            source="isapi",
        )

        assert mock_pub.called
        call_args = mock_pub.call_args_list[0]
        topic = call_args[0][0]
        payload = call_args[0][1]
        assert "cam3-nm315.cz" in topic
        assert payload == "1"

    handler.cancel_all_resets()


@pytest.mark.asyncio
async def test_isapi_stream_manager_lifecycle():
    loop = asyncio.get_event_loop()
    handler = smtp2mqttHandler(loop)

    config["ENABLE_ISAPI"] = "True"
    config["ISAPI_CAMERAS"] = "10.0.40.103:cam3@nm315.cz, 10.0.40.104:cam4@nm315.cz"
    config["ISAPI_USER"] = "admin"
    config["ISAPI_PASSWORD"] = "testpass"

    with patch.object(handler, "_run_isapi_stream_sync"):
        await handler.start_isapi_streams()
        assert handler.isapi_running is True
        assert len(handler.isapi_stream_tasks) == 2
        assert "cam3@nm315.cz" in handler.isapi_status
        assert "cam4@nm315.cz" in handler.isapi_status

        # Check status JSON contains isapi data
        status_json = handler.get_status_json()
        assert status_json["isapi_enabled"] is True
        assert "cam3@nm315.cz" in status_json["isapi_status"]

        # Check prometheus metrics include isapi streams
        metrics_str = handler.generate_prometheus_metrics()
        assert "smtp2mqtt_isapi_stream_connected" in metrics_str

        handler.stop_isapi_streams()
        assert handler.isapi_running is False
        assert len(handler.isapi_stream_tasks) == 0

    handler.cancel_all_resets()


def test_probe_camera_isapi():
    from bin.smtp2mqtt import probe_camera_isapi

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = """<DeviceInfo version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
<deviceName>NM315 Vchod</deviceName>
<model>DS-2CD2387G2-LSU/SL</model>
<firmwareVersion>V5.7.17</firmwareVersion>
</DeviceInfo>"""

    with patch("requests.get", return_value=mock_resp):
        res = probe_camera_isapi("10.0.40.103", 80, "admin", "pass")
        assert res["success"] is True
        assert res["model"] == "DS-2CD2387G2-LSU/SL"
        assert res["firmware"] == "V5.7.17"
        assert res["device_name"] == "NM315 Vchod"
        assert "Connected" in res["message"]


def test_probe_camera_isapi_auth_failure():
    from bin.smtp2mqtt import probe_camera_isapi

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"

    with patch("requests.get", return_value=mock_resp):
        res = probe_camera_isapi("10.0.40.103", 80, "admin", "wrong")
        assert res["success"] is False
        assert res["status_code"] == 401
        assert "Authentication Failed" in res["error"]


@pytest.mark.asyncio
async def test_isapi_stream_json_format_configuration():
    loop = asyncio.get_event_loop()
    handler = smtp2mqttHandler(loop)

    config["ENABLE_ISAPI"] = "True"
    config["ISAPI_CAMERAS"] = [
        {"ip": "10.0.40.103", "port": 80, "sender": "cam3@nm315.cz", "user": "admin", "password": "pass1"},
        {"ip": "10.0.40.104", "port": 80, "sender": "cam4@nm315.cz", "user": "admin", "password": "pass2"}
    ]

    with patch.object(handler, "_run_isapi_stream_sync"):
        await handler.start_isapi_streams()
        assert handler.isapi_running is True
        assert len(handler.isapi_stream_tasks) == 2
        assert "cam3@nm315.cz" in handler.isapi_status
        assert "cam4@nm315.cz" in handler.isapi_status

        handler.stop_isapi_streams()
        assert len(handler.isapi_stream_tasks) == 0

    handler.cancel_all_resets()

