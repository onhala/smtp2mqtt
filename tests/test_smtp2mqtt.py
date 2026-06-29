import os
import sys
import time
import shutil
import socket
import smtplib
import subprocess
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
async def test_smtp2mqtt_handler_mqtt_publish():
    """Verify that handler correctly publishes to MQTT broker via thread."""
    # Construct handler
    loop = mock.MagicMock()
    handler = smtp2mqtt.smtp2mqttHandler(loop)

    # Mock smtp2mqtt.publish.single
    with mock.patch("smtp2mqtt.publish.single") as mock_publish_single:
        handler.mqtt_publish("test-topic", "ON")
        mock_publish_single.assert_called_once_with(
            "test-topic",
            "ON",
            hostname=smtp2mqtt.config["MQTT_HOST"],
            port=smtp2mqtt.config["MQTT_PORT"],
            auth=None
        )

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
    
    # We use sys.executable to ensure we run with the same python interpreter
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
            # Send greeting
            code, msg = smtp.ehlo()
            assert code == 250
            
            # Send mail
            smtp.sendmail(
                "camera@house.com",
                ["me@house.com"],
                "Subject: Alert!\n\nMotion in Zone 2"
            )
            
        # Wait a moment for processing
        time.sleep(1.0)
        
        # Stop the process gracefully via SIGTERM
        process.terminate()
        
        # Capture remaining logs
        stdout, stderr = process.communicate(timeout=5)
        
        # Assertions
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
