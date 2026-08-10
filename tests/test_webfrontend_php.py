import json
import os
import shutil
import subprocess
import tempfile
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOCK_DIR = os.path.join(PROJECT_ROOT, "tests", "mock_loxberry")

def _check_docker():
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, timeout=2)
        return res.returncode == 0
    except Exception:
        return False

pytestmark = pytest.mark.skipif(not _check_docker(), reason="Docker daemon is not running")


def run_php_script_in_dir(tmp_dir, query_string="", post_data=None, env_vars=None):
    """Helper to run index.php in php:8.2-cli Docker container with mock LoxBerry SDK."""
    lb_config = os.path.join(tmp_dir, "config")
    lb_data = os.path.join(tmp_dir, "data")
    lb_log = os.path.join(tmp_dir, "log")
    lb_bin = os.path.join(tmp_dir, "bin")
    lb_sysconfig = os.path.join(tmp_dir, "sysconfig")

    for d in [tmp_dir, lb_config, lb_data, lb_log, lb_bin, lb_sysconfig]:
        os.makedirs(d, exist_ok=True)
        os.chmod(d, 0o777)

    status_data = {
        "smtp_connected": True,
        "mqtt_connected": True,
        "uptime_formatted": "1d 2h 15m",
        "processed_messages_count": 42,
        "recent_actions": [
            {
                "timestamp": "2026-08-02 14:00:00",
                "type": "trigger",
                "sender": "kamera1@domov.local",
                "topic": "smtp2mqtt/kamera1",
                "payload": "ON",
                "status": "SUCCESS"
            }
        ]
    }
    with open(os.path.join(lb_data, "status.json"), "w", encoding="utf-8") as f:
        json.dump(status_data, f)
    os.chmod(os.path.join(lb_data, "status.json"), 0o666)

    csrf_val = post_data.get("csrf_token", "mock_csrf_123") if post_data else "mock_csrf_123"

    php_code = f"""
    @session_save_path('/tmp');
    session_id(md5(microtime() . rand()));
    @session_start();
    $_SESSION['csrf_token'] = '{csrf_val}';
    $_SERVER['HTTP_HOST'] = '127.0.0.1:80';
    $_SERVER['REQUEST_METHOD'] = '{'POST' if post_data else 'GET'}';
    parse_str('{query_string}', $_GET);
    """

    if post_data:
        php_code += f"$_POST = json_decode('{json.dumps(post_data)}', true);\n"

    php_code += f"""
    require_once '{os.path.join(MOCK_DIR, "loxberry_web.php")}';
    require_once '{os.path.join(MOCK_DIR, "loxberry_system.php")}';
    require '{os.path.join(PROJECT_ROOT, "webfrontend", "htmlauth", "index.php")}';
    """

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{PROJECT_ROOT}:{PROJECT_ROOT}",
        "-w", PROJECT_ROOT,
        "-e", f"LBPCONFIG_DIR={lb_config}",
        "-e", f"LBPDATA_DIR={lb_data}",
        "-e", f"LBPLOG_DIR={lb_log}",
        "-e", f"LBPBIN_DIR={lb_bin}",
        "-e", f"LBSYSCONFIG_DIR={lb_sysconfig}",
        "php:8.2-cli", "php",
        "-d", f"include_path={MOCK_DIR}",
        "-r", php_code
    ]

    res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return res, lb_config


def test_php_syntax_linter():
    """Verify that all PHP files have zero syntax errors using php -l in Docker."""
    php_files = [
        os.path.join(PROJECT_ROOT, "webfrontend", "htmlauth", "index.php"),
        os.path.join(PROJECT_ROOT, "webfrontend", "html", "index.php"),
        os.path.join(MOCK_DIR, "loxberry_web.php"),
        os.path.join(MOCK_DIR, "loxberry_system.php"),
    ]

    for php_file in php_files:
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{PROJECT_ROOT}:{PROJECT_ROOT}",
            "-w", PROJECT_ROOT,
            "php:8.2-cli", "php", "-l", php_file
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0, f"PHP Syntax error in {php_file}: {res.stderr}"
        assert "No syntax errors detected" in res.stdout


def test_render_tabs_and_csrf_token():
    """Verify that all UI tabs render correctly and generate CSRF tokens."""
    os.makedirs(os.path.join(PROJECT_ROOT, "scratch"), exist_ok=True)
    tmp_dir = tempfile.mkdtemp(dir=os.path.join(PROJECT_ROOT, "scratch"))
    try:
        for tab in ["settings", "dashboard", "logs", "help"]:
            res, _ = run_php_script_in_dir(tmp_dir, f"tab={tab}")
            assert res.returncode == 0, f"Failed rendering tab={tab}: {res.stderr}"
            assert "MOCK_LOXBERRY_HEADER" in res.stdout
            assert "MOCK_LOXBERRY_FOOTER" in res.stdout

            if tab == "settings":
                assert "csrf_token" in res.stdout
                assert 'name="smtp_port"' in res.stdout
                assert "Rychlá Diagnostika Spojení" in res.stdout

            if tab == "help":
                assert "Hikvision" in res.stdout
                assert "Dahua" in res.stdout
                assert "Loxone Config Generator" in res.stdout
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_clean_json_ajax_endpoint():
    """Verify that ?tab=dashboard&_ajax=json returns valid JSON status payload."""
    os.makedirs(os.path.join(PROJECT_ROOT, "scratch"), exist_ok=True)
    tmp_dir = tempfile.mkdtemp(dir=os.path.join(PROJECT_ROOT, "scratch"))
    try:
        res, _ = run_php_script_in_dir(tmp_dir, "tab=dashboard&_ajax=json")
        assert res.returncode == 0, f"JSON AJAX failed: {res.stderr}"

        output = res.stdout.strip()
        json_start = output.find("{")
        assert json_start != -1, f"No JSON object found in output: {output}"

        data = json.loads(output[json_start:])
        assert "is_running" in data
        assert "version" in data
        assert "config" in data
        assert "status" in data
        assert data["status"]["processed_messages_count"] == 42
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_post_save_settings():
    """Verify saving settings updates config.json properly."""
    os.makedirs(os.path.join(PROJECT_ROOT, "scratch"), exist_ok=True)
    tmp_dir = tempfile.mkdtemp(dir=os.path.join(PROJECT_ROOT, "scratch"))
    try:
        post_payload = {
            "save_settings": "1",
            "csrf_token": "mock_csrf_123",
            "web_port": "8081",
            "smtp_port": "1026",
            "smtp_host": "0.0.0.0",
            "allowed_ips": "192.168.1.0/24",
            "mqtt_topic": "smtp2mqtt_test",
            "mqtt_payload": "ON",
            "mqtt_reset_time": "15",
            "mqtt_reset_payload": "OFF",
            "cleanup_attachments_days": "14",
            "cleanup_logs_days": "14"
        }

        res, lb_config = run_php_script_in_dir(tmp_dir, "tab=settings", post_data=post_payload)
        assert res.returncode == 0, f"PHP run failed: {res.stderr}"

        cfg_path = os.path.join(lb_config, "config.json")
        assert os.path.exists(cfg_path), f"config.json was not created. Output: {res.stdout}"

        with open(cfg_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
            assert saved["WEB_PORT"] == 8081
            assert saved["SMTP_PORT"] == 1026
            assert saved["ALLOWED_IPS"] == "192.168.1.0/24"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
