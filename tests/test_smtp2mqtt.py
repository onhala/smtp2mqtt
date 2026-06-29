import os
import sys
import time
import shutil
import smtplib
import subprocess
import asyncio
import importlib
import logging
import json
import unittest.mock as mock
from email.message import EmailMessage
import pytest

# Add the project root to sys.path so we can import smtp2mqtt
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import smtp2mqtt

@pytest.fixture(autouse=True)
def prevent_real_socket_connections(monkeypatch):
    """Prevent any background monitoring threads from making real network connections by default."""
    monkeypatch.setattr(smtp2mqtt.smtp2mqttHandler, "_check_socket_connection", lambda self, host, port: False)

def test_parse_bool():
    """Verify boolean parsing helper handles various values correctly."""
    assert smtp2mqtt.parse_bool("True") is True
    assert smtp2mqtt.parse_bool("true") is True
    assert smtp2mqtt.parse_bool(True) is True
    assert smtp2mqtt.parse_bool("1") is True
    assert smtp2mqtt.parse_bool("yes") is True
    assert smtp2mqtt.parse_bool("on") is True
    assert smtp2mqtt.parse_bool("False") is False
    assert smtp2mqtt.parse_bool("false") is False
    assert smtp2mqtt.parse_bool(False) is False
    assert smtp2mqtt.parse_bool("0") is False
    assert smtp2mqtt.parse_bool(None) is False
    assert smtp2mqtt.parse_bool("random") is False

def test_config_loading_fallback_value_error():
    """Verify that configuration loading gracefully falls back to defaults on integer parsing error."""
    with mock.patch.dict(os.environ, {"SMTP_PORT": "not_an_int"}):
        importlib.reload(smtp2mqtt)
        assert smtp2mqtt.config["SMTP_PORT"] == 1025

def test_file_logger_setup_if_log_dir_exists():
    """Verify that file logger is initialized if 'log' directory exists."""
    os.makedirs("log", exist_ok=True)
    try:
        importlib.reload(smtp2mqtt)
        has_file_handler = any(isinstance(h, logging.FileHandler) for h in smtp2mqtt.log.handlers)
        assert has_file_handler is True
    finally:
        # Cleanup log directory and log handlers
        for h in list(smtp2mqtt.log.handlers):
            if isinstance(h, logging.FileHandler):
                h.close()
                smtp2mqtt.log.removeHandler(h)
        if os.path.exists("log"):
            shutil.rmtree("log")

def test_file_logger_setup_permission_error():
    """Verify that if FileHandler fails, we gracefully catch the error and log it."""
    os.makedirs("log", exist_ok=True)
    # Mock log.error on the module level logger or mock logging.FileHandler
    original_handlers = list(smtp2mqtt.log.handlers)
    try:
        with mock.patch("logging.FileHandler", side_effect=PermissionError("Permission denied")):
            with mock.patch("logging.Logger.error") as mock_error:
                importlib.reload(smtp2mqtt)
                # Verify that log.error was called
                any_msg_matches = any("Failed to set up file logger" in call[0][0] for call in mock_error.call_args_list)
                assert any_msg_matches is True
    finally:
        # Cleanup log directory and any new handlers added
        for h in list(smtp2mqtt.log.handlers):
            if h not in original_handlers:
                if isinstance(h, logging.FileHandler):
                    h.close()
                smtp2mqtt.log.removeHandler(h)
        if os.path.exists("log"):
            shutil.rmtree("log")

@pytest.mark.asyncio
async def test_smtp2mqtt_handler_saves_attachments():
    """Verify that attachments are parsed and stored in the attachments directory."""
    # Ensure a clean slate
    if os.path.exists("attachments"):
        shutil.rmtree("attachments")

    # Force SAVE_ATTACHMENTS = True
    smtp2mqtt.config["SAVE_ATTACHMENTS"] = True

    # Construct handler
    loop = mock.MagicMock()
    handler = smtp2mqtt.smtp2mqttHandler(loop)

    # Build standard email with image attachment
    msg = EmailMessage()
    msg["Subject"] = "Test trigger"
    msg["From"] = "camera@house.com"
    msg["To"] = "me@house.com"
    msg.set_content("Motion detected!")
    
    fake_image = b"XYZ-FAKE-IMAGE-DATA-XYZ"
    msg.add_attachment(fake_image, maintype="image", subtype="jpeg", filename="test_motion.jpg")

    # Call save_attachments
    handler.save_attachments(msg, "smtp2mqtt/camera-house.com", is_triggered=False)

    # Verify file was saved correctly
    assert os.path.exists("attachments")
    file_path = os.path.join("attachments", "test_motion.jpg")
    assert os.path.exists(file_path)
    
    with open(file_path, "rb") as f:
        saved_data = f.read()
    assert saved_data == fake_image

    # Cleanup
    shutil.rmtree("attachments")

@pytest.mark.asyncio
async def test_smtp2mqtt_handler_ignores_non_image_attachments():
    """Verify that non-image attachments are ignored and not saved to disk."""
    if os.path.exists("attachments"):
        shutil.rmtree("attachments")
        
    smtp2mqtt.config["SAVE_ATTACHMENTS"] = True
    loop = mock.MagicMock()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    msg = EmailMessage()
    msg["Subject"] = "Test non-image"
    msg["From"] = "sender@domain.com"
    msg.set_content("Check the text doc attachment")
    msg.add_attachment(b"some text", maintype="text", subtype="plain", filename="doc.txt")
    
    handler.save_attachments(msg, "smtp2mqtt/sender-domain.com", is_triggered=False)
    
    assert not os.path.exists("attachments") or len(os.listdir("attachments")) == 0

@pytest.mark.asyncio
async def test_smtp2mqtt_handler_skips_no_filename_attachments():
    """Verify that attachments without filename are safely skipped."""
    if os.path.exists("attachments"):
        shutil.rmtree("attachments")
        
    smtp2mqtt.config["SAVE_ATTACHMENTS"] = True
    loop = mock.MagicMock()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    msg = EmailMessage()
    msg["Subject"] = "Test no-name attachment"
    msg["From"] = "sender@domain.com"
    msg.set_content("No-name")
    
    part = mock.MagicMock()
    part.get_content_type.return_value = "image/jpeg"
    part.get_filename.return_value = None
    
    with mock.patch.object(msg, "iter_attachments", return_value=[part]):
        handler.save_attachments(msg, "smtp2mqtt/sender-domain.com", is_triggered=False)
        
    assert not os.path.exists("attachments") or len(os.listdir("attachments")) == 0

def test_smtp2mqtt_handler_save_attachments_exception():
    """Verify that exceptions during saving attachments are caught and logged gracefully."""
    loop = mock.MagicMock()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    msg = mock.MagicMock()
    msg.iter_attachments.side_effect = Exception("FileSystem error")
    
    # Should not raise exception
    handler.save_attachments(msg, "smtp2mqtt/sender-domain.com", is_triggered=False)

