import os
import sys
import time
import shutil
import smtplib
import subprocess
import asyncio
import importlib
import logging
import unittest.mock as mock
from email.message import EmailMessage
import pytest

# Add the project root to sys.path so we can import smtp2mqtt
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import smtp2mqtt

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
        mock_pub.assert_called_once_with(expected_topic, "ON")
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
        mock_pub.assert_called_once_with("smtp2mqtt/sender-domain.com", "ON")
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
        mock_pub.assert_called_once_with(topic, smtp2mqtt.config["MQTT_RESET_PAYLOAD"])

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
    
    # We mock asyncio.new_event_loop to return our mock loop
    with mock.patch("asyncio.new_event_loop", return_value=mock_loop), \
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
