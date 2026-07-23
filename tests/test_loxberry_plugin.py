import configparser
import os
import re
import subprocess
import zipfile
import pytest
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import smtp2mqtt


def test_plugin_cfg_structure_and_validity():
    """Verify that plugin.cfg follows mandatory LoxBerry standards."""
    cfg_path = os.path.join(PROJECT_ROOT, "plugin.cfg")
    assert os.path.exists(cfg_path), "plugin.cfg must exist in repository root"

    # Check Unix LF line endings
    with open(cfg_path, "rb") as f:
        content_bytes = f.read()
        assert b"\r\n" not in content_bytes, "plugin.cfg must use Unix LF line endings (no CRLF)"

    config = configparser.ConfigParser()
    config.read(cfg_path, encoding="utf-8")

    # Mandatory Sections
    for section in ["AUTHOR", "PLUGIN", "SYSTEM", "AUTOUPDATE"]:
        assert config.has_section(section), f"plugin.cfg is missing mandatory section [{section}]"

    # Required fields in [AUTHOR]
    assert config.get("AUTHOR", "NAME", fallback="").strip() != ""
    assert "@" in config.get("AUTHOR", "EMAIL", fallback="")

    # Required fields in [PLUGIN]
    name = config.get("PLUGIN", "NAME", fallback="")
    folder = config.get("PLUGIN", "FOLDER", fallback="")
    version = config.get("PLUGIN", "VERSION", fallback="")
    title = config.get("PLUGIN", "TITLE", fallback="")

    assert name == "smtp2mqtt", "PLUGIN NAME must match repository name"
    assert folder == "smtp2mqtt", "PLUGIN FOLDER must match plugin name"
    assert len(title) <= 25, "PLUGIN TITLE should not exceed 25 characters"
    assert re.match(r"^\d+\.\d+\.\d+$", version), "VERSION must follow Semantic Versioning (X.Y.Z)"

    # Required fields in [SYSTEM]
    assert config.get("SYSTEM", "INTERFACE", fallback="") == "2.0"
    assert config.get("SYSTEM", "LB_MIN", fallback="") != ""

    # Required fields in [AUTOUPDATE]
    assert config.getboolean("AUTOUPDATE", "AUTOMATIC_UPDATES") is True
    assert config.get("AUTOUPDATE", "RELEASECFG", fallback="").startswith("https://")
    assert config.get("AUTOUPDATE", "PRERELEASECFG", fallback="").startswith("https://")


def test_release_cfg_structure_and_validity():
    """Verify that release.cfg follows LoxBerry Auto-Update standards."""
    cfg_path = os.path.join(PROJECT_ROOT, "release.cfg")
    assert os.path.exists(cfg_path), "release.cfg must exist in repository root"

    with open(cfg_path, "rb") as f:
        content_bytes = f.read()
        assert b"\r\n" not in content_bytes, "release.cfg must use Unix LF line endings (no CRLF)"

    config = configparser.ConfigParser()
    config.read(cfg_path, encoding="utf-8")

    assert config.has_section("AUTOUPDATE")
    version = config.get("AUTOUPDATE", "VERSION", fallback="")
    archive_url = config.get("AUTOUPDATE", "ARCHIVEURL", fallback="")
    info_url = config.get("AUTOUPDATE", "INFOURL", fallback="")

    assert re.match(r"^\d+\.\d+\.\d+$", version), "release.cfg VERSION must be valid semver"
    assert archive_url.startswith("https://github.com/onhala/smtp2mqtt/releases/download/")
    assert info_url.startswith("https://github.com/onhala/smtp2mqtt/releases/tag/")


def test_shell_scripts_syntax_shebang_and_line_endings():
    """Verify shell scripts have valid bash shebangs, LF line endings, and syntax."""
    scripts = [
        "postinstall.sh",
        "preupgrade.sh",
        "postupgrade.sh",
        "preremove.sh",
        "loxberry-build.sh",
    ]

    for script_name in scripts:
        script_path = os.path.join(PROJECT_ROOT, script_name)
        assert os.path.exists(script_path), f"Script {script_name} must exist"

        with open(script_path, "rb") as f:
            content_bytes = f.read()
            assert b"\r\n" not in content_bytes, f"Script {script_name} must use Unix LF line endings"
            lines = content_bytes.splitlines()
            assert lines[0].startswith(b"#!") and b"bash" in lines[0], f"Script {script_name} must start with #!/bin/bash"


def test_loxberry_paths_and_mqtt_auto_detection(tmp_path, monkeypatch):
    """Test get_loxberry_paths and load_loxberry_mqtt_config helper functions."""
    lb_root = tmp_path / "opt" / "loxberry"
    lb_sys = lb_root / "config" / "system"
    lb_sys.mkdir(parents=True)

    mqtt_json = lb_sys / "mqttgateway.json"
    mqtt_json.write_text("""{
        "Main": {
            "brokeraddress": "192.168.1.50",
            "brokerport": 1883,
            "brokeruser": "loxberry_mqtt",
            "brokerpass": "secret123"
        }
    }""")

    monkeypatch.setenv("LBHOME", str(lb_root))

    paths = smtp2mqtt.get_loxberry_paths()
    assert paths["LBHOME"] == str(lb_root)
    assert paths["LBPDATA"].endswith("data/plugins/smtp2mqtt")
    assert paths["LBPLOG"].endswith("log/plugins/smtp2mqtt")

    mqtt_cfg = smtp2mqtt.load_loxberry_mqtt_config(paths)
    assert mqtt_cfg["MQTT_HOST"] == "192.168.1.50"
    assert mqtt_cfg["MQTT_PORT"] == 1883
    assert mqtt_cfg["MQTT_USERNAME"] == "loxberry_mqtt"
    assert mqtt_cfg["MQTT_PASSWORD"] == "secret123"


def test_loxberry_zip_packaging_integrity(tmp_path):
    """Verify that loxberry-build.sh creates a valid ZIP archive containing mandatory files."""
    # Clean up any pre-existing zip files in project root
    for f in os.listdir(PROJECT_ROOT):
        if f.startswith("smtp2mqtt-loxberry-v") and f.endswith(".zip"):
            try:
                os.remove(os.path.join(PROJECT_ROOT, f))
            except Exception:
                pass

    build_script = os.path.join(PROJECT_ROOT, "loxberry-build.sh")
    res = subprocess.run(["bash", build_script], cwd=PROJECT_ROOT, capture_output=True, text=True)
    assert res.returncode == 0, f"loxberry-build.sh failed: {res.stderr}"

    # Locate generated zip
    zip_files = [f for f in os.listdir(PROJECT_ROOT) if f.startswith("smtp2mqtt-loxberry-v") and f.endswith(".zip")]
    assert len(zip_files) > 0, "No loxberry zip file generated"

    zip_path = os.path.join(PROJECT_ROOT, zip_files[0])
    with zipfile.ZipFile(zip_path, "r") as zf:
        file_list = zf.namelist()
        mandatory_files = [
            "plugin.cfg",
            "release.cfg",
            "postinstall.sh",
            "preupgrade.sh",
            "postupgrade.sh",
            "preremove.sh",
            "smtp2mqtt.py",
            "requirements.txt",
            "icons/icon_64.png",
            "icons/icon_128.png",
            "icons/icon_256.png",
            "icons/icon_512.png",
            "webfrontend/html/index.php",
        ]
        for mandatory in mandatory_files:
            assert mandatory in file_list, f"ZIP package is missing required file: {mandatory}"