@pytest.mark.asyncio
async def test_smtp2mqtt_handler_prevents_path_traversal():
    """Verify that attachment filenames containing directory traversal characters are sanitized to prevent CWE-22."""
    if os.path.exists("attachments"):
        shutil.rmtree("attachments")

    smtp2mqtt.config["SAVE_ATTACHMENTS"] = True
    loop = mock.MagicMock()
    handler = smtp2mqtt.smtp2mqttHandler(loop)

    msg = EmailMessage()
    msg["Subject"] = "Test trigger"
    msg["From"] = "camera@house.com"
    msg["To"] = "me@house.com"
    msg.set_content("Motion detected!")
    
    fake_image = b"MALICIOUS-DATA"
    # Malicious filename with traversal path
    msg.add_attachment(fake_image, maintype="image", subtype="jpeg", filename="../../malicious_traversal.jpg")

    handler.save_attachments(msg, "smtp2mqtt/camera-house.com", is_triggered=False)

    # Verify attachments directory exists
    assert os.path.exists("attachments")
    
    # Verify the file was saved using only the base name and did NOT traverse out of attachments
    forbidden_path = os.path.abspath(os.path.join("attachments", "..", "malicious_traversal.jpg"))
    safe_path = os.path.abspath(os.path.join("attachments", "malicious_traversal.jpg"))
    
    assert not os.path.exists(forbidden_path)
    assert os.path.exists(safe_path)
    
    with open(safe_path, "rb") as f:
        assert f.read() == fake_image

    # Cleanup
    shutil.rmtree("attachments")

@pytest.mark.asyncio
async def test_smtp2mqtt_handler_sanitizes_mqtt_topic():
    """Verify that handles/senders with MQTT wildcards or directory separators are sanitized correctly in handle_DATA."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    envelope = mock.MagicMock()
    envelope.mail_from = "attacker+test/#/bypass@domain.com"
    envelope.original_content = b"From: attacker+test/#/bypass@domain.com\nTo: rcpt@domain.com\nSubject: Test\n\nBody"
    envelope.content = b"From: attacker+test/#/bypass@domain.com\nTo: rcpt@domain.com\nSubject: Test\n\nBody"
    
    with mock.patch.object(handler, "mqtt_publish") as mock_pub, \
         mock.patch.object(handler, "save_attachments") as mock_save:
        
        res = await handler.handle_DATA(None, None, envelope)
        
        assert res == "250 Message accepted for delivery"
        # The '@' becomes '-', '+' and '#' and '/' should become '_'
        expected_topic = "smtp2mqtt/attacker_test___bypass-domain.com"
        mock_pub.assert_called_once_with(expected_topic, "ON", "trigger", "attacker+test/#/bypass@domain.com")
        assert expected_topic in handler.handles
        
        handler.cancel_all_resets()

@pytest.mark.asyncio
async def test_smtp2mqtt_handler_handle_data_basic():
    """Verify that handle_DATA handles valid messages, publishes to MQTT, and schedules a reset timer."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    envelope = mock.MagicMock()
    envelope.mail_from = "sender@domain.com"
    envelope.original_content = b"From: sender@domain.com\nTo: rcpt@domain.com\nSubject: Test\n\nBody"
    envelope.content = b"From: sender@domain.com\nTo: rcpt@domain.com\nSubject: Test\n\nBody"
    
    with mock.patch.object(handler, "mqtt_publish") as mock_pub, \
         mock.patch.object(handler, "save_attachments") as mock_save:
        
        res = await handler.handle_DATA(None, None, envelope)
        
        assert res == "250 Message accepted for delivery"
        mock_pub.assert_called_once_with("smtp2mqtt/sender-domain.com", "ON", "trigger", "sender@domain.com")
        assert "smtp2mqtt/sender-domain.com" in handler.handles
        
        handler.cancel_all_resets()

@pytest.mark.asyncio
async def test_smtp2mqtt_handler_handle_data_parse_error():
    """Verify that handle_DATA returns a 500 error on message parsing failure."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    envelope = mock.MagicMock()
    envelope.mail_from = "sender@domain.com"
    envelope.original_content = b"Corrupted"
    
    with mock.patch("email.message_from_bytes", side_effect=Exception("parse error")):
        res = await handler.handle_DATA(None, None, envelope)
        assert "500 Error parsing message" in res

@pytest.mark.asyncio
async def test_smtp2mqtt_handler_save_attachments_during_reset_time_logic():
    """Verify SAVE_ATTACHMENTS_DURING_RESET_TIME config handles file saving rules properly when triggered."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    smtp2mqtt.config["SAVE_ATTACHMENTS"] = True
    
    envelope = mock.MagicMock()
    envelope.mail_from = "sender@domain.com"
    envelope.original_content = b"From: sender@domain.com\nTo: rcpt@domain.com\nSubject: Test\n\nBody"
    envelope.content = b"From: sender@domain.com\nTo: rcpt@domain.com\nSubject: Test\n\nBody"
    
    # 1. Topic already triggered, SAVE_ATTACHMENTS_DURING_RESET_TIME = False -> skip saving
    smtp2mqtt.config["SAVE_ATTACHMENTS_DURING_RESET_TIME"] = False
    handler.handles["smtp2mqtt/sender-domain.com"] = mock.MagicMock()
    
    with mock.patch.object(handler, "mqtt_publish"), \
         mock.patch.object(handler, "save_attachments") as mock_save:
        await handler.handle_DATA(None, None, envelope)
        mock_save.assert_not_called()
        
    # 2. Topic already triggered, SAVE_ATTACHMENTS_DURING_RESET_TIME = True -> save
    smtp2mqtt.config["SAVE_ATTACHMENTS_DURING_RESET_TIME"] = True
    handler.handles["smtp2mqtt/sender-domain.com"] = mock.MagicMock()
    
    with mock.patch.object(handler, "mqtt_publish"), \
         mock.patch.object(handler, "save_attachments") as mock_save:
        await handler.handle_DATA(None, None, envelope)
        mock_save.assert_called_once()
        
    handler.cancel_all_resets()

@pytest.mark.asyncio
async def test_smtp2mqtt_handler_mqtt_publish():
    """Verify that handler correctly publishes to MQTT broker via thread."""
    loop = mock.MagicMock()
    handler = smtp2mqtt.smtp2mqttHandler(loop)

    with mock.patch("smtp2mqtt.publish.single") as mock_publish_single:
        handler.mqtt_publish("test-topic", "ON")
        mock_publish_single.assert_called_once_with(
            "test-topic",
            "ON",
            hostname=smtp2mqtt.config["MQTT_HOST"],
            port=smtp2mqtt.config["MQTT_PORT"],
            auth=None
        )

