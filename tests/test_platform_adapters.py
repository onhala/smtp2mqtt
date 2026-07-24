import os
import json
import shutil
import unittest.mock as mock
import pytest
from smtp2mqtt.platform.docker.adapter import DockerPlatformAdapter
from smtp2mqtt.platform.loxberry.adapter import LoxBerryPlatformAdapter
from smtp2mqtt.__main__ import get_platform_adapter, main

def test_docker_platform_adapter_defaults():
    adapter = DockerPlatformAdapter()
    adapter.initialize()
    assert adapter.get_data_dir() == "."
    
    # get_log_dir returns 'log' if directory exists, else ''
    if not os.path.exists("log"):
        assert adapter.get_log_dir() == ""
    else:
        assert adapter.get_log_dir() == "log"

def test_docker_platform_adapter_config_loading(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    adapter = DockerPlatformAdapter()
    assert adapter.load_config() == {}
    
    config_file = tmp_path / "config.json"
    config_file.write_text('{"MQTT_HOST": "192.168.1.10", "MQTT_PORT": 1883}')
    
    cfg = adapter.load_config()
    assert cfg.get("MQTT_HOST") == "192.168.1.10"
    assert cfg.get("MQTT_PORT") == 1883

def test_docker_platform_adapter_config_corrupted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    adapter = DockerPlatformAdapter()
    config_file = tmp_path / "config.json"
    config_file.write_text('{invalid json')
    
    cfg = adapter.load_config()
    assert cfg == {}

def test_loxberry_platform_adapter_no_env(monkeypatch):
    monkeypatch.delenv("LBHOME", raising=False)
    adapter = LoxBerryPlatformAdapter()
    adapter.initialize()
    assert adapter.get_loxberry_paths() == {}
    assert adapter.get_data_dir() == "."
    assert adapter.get_log_dir() == "."

def test_loxberry_platform_adapter_with_env(tmp_path, monkeypatch):
    lb_root = tmp_path / "opt" / "loxberry"
    lb_sys_python = lb_root / "system" / "python"
    lb_sys_python.mkdir(parents=True)
    
    monkeypatch.setenv("LBHOME", str(lb_root))
    adapter = LoxBerryPlatformAdapter()
    adapter.initialize()
    
    paths = adapter.get_loxberry_paths()
    assert paths.get("LBHOME") == str(lb_root)
    assert paths.get("LBPDATA") == str(lb_root / "data" / "plugins" / "smtp2mqtt")
    assert adapter.get_data_dir() == str(lb_root / "data" / "plugins" / "smtp2mqtt")
    assert adapter.get_log_dir() == str(lb_root / "log" / "plugins" / "smtp2mqtt")

def test_loxberry_platform_adapter_mqtt_ini_and_json(tmp_path, monkeypatch):
    lb_root = tmp_path / "opt" / "loxberry"
    lb_sys = lb_root / "config" / "system"
    lb_sys.mkdir(parents=True)
    
    mqtt_ini = lb_sys / "mqttgateway.ini"
    mqtt_ini.write_text("[Main]\nbrokeraddress = 10.0.0.1\nbrokerport = 1883\nbrokeruser = user1\nbrokerpass = pass1\n")
    
    monkeypatch.setenv("LBHOME", str(lb_root))
    adapter = LoxBerryPlatformAdapter()
    paths = adapter.get_loxberry_paths()
    
    cfg_ini = adapter.load_loxberry_mqtt_config(paths)
    assert cfg_ini.get("MQTT_HOST") == "10.0.0.1"
    assert cfg_ini.get("MQTT_PORT") == "1883"
    assert cfg_ini.get("MQTT_USERNAME") == "user1"
    
    # Overwrite with JSON config
    mqtt_json = lb_sys / "mqttgateway.json"
    mqtt_json.write_text('{"Main": {"mqttserver": "10.0.0.2", "mqttport": 1884, "mqttuser": "user2", "mqttpass": "pass2"}}')
    
    cfg_json = adapter.load_loxberry_mqtt_config(paths)
    assert cfg_json.get("MQTT_HOST") == "10.0.0.2"
    assert cfg_json.get("MQTT_PORT") == 1884
    assert cfg_json.get("MQTT_USERNAME") == "user2"

def test_get_platform_adapter_detection(monkeypatch, tmp_path):
    monkeypatch.delenv("LBHOME", raising=False)
    adapter = get_platform_adapter()
    assert isinstance(adapter, DockerPlatformAdapter)
    
    monkeypatch.setenv("LBHOME", str(tmp_path))
    adapter_lb = get_platform_adapter()
    assert isinstance(adapter_lb, LoxBerryPlatformAdapter)

def test_main_entrypoint(monkeypatch):
    with mock.patch("smtp2mqtt.main") as mock_legacy_main:
        main()
        mock_legacy_main.assert_called_once()

def test_loxberry_platform_adapter_full_load_config(tmp_path, monkeypatch):
    lb_root = tmp_path / "opt" / "loxberry"
    lb_cfg_dir = lb_root / "config" / "plugins" / "smtp2mqtt"
    lb_cfg_dir.mkdir(parents=True)
    
    config_file = lb_cfg_dir / "config.json"
    config_file.write_text('{"MQTT_RESET_TIME": 200}')
    
    monkeypatch.setenv("LBHOME", str(lb_root))
    adapter = LoxBerryPlatformAdapter()
    merged = adapter.load_config()
    assert merged.get("MQTT_RESET_TIME") == 200

def test_loxberry_platform_adapter_config_corrupted_file(tmp_path, monkeypatch):
    lb_root = tmp_path / "opt" / "loxberry"
    lb_cfg_dir = lb_root / "config" / "plugins" / "smtp2mqtt"
    lb_cfg_dir.mkdir(parents=True)
    
    config_file = lb_cfg_dir / "config.json"
    config_file.write_text('{corrupted json')
    
    monkeypatch.setenv("LBHOME", str(lb_root))
    adapter = LoxBerryPlatformAdapter()
    merged = adapter.load_config()
    assert isinstance(merged, dict)

