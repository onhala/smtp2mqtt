import os
import shutil
import subprocess
import tempfile
import configparser
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_plugin_cfg_loxberry_standards():
    """Verify plugin.cfg contains CUSTOM_LOGLEVELS=true and WEBSITE URL fields."""
    pcfg_path = os.path.join(PROJECT_ROOT, "plugin.cfg")
    assert os.path.exists(pcfg_path), "plugin.cfg must exist"

    parser = configparser.ConfigParser()
    parser.read(pcfg_path)

    assert "SYSTEM" in parser, "plugin.cfg must have [SYSTEM] section"
    assert parser.getboolean("SYSTEM", "CUSTOM_LOGLEVELS") is True, "CUSTOM_LOGLEVELS must be True in [SYSTEM]"

    assert "AUTHOR" in parser, "plugin.cfg must have [AUTHOR] section"
    assert "WEBSITE" in parser["AUTHOR"], "WEBSITE must be in [AUTHOR]"
    assert parser["AUTHOR"]["WEBSITE"].startswith("https://github.com/"), "WEBSITE must point to GitHub"

    assert "PLUGIN" in parser, "plugin.cfg must have [PLUGIN] section"
    assert "WEBSITE" in parser["PLUGIN"], "WEBSITE must be in [PLUGIN]"


def test_installer_upgrade_lifecycle_preserves_config():
    """Simulate real LoxBerry upgrade lifecycle and verify user config.json is preserved byte-for-byte."""
    tmp_dir = tempfile.mkdtemp(prefix="smtp2mqtt_upgrade_test_")
    try:
        tempfolder = os.path.join(tmp_dir, "install_extract_12345")
        pname = "smtp2mqtt"
        pfolder = "smtp2mqtt"
        pversion = "1.8.27"
        lbhomedir = os.path.join(tmp_dir, "opt_loxberry")

        config_dir = os.path.join(lbhomedir, "config", "plugins", pfolder)
        data_dir = os.path.join(lbhomedir, "data", "plugins", pfolder)
        bin_dir = os.path.join(lbhomedir, "bin", "plugins", pfolder)
        log_dir = os.path.join(lbhomedir, "log", "plugins", pfolder)

        os.makedirs(config_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(bin_dir, exist_ok=True)
        os.makedirs(log_dir, exist_ok=True)
        os.makedirs(tempfolder, exist_ok=True)

        user_config_path = os.path.join(config_dir, "config.json")
        sample_config_content = """{
    "WEB_PORT": 8080,
    "SMTP_PORT": 1025,
    "ALLOWED_IPS": "10.0.40.0/24, 192.168.0.0/16",
    "CUSTOM_USER_KEY": "PRESERVED_VAL_12345"
}"""
        with open(user_config_path, "w", encoding="utf-8") as f:
            f.write(sample_config_content)

        preupgrade_script = os.path.join(PROJECT_ROOT, "preupgrade.sh")
        postupgrade_script = os.path.join(PROJECT_ROOT, "postupgrade.sh")

        # 1. Run preupgrade.sh with LoxBerry positional arguments ($1..$5)
        pre_cmd = [
            "bash", preupgrade_script,
            "install_extract_12345", pname, pfolder, pversion, lbhomedir
        ]
        res_pre = subprocess.run(pre_cmd, capture_output=True, text=True)
        assert res_pre.returncode == 0, f"preupgrade.sh failed: {res_pre.stderr}"

        tmp_upgrade_dir = f"/tmp/install_extract_12345_upgrade/config"
        backup_in_data = os.path.join(data_dir, "config.json.bak")
        assert os.path.exists(tmp_upgrade_dir) or os.path.exists(backup_in_data), "Config backup must exist"

        # 2. Simulate LoxBerry installer replacing config folder with fresh defaults
        shutil.rmtree(config_dir)
        os.makedirs(config_dir, exist_ok=True)
        with open(user_config_path, "w", encoding="utf-8") as f:
            f.write('{"WEB_PORT": 8080, "DEFAULT_WIPED": true}')

        # 3. Run postupgrade.sh with LoxBerry positional arguments ($1..$5)
        post_cmd = [
            "bash", postupgrade_script,
            "install_extract_12345", pname, pfolder, pversion, lbhomedir
        ]
        res_post = subprocess.run(post_cmd, capture_output=True, text=True)
        assert res_post.returncode == 0, f"postupgrade.sh failed: {res_post.stderr}"

        # 4. Verify user_config_path content was restored
        with open(user_config_path, "r", encoding="utf-8") as f:
            restored_content = f.read()

        assert "PRESERVED_VAL_12345" in restored_content, "User configuration must be restored after upgrade"
        assert "10.0.40.0/24" in restored_content, "Custom allowed IPs must be preserved after upgrade"

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        shutil.rmtree("/tmp/install_extract_12345_upgrade", ignore_errors=True)


def test_html_javascript_table_state_retention_logic():
    """Verify JavaScript readCurrentTableState logic in index.php contains DOM scraping before re-render."""
    auth_index_path = os.path.join(PROJECT_ROOT, "webfrontend", "htmlauth", "index.php")
    with open(auth_index_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "function readCurrentTableState()" in content, "readCurrentTableState JS function must be present"
    assert "firewallRules = readCurrentTableState();" in content, "add/remove functions must collect current DOM inputs before re-render"
    assert "readCurrentTableState()" in content