def test_mqtt_publish_with_auth():
    """Verify that handler correctly includes username/password in MQTT publishing when configured."""
    loop = mock.MagicMock()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    smtp2mqtt.config["MQTT_USERNAME"] = "user"
    smtp2mqtt.config["MQTT_PASSWORD"] = "pass"
    
    with mock.patch("smtp2mqtt.publish.single") as mock_pub_single:
        handler.mqtt_publish("test-topic", "ON")
        mock_pub_single.assert_called_once_with(
            "test-topic",
            "ON",
            hostname=smtp2mqtt.config["MQTT_HOST"],
            port=smtp2mqtt.config["MQTT_PORT"],
            auth={"username": "user", "password": "pass"}
        )
        
    # Reset config
    smtp2mqtt.config["MQTT_USERNAME"] = ""
    smtp2mqtt.config["MQTT_PASSWORD"] = ""

def test_mqtt_publish_exception():
    """Verify that publish network exceptions are caught and logged gracefully."""
    loop = mock.MagicMock()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    with mock.patch("smtp2mqtt.publish.single", side_effect=Exception("network error")):
        # Should not raise exception
        handler.mqtt_publish("test-topic", "ON")

def test_mqtt_publish_persistent():
    """Verify that handler correctly publishes to MQTT broker via persistent client."""
    loop = mock.MagicMock()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    # Manually configure a mock persistent client
    mock_client = mock.MagicMock()
    mock_info = mock.MagicMock()
    mock_info.is_published.return_value = True
    mock_client.publish.return_value = mock_info
    
    handler._mqtt_client = mock_client
    
    handler.mqtt_publish("test-topic", "ON")
    
    mock_client.publish.assert_called_once_with("test-topic", "ON", qos=0)
    mock_info.wait_for_publish.assert_called_once_with(timeout=2.0)
    assert handler.last_publish_success is True

@pytest.mark.asyncio
async def test_smtp2mqtt_handler_trigger_reset():
    """Verify that _trigger_reset pops the handle and spawns async task for MQTT publish reset."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    topic = "smtp2mqtt/sender-domain.com"
    mock_handle = mock.MagicMock()
    handler.handles[topic] = mock_handle
    
    with mock.patch.object(handler, "mqtt_publish") as mock_pub:
        handler._trigger_reset(topic)
        
        assert topic not in handler.handles
        
        await asyncio.sleep(0.1)
        mock_pub.assert_called_once_with(topic, smtp2mqtt.config["MQTT_RESET_PAYLOAD"], "reset", "system")

def test_smtp2mqtt_handler_cancel_all_resets():
    """Verify that cancel_all_resets cancels all pending reset timers."""
    loop = mock.MagicMock()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    # Empty case should not raise error
    handler.cancel_all_resets()
    
    mock_handle_1 = mock.MagicMock()
    mock_handle_2 = mock.MagicMock()
    handler.handles["topic1"] = mock_handle_1
    handler.handles["topic2"] = mock_handle_2
    
    handler.cancel_all_resets()
    
    mock_handle_1.cancel.assert_called_once()
    mock_handle_2.cancel.assert_called_once()
    assert len(handler.handles) == 0

def test_main_function_graceful_run_and_exit():
    """Verify that main() initializes the gateway, runs the event loop, and shuts down cleanly."""
    mock_loop = mock.MagicMock(spec=asyncio.AbstractEventLoop)
    mock_server = mock.MagicMock()
    
    # We mock asyncio.new_event_loop to return our mock loop and mock start_server
    with mock.patch("asyncio.new_event_loop", return_value=mock_loop), \
         mock.patch("asyncio.start_server", return_value=mock_server), \
         mock.patch("smtp2mqtt.UnthreadedController") as mock_controller_cls:
        
        mock_controller = mock_controller_cls.return_value
        
        # Let's call main()
        smtp2mqtt.main()
        
        # Verify controller was instantiated and started
        mock_controller_cls.assert_called_once()
        mock_controller.begin.assert_called_once()
        
        # Verify run_forever was called on our mock loop
        mock_loop.run_forever.assert_called_once()
        
        # Verify controller.end was called in the finally block
        mock_controller.end.assert_called_once()
        
        # Verify loop was closed in the finally block
        mock_loop.close.assert_called_once()

def test_integration_flow():
    """Run full integration test with the actual running server subprocess."""
    # Choose a high port for local testing
    test_port = 1026
    
    # Configure environment
    env = os.environ.copy()
    env["SMTP_PORT"] = str(test_port)
    env["MQTT_HOST"] = "127.0.0.1"
    env["MQTT_PORT"] = "1883"
    env["DEBUG"] = "True"
    env["SAVE_ATTACHMENTS"] = "False"
    
    # Run smtp2mqtt.py in a separate process
    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smtp2mqtt.py"))
    
    process = subprocess.Popen(
        [sys.executable, script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env
    )
    
    # Give the server a moment to spin up and bind the port
    time.sleep(1.5)
    
    try:
        # Check that it didn't crash instantly
        assert process.poll() is None, f"Server crashed on startup with code {process.poll()}"
        
        # Test connecting and sending mail
        with smtplib.SMTP("127.0.0.1", test_port, timeout=5) as smtp:
            code, msg = smtp.ehlo()
            assert code == 250
            
            smtp.sendmail(
                "camera@house.com",
                ["me@house.com"],
                "Subject: Alert!\n\nMotion in Zone 2"
            )
            
        time.sleep(1.0)
        
        process.terminate()
        
        stdout, stderr = process.communicate(timeout=5)
        
        assert f"SMTP server is listening on 0.0.0.0:{test_port}" in stdout
        assert "Received SMTP message from camera@house.com" in stdout
        assert "Publishing payload 'ON' to topic 'smtp2mqtt/camera-house.com'" in stdout
        assert "Received termination signal" in stdout
        assert "smtp2mqtt gateway stopped successfully." in stdout
        
    except Exception as e:
        process.kill()
        stdout, stderr = process.communicate()
        print(f"Server integration test failure stdout:\n{stdout}")
        print(f"Server integration test failure stderr:\n{stderr}")
        raise e


# --- Additional Unit Tests for Web Server and State Tracking ---

def test_recent_actions_truncation():
    """Verify that recent_actions maintains a maximum of 20 items."""
    loop = mock.MagicMock()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    # Clear and insert 25 actions
    handler.recent_actions = []
    for i in range(25):
        handler.log_action("trigger", f"sender{i}@test.com", "topic", "payload", True)
    assert len(handler.recent_actions) == 20
    # The first element should be the latest (sender24)
    assert handler.recent_actions[0]["sender"] == "sender24@test.com"

def test_save_attachments_empty_safe_filename():
    """Verify that an attachment with a filename that sanitizes to empty is ignored."""
    loop = mock.MagicMock()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    smtp2mqtt.config["SAVE_ATTACHMENTS"] = True
    
    msg = EmailMessage()
    part = mock.MagicMock()
    part.get_content_type.return_value = "image/jpeg"
    part.get_filename.return_value = "/" # Base name becomes empty string
    
    with mock.patch.object(msg, "iter_attachments", return_value=[part]):
        handler.save_attachments(msg, "topic", is_triggered=False)
    # Should not raise any error and should skip safely

def test_get_status_json():
    """Verify that get_status_json generates correct structure."""
    loop = mock.MagicMock()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    status = handler.get_status_json()
    assert status["status"] == "online"
    assert "uptime_seconds" in status
    assert "recent_actions" in status

def test_get_dashboard_html():
    """Verify that get_dashboard_html returns the template."""
    loop = mock.MagicMock()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    html = handler.get_dashboard_html()
    assert "smtp2mqtt Gateway" in html
    assert "LIVE STATS" in html

class DummyReader:
    def __init__(self, lines):
        self.lines = lines
        self.index = 0
    async def readline(self):
        if self.index < len(self.lines):
            val = self.lines[self.index]
            self.index += 1
            return val
        return b""

class DummyWriter:
    def __init__(self):
        self.data = b""
        self.closed = False
    def write(self, data):
        self.data += data
    async def drain(self):
        pass
    def close(self):
        self.closed = True
    async def wait_closed(self):
        pass

@pytest.mark.asyncio
async def test_handle_web_client_api_endpoints():
    """Verify that handle_web_client serves valid status JSON on api paths."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    for path in ["/api", "/api/status", "/status"]:
        reader = DummyReader([f"GET {path} HTTP/1.1\r\n".encode(), b"Host: localhost\r\n", b"\r\n"])
        writer = DummyWriter()
        
        await handler.handle_web_client(reader, writer)
        
        assert b"HTTP/1.1 200 OK" in writer.data
        assert b"Content-Type: application/json" in writer.data
        # Parse output JSON to make sure it is valid
        header_part, body_part = writer.data.split(b"\r\n\r\n", 1)
        data = json.loads(body_part.decode())
        assert data["status"] == "online"
        assert writer.closed

