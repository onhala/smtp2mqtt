import asyncio
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from smtp2mqtt.adapters.mqtt_client import MQTTAdapter
from smtp2mqtt.core.timer_manager import TimerManager
from smtp2mqtt.handlers.firewall import IPFirewall
from smtp2mqtt.web.sse import SSEBroadcaster


@pytest.mark.asyncio
async def test_timer_manager_sliding_window():
    loop = asyncio.get_running_loop()
    tm = TimerManager(loop)
    
    reset_fired = []
    def on_reset(topic):
        reset_fired.append(topic)
        
    # Schedule reset in 0.1 seconds
    extended = await tm.schedule_reset("smtp2mqtt/test_cam", 0.1, on_reset)
    assert not extended
    assert await tm.is_triggered("smtp2mqtt/test_cam")
    
    # Extend before it expires
    extended = await tm.schedule_reset("smtp2mqtt/test_cam", 0.2, on_reset)
    assert extended
    
    await asyncio.sleep(0.3)
    assert "smtp2mqtt/test_cam" in reset_fired
    assert not await tm.is_triggered("smtp2mqtt/test_cam")


def test_ip_firewall_validation():
    fw = IPFirewall("192.168.1.0/24, 10.0.0.5")
    assert fw.is_allowed("192.168.1.50")
    assert fw.is_allowed("10.0.0.5")
    assert not fw.is_allowed("10.0.0.6")
    assert not fw.is_allowed("172.16.0.1")

    fw_all = IPFirewall("*")
    assert fw_all.is_allowed("1.2.3.4")


@pytest.mark.asyncio
async def test_sse_broadcaster_pub_sub():
    broadcaster = SSEBroadcaster()
    queue = broadcaster.subscribe()
    
    test_event = {"event_type": "line_crossing", "camera": "Cam1"}
    broadcaster.broadcast(test_event, "motion_alert")
    
    msg = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert "event: motion_alert" in msg
    assert "line_crossing" in msg
    
    broadcaster.unsubscribe(queue)