@pytest.mark.asyncio
async def test_handle_web_client_html_dashboard():
    """Verify that handle_web_client serves HTML on root path."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    reader = DummyReader([b"GET / HTTP/1.1\r\n", b"Host: localhost\r\n", b"\r\n"])
    writer = DummyWriter()
    
    await handler.handle_web_client(reader, writer)
    
    assert b"HTTP/1.1 200 OK" in writer.data
    assert b"Content-Type: text/html; charset=utf-8" in writer.data
    assert b"smtp2mqtt Gateway" in writer.data
    assert writer.closed

@pytest.mark.asyncio
async def test_handle_web_client_404():
    """Verify that handle_web_client returns 404 for unknown paths."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    reader = DummyReader([b"GET /notexist HTTP/1.1\r\n", b"\r\n"])
    writer = DummyWriter()
    
    await handler.handle_web_client(reader, writer)
    
    assert b"HTTP/1.1 404 Not Found" in writer.data
    assert b"Not Found" in writer.data
    assert writer.closed

@pytest.mark.asyncio
async def test_handle_web_client_405():
    """Verify that handle_web_client returns 405 for non-GET requests."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    reader = DummyReader([b"POST /api HTTP/1.1\r\n", b"\r\n"])
    writer = DummyWriter()
    
    await handler.handle_web_client(reader, writer)
    
    assert b"HTTP/1.1 405 Method Not Allowed" in writer.data
    assert b"Method Not Allowed" in writer.data
    assert writer.closed

@pytest.mark.asyncio
async def test_handle_web_client_malformed_request_line():
    """Verify that handle_web_client exits gracefully on malformed request lines."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    reader = DummyReader([b"GET\r\n", b"\r\n"])
    writer = DummyWriter()
    
    await handler.handle_web_client(reader, writer)
    assert writer.data == b"" # No response headers written

@pytest.mark.asyncio
async def test_handle_web_client_empty_request():
    """Verify that handle_web_client exits gracefully on empty request."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    reader = DummyReader([b"\r\n"])
    writer = DummyWriter()
    
    await handler.handle_web_client(reader, writer)
    assert writer.data == b""

@pytest.mark.asyncio
async def test_handle_web_client_exception():
    """Verify that handle_web_client handles exceptions cleanly without raising them."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    # Passing None to cause exceptions during readline
    await handler.handle_web_client(None, None)
    # Should not raise any unhandled exceptions


@pytest.mark.asyncio
async def test_mqtt_broker_monitor_and_socket_check(monkeypatch):
    """Verify that monitor_mqtt_broker checks connectivity and transitions correctly."""
    loop = asyncio.get_running_loop()
    
    # We will mock asyncio.sleep to not wait 10 seconds
    sleep_calls = {}
    async def mock_sleep(seconds):
        task = asyncio.current_task()
        if task not in sleep_calls:
            sleep_calls[task] = []
        sleep_calls[task].append(seconds)
        if len(sleep_calls[task]) >= 3:
            raise asyncio.CancelledError()
    
    monkeypatch.setattr(asyncio, "sleep", mock_sleep)
    
    # We will mock _check_socket_connection to return True, then False, then True for MQTT,
    # and always True for SMTP to prevent interference.
    check_results = [True, False, True]
    current_index = 0
    
    def mock_check_socket_connection(self, host, port):
        nonlocal current_index
        if port == 1025:  # SMTP port
            return True
        res = check_results[current_index % len(check_results)]
        current_index += 1
        return res
        
    monkeypatch.setattr(smtp2mqtt.smtp2mqttHandler, "_check_socket_connection", mock_check_socket_connection)
    
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    # Let's wait a bit to let the task execute its iterations.
    try:
        await asyncio.wait_for(handler.monitor_task, timeout=1.0)
    except asyncio.CancelledError:
        pass # Task exited because of CancelledError in mock_sleep
        
    # Assertions
    # Initial check (index 0) returned True.
    # Second check (index 1) returned False -> transition to offline logged.
    # Third check (index 2) returned True -> transition back to online logged.
    assert handler.mqtt_connected_status is True
    assert len(sleep_calls) >= 1
    
    # Cancel all background tasks before undoing monkeypatch to avoid unawaited tasks
    handler.cancel_all_resets()
    
    # Test _check_socket_connection directly
    import socket
    conn_calls = []
    def mock_create_connection(address, timeout):
        conn_calls.append((address, timeout))
        if address[0] == "offline":
            raise OSError("Connection refused")
        return mock.MagicMock()
        
    monkeypatch.undo()
    monkeypatch.setattr(socket, "create_connection", mock_create_connection)
    
    assert handler._check_socket_connection("online", 1883) is True
    assert handler._check_socket_connection("offline", 1883) is False


@pytest.mark.asyncio
async def test_smtp_server_monitor_and_socket_check(monkeypatch):
    """Verify that monitor_smtp_server checks connectivity and transitions correctly."""
    loop = asyncio.get_running_loop()
    
    # We will mock asyncio.sleep to not wait 10 seconds
    sleep_calls = {}
    async def mock_sleep(seconds):
        task = asyncio.current_task()
        if task not in sleep_calls:
            sleep_calls[task] = []
        sleep_calls[task].append(seconds)
        if len(sleep_calls[task]) >= 3:
            raise asyncio.CancelledError()
    
    monkeypatch.setattr(asyncio, "sleep", mock_sleep)
    
    # We will mock _check_socket_connection to return True, then False, then True for SMTP,
    # and always True for MQTT to prevent interference.
    check_results = [True, False, True]
    current_index = 0
    
    def mock_check_socket_connection(self, host, port):
        nonlocal current_index
        if port == 1883:  # MQTT port
            return True
        res = check_results[current_index % len(check_results)]
        current_index += 1
        return res
        
    monkeypatch.setattr(smtp2mqtt.smtp2mqttHandler, "_check_socket_connection", mock_check_socket_connection)
    
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    # Let's wait a bit to let the task execute its iterations.
    try:
        await asyncio.wait_for(handler.monitor_smtp_task, timeout=1.0)
    except asyncio.CancelledError:
        pass # Task exited because of CancelledError in mock_sleep
        
    # Assertions
    assert handler.smtp_connected_status is True
    assert len(sleep_calls) >= 1
    handler.cancel_all_resets()


@pytest.mark.asyncio
async def test_get_status_json_formats(monkeypatch):
    """Verify correct formatting of uptime_formatted and connection helper texts."""
    from datetime import datetime, timedelta
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    # Test 1: Uptime < 60s
    handler.start_time = datetime.now() - timedelta(seconds=45)
    handler.mqtt_connected_status = True
    handler.smtp_connected_status_val = True
    status = handler.get_status_json()
    assert status["uptime_formatted"] == "45s"
    assert status["mqtt_status_text"] == "Connected"
    assert status["smtp_status_text"] == "Active"

    # Test 2: Uptime < 3600s
    handler.start_time = datetime.now() - timedelta(minutes=15, seconds=30)
    handler.mqtt_connected_status = False
    handler.smtp_connected_status_val = False
    status = handler.get_status_json()
    assert status["uptime_formatted"] == "15m 30s"
    assert status["mqtt_status_text"] == "Disconnected"
    assert status["smtp_status_text"] == "Inactive"

    # Test 3: Uptime >= 3600s
    handler.start_time = datetime.now() - timedelta(hours=3, minutes=10, seconds=45)
    status = handler.get_status_json()
    assert status["uptime_formatted"] == "3h 10m"
    
    handler.cancel_all_resets()


@pytest.mark.asyncio
async def test_smtp_controller_status_checks(monkeypatch):
    """Verify that monitor_smtp_server uses UnthreadedController to check state without falling back."""
    loop = asyncio.get_running_loop()
    
    # Mock UnthreadedController
    class MockServer:
        def is_serving(self):
            return True
            
    class MockController:
        def __init__(self, handler, hostname, port):
            self.server = MockServer()
            
    monkeypatch.setattr(smtp2mqtt, "UnthreadedController", MockController)
    
    # Mock sleep to run twice, allowing one iteration after setting smtp_controller, then cancel
    sleep_calls = []
    async def mock_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError()
        
    monkeypatch.setattr(asyncio, "sleep", mock_sleep)
    
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    # Set active smtp_controller on the handler
    handler.smtp_controller = MockController(None, "127.0.0.1", 1025)
    
    try:
        await asyncio.wait_for(handler.monitor_smtp_task, timeout=1.0)
    except asyncio.CancelledError:
        pass
        
    assert handler.smtp_connected_status is True
    handler.cancel_all_resets()


@pytest.mark.asyncio
async def test_web_server_security_limits():
    """Verify that handle_web_client restricts header reading to 100 headers to prevent DoS."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    # Create mock reader and writer
    class MockReader:
        def __init__(self):
            self.readline_count = 0
            
        async def readline(self):
            self.readline_count += 1
            if self.readline_count == 1:
                return b"GET /api HTTP/1.1\r\n"
            else:
                return b"X-Flood-Header: flood\r\n"
                
    class MockWriter:
        def __init__(self):
            self.write_data = b""
            self.is_closed = False
            
        def write(self, data):
            self.write_data += data
            
        async def drain(self):
            pass
            
        def close(self):
            self.is_closed = True
            
        async def wait_closed(self):
            pass
            
    reader = MockReader()
    writer = MockWriter()
    
    await handler.handle_web_client(reader, writer)
    
    assert reader.readline_count <= 102
    assert b"200 OK" in writer.write_data
    assert writer.is_closed is True
    handler.cancel_all_resets()


@pytest.mark.asyncio
async def test_monitor_exceptions_handling(monkeypatch):
    """Verify that the monitors handle unexpected exceptions gracefully."""
    loop = asyncio.get_running_loop()
    
    def mock_check_socket_connection_raise(self, host, port):
        raise RuntimeError("Unexpected failure")
        
    monkeypatch.setattr(smtp2mqtt.smtp2mqttHandler, "_check_socket_connection", mock_check_socket_connection_raise)
    
    sleep_calls = []
    async def mock_sleep(seconds):
        sleep_calls.append(seconds)
        raise asyncio.CancelledError()
        
    monkeypatch.setattr(asyncio, "sleep", mock_sleep)
    
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    try:
         await asyncio.wait_for(handler.monitor_task, timeout=1.0)
    except asyncio.CancelledError:
         pass
         
    try:
         await asyncio.wait_for(handler.monitor_smtp_task, timeout=1.0)
    except asyncio.CancelledError:
         pass
         
    assert handler.mqtt_connected_status is None
    assert handler.smtp_connected_status is False
    handler.cancel_all_resets()


@pytest.mark.asyncio
async def test_save_attachments_returns_info():
    """Verify that save_attachments returns correct filename and absolute path info."""
    if os.path.exists("attachments"):
        shutil.rmtree("attachments")

    smtp2mqtt.config["SAVE_ATTACHMENTS"] = True
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)

    msg = EmailMessage()
    msg["Subject"] = "Test trigger"
    msg["From"] = "camera@house.com"
    msg.set_content("Motion detected!")
    
    fake_image = b"XYZ-FAKE-IMAGE-DATA-XYZ"
    msg.add_attachment(fake_image, maintype="image", subtype="jpeg", filename="test_returned_info.jpg")

    saved_info = handler.save_attachments(msg, "smtp2mqtt/camera", is_triggered=False)

    assert len(saved_info) == 1
    assert saved_info[0]["filename"] == "test_returned_info.jpg"
    assert saved_info[0]["path"] == os.path.abspath(os.path.join("attachments", "test_returned_info.jpg"))

    # Cleanup
    if os.path.exists("attachments"):
        shutil.rmtree("attachments")


@pytest.mark.asyncio
async def test_handle_web_client_serves_attachments():
    """Verify that a valid attachment is served correctly with correct headers and MIME types."""
    os.makedirs("attachments", exist_ok=True)
    file_path = os.path.join("attachments", "test_doc.pdf")
    fake_content = b"PDF-DUMMY-CONTENT"
    with open(file_path, "wb") as f:
        f.write(fake_content)

    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)

    class MockReader:
        async def readline(self):
            if not hasattr(self, "called"):
                self.called = True
                return b"GET /attachments/test_doc.pdf HTTP/1.1\r\n"
            return b"\r\n"

    class MockWriter:
        def __init__(self):
            self.write_data = b""
            self.is_closed = False

        def write(self, data):
            self.write_data += data

        async def drain(self):
            pass

        def close(self):
            self.is_closed = True

        async def wait_closed(self):
            pass

    reader = MockReader()
    writer = MockWriter()

    try:
        await handler.handle_web_client(reader, writer)
    finally:
        # Cleanup
        if os.path.exists("attachments"):
            shutil.rmtree("attachments")
        handler.cancel_all_resets()

    assert b"200 OK" in writer.write_data
    assert b"Content-Type: application/pdf" in writer.write_data
    assert b"Content-Disposition: inline; filename=\"test_doc.pdf\"" in writer.write_data
    assert fake_content in writer.write_data
    assert writer.is_closed is True


@pytest.mark.asyncio
async def test_handle_web_client_prevents_path_traversal():
    """Verify that path traversal attempts are sanitized/neutralized and fail safe."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)

    class MockReader:
        async def readline(self):
            if not hasattr(self, "called"):
                self.called = True
                return b"GET /attachments/../../etc/passwd HTTP/1.1\r\n"
            return b"\r\n"

    class MockWriter:
        def __init__(self):
            self.write_data = b""
            self.is_closed = False

        def write(self, data):
            self.write_data += data

        async def drain(self):
            pass

        def close(self):
            self.is_closed = True

        async def wait_closed(self):
            pass

    reader = MockReader()
    writer = MockWriter()

    try:
        await handler.handle_web_client(reader, writer)
    finally:
        handler.cancel_all_resets()

    assert b"404 Not Found" in writer.write_data
    assert b"Attachment Not Found" in writer.write_data
    assert writer.is_closed is True


@pytest.mark.asyncio
async def test_handle_web_client_attachment_not_found():
    """Verify that requesting a non-existent attachment returns a 404 response."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)

    class MockReader:
        async def readline(self):
            if not hasattr(self, "called"):
                self.called = True
                return b"GET /attachments/missing_file.png HTTP/1.1\r\n"
            return b"\r\n"

    class MockWriter:
        def __init__(self):
            self.write_data = b""
            self.is_closed = False

        def write(self, data):
            self.write_data += data

        async def drain(self):
            pass

        def close(self):
            self.is_closed = True

        async def wait_closed(self):
            pass

    reader = MockReader()
    writer = MockWriter()

    try:
        await handler.handle_web_client(reader, writer)
    finally:
        handler.cancel_all_resets()

    assert b"404 Not Found" in writer.write_data
    assert b"Attachment Not Found" in writer.write_data
    assert writer.is_closed is True


@pytest.mark.asyncio
async def test_handle_web_client_serves_logo(monkeypatch):
    """Verify that handle_web_client serves logo.svg with correct MIME type and handles missing file."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)

    class MockReader:
        def __init__(self, path):
            self.path = path
        async def readline(self):
            if not hasattr(self, "called"):
                self.called = True
                return f"GET {self.path} HTTP/1.1\r\n".encode()
            return b"\r\n"

    class MockWriter:
        def __init__(self):
            self.write_data = b""
            self.is_closed = False

        def write(self, data):
            self.write_data += data

        async def drain(self):
            pass

        def close(self):
            self.is_closed = True

        async def wait_closed(self):
            pass

    # Test 1: Files exist
    # Temporarily mock os.path.exists and os.path.isfile to return True for logo.svg and favicon.svg
    orig_exists = os.path.exists
    orig_isfile = os.path.isfile
    
    def mock_exists(path):
        if "logo.svg" in path or "favicon.svg" in path:
            return True
        return orig_exists(path)
        
    def mock_isfile(path):
        if "logo.svg" in path or "favicon.svg" in path:
            return True
        return orig_isfile(path)

    monkeypatch.setattr(os.path, "exists", mock_exists)
    monkeypatch.setattr(os.path, "isfile", mock_isfile)

    # Mock _read_file_binary to return mock SVG content
    dummy_svg = b"<svg>Mock Logo</svg>"
    dummy_fav = b"<svg>Mock Favicon</svg>"
    def mock_read_file_binary(self_obj, path):
        if "logo.svg" in path:
            return dummy_svg
        if "favicon.svg" in path:
            return dummy_fav
        raise FileNotFoundError()

    monkeypatch.setattr(smtp2mqtt.smtp2mqttHandler, "_read_file_binary", mock_read_file_binary)

    # Verify serving logo.svg
    reader = MockReader("/logo.svg")
    writer = MockWriter()
    await handler.handle_web_client(reader, writer)
    assert b"200 OK" in writer.write_data
    assert b"Content-Type: image/svg+xml" in writer.write_data
    assert dummy_svg in writer.write_data

    # Verify serving favicon.svg on /favicon.svg route
    reader = MockReader("/favicon.svg")
    writer = MockWriter()
    await handler.handle_web_client(reader, writer)
    assert b"200 OK" in writer.write_data
    assert b"Content-Type: image/svg+xml" in writer.write_data
    assert dummy_fav in writer.write_data

    # Verify serving favicon.svg on /favicon.ico route
    reader = MockReader("/favicon.ico")
    writer = MockWriter()
    await handler.handle_web_client(reader, writer)
    assert b"200 OK" in writer.write_data
    assert b"Content-Type: image/svg+xml" in writer.write_data
    assert dummy_fav in writer.write_data

    # Test 2: File does not exist
    def mock_exists_false(path):
        if "logo.svg" in path or "favicon.svg" in path:
            return False
        return orig_exists(path)
    monkeypatch.setattr(os.path, "exists", mock_exists_false)

    reader = MockReader("/logo.svg")
    writer = MockWriter()
    await handler.handle_web_client(reader, writer)
    assert b"404 Not Found" in writer.write_data
    assert b"File Not Found" in writer.write_data

    handler.cancel_all_resets()


@pytest.mark.asyncio
async def test_monitor_mqtt_broker_logs_state_changes_to_actions(monkeypatch):
    """Verify that MQTT broker monitor logs state changes (system actions) correctly on transition."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    # Cancel background resets and reset status/actions to prevent race conditions/test pollution
    handler.cancel_all_resets()
    handler.mqtt_connected_status = None
    handler.recent_actions.clear()

    connection_states = [True, False, True]
    state_index = 0

    def mock_check_socket_connection(host, port):
        nonlocal state_index
        val = connection_states[state_index]
        if state_index < len(connection_states) - 1:
            state_index += 1
        return val

    monkeypatch.setattr(handler, "_check_socket_connection", mock_check_socket_connection)

    sleep_count = 0
    async def mock_sleep(seconds):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 3:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", mock_sleep)

    try:
        await handler.monitor_mqtt_broker()
    except asyncio.CancelledError:
        pass
    finally:
        handler.cancel_all_resets()

    system_actions = [a for a in handler.recent_actions if a["type"] == "system"]
    assert len(system_actions) == 2
    assert "Online (Reconnected)" in system_actions[0]["payload"]
    assert system_actions[0]["status"] == "SUCCESS"
    assert "Offline (Unreachable)" in system_actions[1]["payload"]
    assert system_actions[1]["status"] == "FAILED"


@pytest.mark.asyncio
async def test_handle_data_associates_attachments_to_recent_actions(monkeypatch):
    """Verify that handle_DATA associates saved attachments to the corresponding trigger action."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    # Pre-populate self.recent_actions with the expected trigger action
    handler.recent_actions = [
        {
            "type": "trigger",
            "sender": "sender@domain.com",
            "topic": "smtp2mqtt/sender-domain.com",
            "time": "12:00",
            "payload": "ON"
        }
    ]
    
    envelope = mock.MagicMock()
    envelope.mail_from = "sender@domain.com"
    envelope.original_content = b"From: sender@domain.com\nTo: rcpt@domain.com\nSubject: Test\n\nBody"
    envelope.content = b"From: sender@domain.com\nTo: rcpt@domain.com\nSubject: Test\n\nBody"
    
    mock_attachments = [{"filename": "test.jpg", "path": "attachments/test.jpg", "size": 123}]
    
    async def mock_to_thread(func, *args, **kwargs):
        if func == handler.save_attachments:
            return mock_attachments
        return None
        
    monkeypatch.setattr(asyncio, "to_thread", mock_to_thread)
    
    res = await handler.handle_DATA(None, None, envelope)
    assert res == "250 Message accepted for delivery"
    
    # Assert attachments were associated to the trigger action
    assert handler.recent_actions[0]["attachments"] == mock_attachments
    handler.cancel_all_resets()


@pytest.mark.asyncio
async def test_handle_web_client_read_file_binary_exception(monkeypatch):
    """Verify that handle_web_client returns 500 when _read_file_binary raises an exception for logo/favicon."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)

    class MockReader:
        async def readline(self):
            return b"GET /logo.svg HTTP/1.1\r\n"

    class MockWriter:
        def __init__(self):
            self.write_data = b""
            self.is_closed = False
        def write(self, data):
            self.write_data += data
        async def drain(self):
            pass
        def close(self):
            self.is_closed = True
        async def wait_closed(self):
            pass

    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os.path, "isfile", lambda p: True)

    def mock_read_file_binary_error(self_obj, path):
        raise IOError("Mock read failure")

    monkeypatch.setattr(smtp2mqtt.smtp2mqttHandler, "_read_file_binary", mock_read_file_binary_error)

    reader = MockReader()
    writer = MockWriter()
    await handler.handle_web_client(reader, writer)
    assert b"500 Internal Server Error" in writer.write_data
    assert b"Internal Server Error" in writer.write_data
    handler.cancel_all_resets()


@pytest.mark.asyncio
async def test_handle_web_client_attachment_read_exception(monkeypatch):
    """Verify that handle_web_client returns 500 when _read_file_binary raises an exception for an attachment."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)

    class MockReader:
        async def readline(self):
            return b"GET /attachments/test.jpg HTTP/1.1\r\n"

    class MockWriter:
        def __init__(self):
            self.write_data = b""
            self.is_closed = False
        def write(self, data):
            self.write_data += data
        async def drain(self):
            pass
        def close(self):
            self.is_closed = True
        async def wait_closed(self):
            pass

    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os.path, "isfile", lambda p: True)

    def mock_read_file_binary_error(self_obj, path):
        raise IOError("Mock attachment read failure")

    monkeypatch.setattr(smtp2mqtt.smtp2mqttHandler, "_read_file_binary", mock_read_file_binary_error)

    reader = MockReader()
    writer = MockWriter()
    await handler.handle_web_client(reader, writer)
    assert b"500 Internal Server Error" in writer.write_data
    assert b"Internal Server Error" in writer.write_data
    handler.cancel_all_resets()


@pytest.mark.asyncio
async def test_monitor_mqtt_broker_initial_offline(monkeypatch):
    """Verify MQTT monitor logs offline state initially when broker check fails."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    # Cancel background resets and reset status/actions to prevent race conditions/test pollution
    handler.cancel_all_resets()
    handler.mqtt_connected_status = None
    handler.recent_actions.clear()
    
    assert handler.mqtt_connected_status is None
    
    monkeypatch.setattr(handler, "_check_socket_connection", lambda h, p: False)
    
    async def mock_sleep(seconds):
        raise asyncio.CancelledError()
    monkeypatch.setattr(asyncio, "sleep", mock_sleep)
    
    try:
        await handler.monitor_mqtt_broker()
    except asyncio.CancelledError:
        pass
    
    assert handler.mqtt_connected_status is False
    system_actions = [a for a in handler.recent_actions if a["type"] == "system"]
    assert len(system_actions) == 1
    assert "Offline (Unreachable)" in system_actions[0]["payload"]
    handler.cancel_all_resets()


@pytest.mark.asyncio
async def test_monitor_smtp_server_exception(monkeypatch):
    """Verify SMTP server monitor handles internal check exception gracefully."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    # Cancel background resets and reset status/actions to prevent race conditions/test pollution
    handler.cancel_all_resets()
    handler.smtp_connected_status_val = None
    handler.recent_actions.clear()
    
    mock_server = mock.MagicMock()
    mock_server.is_serving.side_effect = Exception("Mock server exception")
    
    mock_controller = mock.MagicMock()
    mock_controller.server = mock_server
    handler.smtp_controller = mock_controller
    
    monkeypatch.setattr(handler, "_check_socket_connection", lambda h, p: False)
    
    async def mock_sleep(seconds):
        raise asyncio.CancelledError()
    monkeypatch.setattr(asyncio, "sleep", mock_sleep)
    
    try:
        await handler.monitor_smtp_server()
    except asyncio.CancelledError:
        pass
        
    assert handler.smtp_connected_status_val is False
    handler.cancel_all_resets()


@pytest.mark.asyncio
async def test_monitor_smtp_server_initial_inactive(monkeypatch):
    """Verify SMTP server monitor logs inactive initially when port check fails."""
    loop = asyncio.get_running_loop()
    handler = smtp2mqtt.smtp2mqttHandler(loop)
    
    # Cancel background resets and reset status/actions to prevent race conditions/test pollution
    handler.cancel_all_resets()
    handler.smtp_connected_status_val = None
    handler.recent_actions.clear()
    
    assert handler.smtp_connected_status_val is None
    
    handler.smtp_controller = None
    monkeypatch.setattr(handler, "_check_socket_connection", lambda h, p: False)
    
    async def mock_sleep(seconds):
        raise asyncio.CancelledError()
    monkeypatch.setattr(asyncio, "sleep", mock_sleep)
    
    try:
        await handler.monitor_smtp_server()
    except asyncio.CancelledError:
        pass
        
    assert handler.smtp_connected_status_val is False
    handler.cancel_all_resets()


def setup_custom_new_event_loop(monkeypatch, run_forever_cb=None, add_signal_handler_cb=None):
    """Sets up a robust mock of asyncio.new_event_loop that returns a real loop
    but intercepts run_forever and run_until_complete to allow testing the entrypoints
    without hanging.
    """
    orig_new_loop = asyncio.new_event_loop
    def custom_new_event_loop():
        loop = orig_new_loop()
        
        # Override add_signal_handler if a callback is provided
        if add_signal_handler_cb:
            loop.add_signal_handler = add_signal_handler_cb
        else:
            loop.add_signal_handler = lambda *args, **kwargs: None
            
        orig_run_until_complete = loop.run_until_complete
        loop._in_run_until_complete = False
        
        def custom_run_until_complete(future):
            loop._in_run_until_complete = True
            try:
                return orig_run_until_complete(future)
            finally:
                loop._in_run_until_complete = False
        loop.run_until_complete = custom_run_until_complete
        
        orig_run_forever = loop.run_forever
        def mock_run_forever():
            if loop._in_run_until_complete:
                orig_run_forever()
            else:
                if run_forever_cb:
                    run_forever_cb()
        loop.run_forever = mock_run_forever
        
        return loop
    monkeypatch.setattr(asyncio, "new_event_loop", custom_new_event_loop)


def test_main_web_server_start_exception(monkeypatch):
    """Verify web server startup fallback when start_server raises an exception."""
    orig_enable_web = smtp2mqtt.config["ENABLE_WEB"]
    smtp2mqtt.config["ENABLE_WEB"] = True
    
    mock_controller_class = mock.MagicMock()
    monkeypatch.setattr(smtp2mqtt, "UnthreadedController", mock_controller_class)
    
    async def mock_start_server(*args, **kwargs):
        raise Exception("Port already in use")
    monkeypatch.setattr(asyncio, "start_server", mock_start_server)
    
    setup_custom_new_event_loop(monkeypatch)
    
    try:
        smtp2mqtt.main()
    finally:
        smtp2mqtt.config["ENABLE_WEB"] = orig_enable_web


def test_main_shutdown_signal_callback(monkeypatch):
    """Verify registration and callback triggering of OS termination signals."""
    orig_enable_web = smtp2mqtt.config["ENABLE_WEB"]
    smtp2mqtt.config["ENABLE_WEB"] = False
    
    mock_controller_class = mock.MagicMock()
    monkeypatch.setattr(smtp2mqtt, "UnthreadedController", mock_controller_class)
    
    captured_callbacks = []
    def mock_add_signal_handler(sig, callback, *args):
        captured_callbacks.append(callback)
    
    def mock_run_forever():
        for cb in captured_callbacks:
            cb()
            
    setup_custom_new_event_loop(
        monkeypatch,
        run_forever_cb=mock_run_forever,
        add_signal_handler_cb=mock_add_signal_handler,
    )
    
    try:
        smtp2mqtt.main()
    finally:
        smtp2mqtt.config["ENABLE_WEB"] = orig_enable_web
        
    assert len(captured_callbacks) > 0


def test_main_signal_registration_exception(monkeypatch):
    """Verify registration exception handling for OS signal handlers."""
    orig_enable_web = smtp2mqtt.config["ENABLE_WEB"]
    smtp2mqtt.config["ENABLE_WEB"] = False
    
    mock_controller_class = mock.MagicMock()
    monkeypatch.setattr(smtp2mqtt, "UnthreadedController", mock_controller_class)
    
    def mock_add_signal_handler_raise(sig, callback, *args):
        raise ValueError("Mock signal registration failure")
        
    setup_custom_new_event_loop(
        monkeypatch,
        add_signal_handler_cb=mock_add_signal_handler_raise,
    )
    
    try:
        smtp2mqtt.main()
    finally:
        smtp2mqtt.config["ENABLE_WEB"] = orig_enable_web


def test_main_event_loop_unhandled_exception(monkeypatch):
    """Verify main event loop handles standard exceptions during execution."""
    orig_enable_web = smtp2mqtt.config["ENABLE_WEB"]
    smtp2mqtt.config["ENABLE_WEB"] = False
    
    mock_controller_class = mock.MagicMock()
    monkeypatch.setattr(smtp2mqtt, "UnthreadedController", mock_controller_class)
    
    def mock_run_forever_raise():
        raise RuntimeError("Mock unhandled loop crash")
        
    setup_custom_new_event_loop(
        monkeypatch,
        run_forever_cb=mock_run_forever_raise,
    )
    
    try:
        smtp2mqtt.main()
    finally:
        smtp2mqtt.config["ENABLE_WEB"] = orig_enable_web


def test_main_controller_end_exception(monkeypatch):
    """Verify cleanup logs and handles exception during SMTP controller termination."""
    orig_enable_web = smtp2mqtt.config["ENABLE_WEB"]
    smtp2mqtt.config["ENABLE_WEB"] = False
    
    mock_controller = mock.MagicMock()
    mock_controller.end.side_effect = Exception("Failed to end controller")
    
    monkeypatch.setattr(smtp2mqtt, "UnthreadedController", lambda *args, **kwargs: mock_controller)
    
    setup_custom_new_event_loop(monkeypatch)
    
    try:
        smtp2mqtt.main()
    finally:
        smtp2mqtt.config["ENABLE_WEB"] = orig_enable_web


def test_main_web_server_close_exception(monkeypatch):
    """Verify cleanup handles exception during web server close wait gracefully."""
    orig_enable_web = smtp2mqtt.config["ENABLE_WEB"]
    smtp2mqtt.config["ENABLE_WEB"] = True
    
    mock_controller_class = mock.MagicMock()
    monkeypatch.setattr(smtp2mqtt, "UnthreadedController", mock_controller_class)
    
    mock_web_server = mock.MagicMock()
    async def mock_wait_closed():
        raise Exception("Mock wait_closed failure")
    mock_web_server.wait_closed = mock_wait_closed
    
    async def mock_start_server(*args, **kwargs):
        return mock_web_server
    monkeypatch.setattr(asyncio, "start_server", mock_start_server)
    
    setup_custom_new_event_loop(monkeypatch)
    
    try:
        smtp2mqtt.main()
    finally:
        smtp2mqtt.config["ENABLE_WEB"] = orig_enable_web



def test_main_entrypoint_keyboard_interrupt(monkeypatch):
    """Verify that KeyboardInterrupt on __main__ block exits cleanly."""
    import runpy
    def mock_new_event_loop():
        raise KeyboardInterrupt()
    monkeypatch.setattr(asyncio, "new_event_loop", mock_new_event_loop)
    
    # runpy executes module code under main name
    runpy.run_path("smtp2mqtt.py", run_name="__main__")


def test_main_entrypoint_unhandled_exception(monkeypatch):
    """Verify that standard Exception on __main__ block prints logs and exits with code 1."""
    import runpy
    def mock_new_event_loop():
        raise RuntimeError("Crashed entrypoint")
    monkeypatch.setattr(asyncio, "new_event_loop", mock_new_event_loop)
    
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path("smtp2mqtt.py", run_name="__main__")
    assert excinfo.value.code == 1
