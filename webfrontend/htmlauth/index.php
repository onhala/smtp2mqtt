<?php
require_once "loxberry_web.php";
require_once "loxberry_system.php";

// Read LoxBerry language file if present
$L = LBSystem::readlanguage("language.ini");

// Define paths
$config_dir = $lbpconfigdir;
$config_file = $config_dir . "/config.json";
$log_file = $lbplogdir . "/smtp2mqtt.log";
$daemon_script = $lbpbindir . "/smtp2mqtt.py";
if (!file_exists($daemon_script) && file_exists($lbpbindir . "/bin/smtp2mqtt.py")) {
    $daemon_script = $lbpbindir . "/bin/smtp2mqtt.py";
}

// Default settings
$defaults = [
    "WEB_PORT" => 8080,
    "SMTP_PORT" => 1025,
    "USE_LOXBERRY_MQTT" => "True",
    "MQTT_HOST" => "localhost",
    "MQTT_PORT" => 1883,
    "MQTT_USERNAME" => "",
    "MQTT_PASSWORD" => "",
    "MQTT_TOPIC" => "smtp2mqtt",
    "MQTT_PAYLOAD" => "ON",
    "MQTT_RESET_TIME" => 10,
    "MQTT_RESET_PAYLOAD" => "OFF",
    "SAVE_ATTACHMENTS" => "True",
    "CLEANUP_ATTACHMENTS_DAYS" => 30,
    "CLEANUP_LOGS_DAYS" => 30,
    "DEBUG" => "False"
];

// Try reading LoxBerry MQTT Gateway defaults if available
$lb_mqtt_file = $lbsysconfigdir . "/mqttgateway.json";
$detected_mqtt = [
    "MQTT_HOST" => "localhost",
    "MQTT_PORT" => 1883,
    "MQTT_USERNAME" => "",
    "MQTT_PASSWORD" => ""
];
if (file_exists($lb_mqtt_file)) {
    $mqtt_data = json_decode(file_get_contents($lb_mqtt_file), true);
    $main = $mqtt_data['Main'] ?? $mqtt_data['Credentials'] ?? $mqtt_data ?? [];
    if (!empty($main['brokeraddress']) || !empty($main['mqttserver'])) {
        $detected_mqtt['MQTT_HOST'] = $main['brokeraddress'] ?? $main['mqttserver'] ?? "localhost";
        $detected_mqtt['MQTT_PORT'] = intval($main['brokerport'] ?? $main['mqttport'] ?? 1883);
        $detected_mqtt['MQTT_USERNAME'] = $main['brokeruser'] ?? $main['mqttuser'] ?? "";
        $detected_mqtt['MQTT_PASSWORD'] = $main['brokerpass'] ?? $main['mqttpass'] ?? "";

        $defaults['MQTT_HOST'] = $detected_mqtt['MQTT_HOST'];
        $defaults['MQTT_PORT'] = $detected_mqtt['MQTT_PORT'];
        $defaults['MQTT_USERNAME'] = $detected_mqtt['MQTT_USERNAME'];
        $defaults['MQTT_PASSWORD'] = $detected_mqtt['MQTT_PASSWORD'];
    }
}

// Handle Log & Daemon Actions (Start / Stop / Restart / Download / Clear)
if (isset($_GET['action'])) {
    if ($_GET['action'] === 'restart_daemon') {
        exec("pkill -f smtp2mqtt.py 2>&1");
        sleep(1);
        exec("nohup python3 " . escapeshellarg($daemon_script) . " > /dev/null 2>&1 &");
        header('Location: index.php?tab=logs&started=1');
        exit;
    }
    if ($_GET['action'] === 'download_log' && file_exists($log_file)) {
        header('Content-Type: text/plain');
        header('Content-Disposition: attachment; filename="smtp2mqtt.log"');
        readfile($log_file);
        exit;
    }
    if ($_GET['action'] === 'clear_log' && file_exists($log_file)) {
        file_put_contents($log_file, "");
        header('Location: index.php?tab=logs&cleared=1');
        exit;
    }
}

// Read current config if file exists
$config = $defaults;
if (file_exists($config_file)) {
    $json_content = file_get_contents($config_file);
    $saved_config = json_decode($json_content, true);
    if (is_array($saved_config)) {
        $config = array_merge($defaults, $saved_config);
    }
}

// Handle Form Submission
$message = "";
$message_type = "success";
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['save_settings'])) {
    $config['WEB_PORT'] = intval($_POST['web_port'] ?? 8080);
    $config['SMTP_PORT'] = intval($_POST['smtp_port'] ?? 1025);
    $use_auto = isset($_POST['use_loxberry_mqtt']);
    $config['USE_LOXBERRY_MQTT'] = $use_auto ? "True" : "False";

    if ($use_auto) {
        $config['MQTT_HOST'] = $detected_mqtt['MQTT_HOST'];
        $config['MQTT_PORT'] = $detected_mqtt['MQTT_PORT'];
        $config['MQTT_USERNAME'] = $detected_mqtt['MQTT_USERNAME'];
        $config['MQTT_PASSWORD'] = $detected_mqtt['MQTT_PASSWORD'];
    } else {
        $config['MQTT_HOST'] = trim($_POST['mqtt_host'] ?? 'localhost');
        $config['MQTT_PORT'] = intval($_POST['mqtt_port'] ?? 1883);
        $config['MQTT_USERNAME'] = trim($_POST['mqtt_username'] ?? '');
        $config['MQTT_PASSWORD'] = $_POST['mqtt_password'] ?? '';
    }

    $config['MQTT_TOPIC'] = trim($_POST['mqtt_topic'] ?? 'smtp2mqtt');
    $config['MQTT_PAYLOAD'] = trim($_POST['mqtt_payload'] ?? 'ON');
    $config['MQTT_RESET_TIME'] = intval($_POST['mqtt_reset_time'] ?? 10);
    $config['MQTT_RESET_PAYLOAD'] = trim($_POST['mqtt_reset_payload'] ?? 'OFF');
    $config['SAVE_ATTACHMENTS'] = isset($_POST['save_attachments']) ? "True" : "False";
    $config['CLEANUP_ATTACHMENTS_DAYS'] = intval($_POST['cleanup_attachments_days'] ?? 30);
    $config['CLEANUP_LOGS_DAYS'] = intval($_POST['cleanup_logs_days'] ?? 30);
    $config['DEBUG'] = isset($_POST['debug']) ? "True" : "False";

    if (!file_exists($config_dir)) {
        mkdir($config_dir, 0755, true);
    }

    if (file_put_contents($config_file, json_encode($config, JSON_PRETTY_PRINT))) {
        $message = "Konfigurace uložena. Restartuji službu smtp2mqtt...";
        // Restart daemon process without sudo
        exec("pkill -f smtp2mqtt.py 2>&1");
        sleep(1);
        exec("nohup python3 " . escapeshellarg($daemon_script) . " > /dev/null 2>&1 &");
    } else {
        $message = "Chyba při zápisu do konfiguračního souboru!";
        $message_type = "danger";
    }
}

// Check daemon process status
$is_running = false;
unset($pgrep_out);
exec("pgrep -f smtp2mqtt.py", $pgrep_out);
if (!empty($pgrep_out)) {
    $is_running = true;
}

// Output LoxBerry Header
LBWeb::lbheader("smtp2mqtt Bridge", "https://github.com/onhala/smtp2mqtt", "smtp2mqtt");

// Determine Dashboard URL dynamically based on configured WEB_PORT with LoxBerry theme
$port = $config['WEB_PORT'];
$host = parse_url("http://" . $_SERVER['HTTP_HOST'], PHP_URL_HOST);
$dashboard_url = "http://" . $host . ":" . $port . "?theme=loxberry";
$active_tab = $_GET['tab'] ?? 'settings';
?>

<style>
    .lox-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        margin-bottom: 20px;
        overflow: hidden;
    }
    .lox-card-header {
        background: #f8fafc;
        border-bottom: 1px solid #e2e8f0;
        padding: 14px 20px;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .lox-card-title {
        font-size: 1.1rem;
        font-weight: 700;
        color: #1e293b;
        margin: 0;
    }
    .lox-card-body {
        padding: 20px;
    }
    .lox-nav-tabs {
        display: flex;
        gap: 8px;
        border-bottom: 2px solid #e2e8f0;
        margin-bottom: 20px;
    }
    .lox-tab-btn {
        padding: 10px 20px;
        font-weight: 600;
        font-size: 0.95rem;
        color: #64748b;
        text-decoration: none;
        border-bottom: 3px solid transparent;
        transition: all 0.2s;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .lox-tab-btn:hover {
        color: #2e7d32;
    }
    .lox-tab-btn.active {
        color: #2e7d32;
        border-bottom-color: #6fb738;
        background: #f1f8e9;
        border-radius: 6px 6px 0 0;
    }
    .lox-btn-primary {
        background: #6fb738;
        color: #ffffff;
        border: none;
        padding: 10px 20px;
        border-radius: 6px;
        font-weight: bold;
        cursor: pointer;
        transition: background 0.2s;
        text-decoration: none;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .lox-btn-primary:hover {
        background: #5ea02f;
    }
    .lox-btn-secondary {
        background: #f1f5f9;
        color: #334155;
        border: 1px solid #cbd5e1;
        padding: 8px 16px;
        border-radius: 6px;
        font-weight: 600;
        cursor: pointer;
        text-decoration: none;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .lox-btn-secondary:hover {
        background: #e2e8f0;
    }
    .lox-badge-info {
        background: #e0f2fe;
        color: #0369a1;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.82rem;
        font-weight: 600;
    }
    .lox-badge-success {
        background: #dcfce7;
        color: #15803d;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.82rem;
        font-weight: 600;
    }
    .lox-badge-danger {
        background: #fee2e2;
        color: #b91c1c;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.82rem;
        font-weight: 600;
    }
    .log-viewer-box {
        background: #0f172a;
        color: #f8fafc;
        font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
        font-size: 0.85rem;
        padding: 15px;
        border-radius: 6px;
        max-height: 550px;
        overflow-y: auto;
        white-space: pre-wrap;
        line-height: 1.5;
        border: 1px solid #334155;
    }
    .log-line-info { color: #4ade80; }
    .log-line-warn { color: #facc15; }
    .log-line-error { color: #f87171; }
    .log-line-debug { color: #38bdf8; }
</style>

<div style="padding: 10px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
    
    <?php if ($message): ?>
        <div style="padding: 12px 16px; margin-bottom: 20px; border-radius: 6px; background-color: <?php echo $message_type === 'success' ? '#dcfce7' : '#fee2e2'; ?>; color: <?php echo $message_type === 'success' ? '#166534' : '#991b1b'; ?>; border: 1px solid <?php echo $message_type === 'success' ? '#bbf7d0' : '#fecaca'; ?>; font-weight: 600;">
            <?php echo htmlspecialchars($message); ?>
        </div>
    <?php endif; ?>

    <!-- Navigation Tabs -->
    <div class="lox-nav-tabs">
        <a href="?tab=settings" class="lox-tab-btn <?php echo $active_tab === 'settings' ? 'active' : ''; ?>">
            ⚙️ Nastavení Pluginu
        </a>
        <a href="?tab=dashboard" class="lox-tab-btn <?php echo $active_tab === 'dashboard' ? 'active' : ''; ?>">
            📊 Živý Dashboard
        </a>
        <a href="?tab=logs" class="lox-tab-btn <?php echo $active_tab === 'logs' ? 'active' : ''; ?>">
            📋 Systémový Log
        </a>
    </div>

    <?php if ($active_tab === 'settings'): ?>
        <!-- Settings Form Tab -->
        <div class="lox-card">
            <div class="lox-card-header">
                <div style="display: flex; align-items: center; gap: 12px;">
                    <h3 class="lox-card-title">⚙️ Konfigurace služby smtp2mqtt</h3>
                    <?php if ($is_running): ?>
                        <span class="lox-badge-success">🟢 Služba Běží</span>
                    <?php else: ?>
                        <span class="lox-badge-danger">🔴 Služba Zastavena</span>
                    <?php endif; ?>
                </div>
                <span class="lox-badge-info">Verze 1.8.3</span>
            </div>
            <div class="lox-card-body">
                <form method="post" action="?tab=settings" id="config-form">
                    
                    <!-- Network Ports -->
                    <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 1rem; border-bottom: 2px solid #f1f8e9; padding-bottom: 6px;">🌐 Síťová Rozhraní</h4>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 25px;">
                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">Web Dashboard Port:</label>
                            <input type="number" name="web_port" value="<?php echo htmlspecialchars($config['WEB_PORT']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>
                        
                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">SMTP Server Port:</label>
                            <input type="number" name="smtp_port" value="<?php echo htmlspecialchars($config['SMTP_PORT']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>
                    </div>

                    <!-- MQTT Broker Settings -->
                    <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 1rem; border-bottom: 2px solid #f1f8e9; padding-bottom: 6px;">📡 MQTT Broker & Témata</h4>
                    
                    <div style="margin-bottom: 15px; background: #f8fafc; padding: 12px 15px; border-radius: 6px; border: 1px solid #e2e8f0;">
                        <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                            <input type="checkbox" name="use_loxberry_mqtt" id="use_loxberry_mqtt" onchange="toggleMqttFields()" <?php echo ($config['USE_LOXBERRY_MQTT'] === "True" || $config['USE_LOXBERRY_MQTT'] === true) ? 'checked' : ''; ?>>
                            <span style="font-weight: 700; color: #2e7d32;">Použít automatickou detekci z LoxBerry MQTT Gateway V2</span>
                        </label>
                        <div id="mqtt-auto-badge" style="margin-top: 6px; font-size: 0.85rem; color: #0284c7; display: none;">
                            ℹ️ Přihlašovací údaje jsou automaticky přebírány ze systému LoxBerry a pole níže jsou uzamčena.
                        </div>
                    </div>

                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 25px;">
                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">MQTT Server Host:</label>
                            <input type="text" name="mqtt_host" id="mqtt_host" value="<?php echo htmlspecialchars($config['MQTT_HOST']); ?>" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">MQTT Server Port:</label>
                            <input type="number" name="mqtt_port" id="mqtt_port" value="<?php echo htmlspecialchars($config['MQTT_PORT']); ?>" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">MQTT Uživatel:</label>
                            <input type="text" name="mqtt_username" id="mqtt_username" value="<?php echo htmlspecialchars($config['MQTT_USERNAME']); ?>" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">MQTT Heslo:</label>
                            <input type="password" name="mqtt_password" id="mqtt_password" value="<?php echo htmlspecialchars($config['MQTT_PASSWORD']); ?>" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">MQTT Root Topic:</label>
                            <input type="text" name="mqtt_topic" value="<?php echo htmlspecialchars($config['MQTT_TOPIC']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">MQTT Trigger Payload:</label>
                            <input type="text" name="mqtt_payload" value="<?php echo htmlspecialchars($config['MQTT_PAYLOAD']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">MQTT Reset Čas (sec):</label>
                            <input type="number" name="mqtt_reset_time" value="<?php echo htmlspecialchars($config['MQTT_RESET_TIME']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">MQTT Reset Payload:</label>
                            <input type="text" name="mqtt_reset_payload" value="<?php echo htmlspecialchars($config['MQTT_RESET_PAYLOAD']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>
                    </div>

                    <!-- Maintenance & Media Retention -->
                    <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 1rem; border-bottom: 2px solid #f1f8e9; padding-bottom: 6px;">🧹 Přílohy & Údržba</h4>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 20px;">
                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">Retence Příloh (Dní):</label>
                            <input type="number" name="cleanup_attachments_days" value="<?php echo htmlspecialchars($config['CLEANUP_ATTACHMENTS_DAYS']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">Retence Logů (Dní):</label>
                            <input type="number" name="cleanup_logs_days" value="<?php echo htmlspecialchars($config['CLEANUP_LOGS_DAYS']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>
                    </div>

                    <div style="display: flex; gap: 25px; margin-top: 15px; align-items: center;">
                        <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                            <input type="checkbox" name="save_attachments" <?php echo ($config['SAVE_ATTACHMENTS'] === "True" || $config['SAVE_ATTACHMENTS'] === true) ? 'checked' : ''; ?>>
                            <span style="font-weight: 600; color: #334155;">Ukládat obrázkové přílohy z e-mailů</span>
                        </label>
                        
                        <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                            <input type="checkbox" name="debug" <?php echo ($config['DEBUG'] === "True" || $config['DEBUG'] === true) ? 'checked' : ''; ?>>
                            <span style="font-weight: 600; color: #334155;">Ladící režim (DEBUG)</span>
                        </label>
                    </div>

                    <div style="margin-top: 25px; border-top: 1px solid #e2e8f0; padding-top: 15px; display: flex; gap: 15px; align-items: center;">
                        <button type="submit" name="save_settings" class="lox-btn-primary">💾 Uložit & Restartovat Službu</button>
                        <a href="?action=restart_daemon" class="lox-btn-secondary">🔄 Vynutit Restart Služby</a>
                    </div>
                </form>
            </div>
        </div>

        <script>
            const detectedMqtt = <?php echo json_encode($detected_mqtt); ?>;

            function toggleMqttFields() {
                const isAuto = document.getElementById('use_loxberry_mqtt').checked;
                const hostInput = document.getElementById('mqtt_host');
                const portInput = document.getElementById('mqtt_port');
                const userInput = document.getElementById('mqtt_username');
                const passInput = document.getElementById('mqtt_password');
                const autoBadge = document.getElementById('mqtt-auto-badge');

                if (isAuto) {
                    hostInput.value = detectedMqtt.MQTT_HOST;
                    portInput.value = detectedMqtt.MQTT_PORT;
                    userInput.value = detectedMqtt.MQTT_USERNAME;
                    passInput.value = detectedMqtt.MQTT_PASSWORD;

                    hostInput.disabled = true;
                    portInput.disabled = true;
                    userInput.disabled = true;
                    passInput.disabled = true;

                    hostInput.style.backgroundColor = '#f1f5f9';
                    portInput.style.backgroundColor = '#f1f5f9';
                    userInput.style.backgroundColor = '#f1f5f9';
                    passInput.style.backgroundColor = '#f1f5f9';

                    autoBadge.style.display = 'block';
                } else {
                    hostInput.disabled = false;
                    portInput.disabled = false;
                    userInput.disabled = false;
                    passInput.disabled = false;

                    hostInput.style.backgroundColor = '#ffffff';
                    portInput.style.backgroundColor = '#ffffff';
                    userInput.style.backgroundColor = '#ffffff';
                    passInput.style.backgroundColor = '#ffffff';

                    autoBadge.style.display = 'none';
                }
            }
            toggleMqttFields();
        </script>

    <?php elseif ($active_tab === 'dashboard'): ?>
        <!-- Embedded Dashboard Tab -->
        <div class="lox-card">
            <div class="lox-card-header" style="background: #ffffff;">
                <div>
                    <h3 class="lox-card-title">📧 smtp2mqtt Live Dashboard</h3>
                    <p style="margin: 4px 0 0 0; font-size: 0.85rem; color: #64748b;">Živý přehled přijatých zpráv, kamerových snapshotů a stavu připojení na portu <?php echo htmlspecialchars($port); ?></p>
                </div>
                <div>
                    <a href="<?php echo $dashboard_url; ?>" target="_blank" class="lox-btn-secondary">Otevřít samostatně ↗</a>
                </div>
            </div>
            <iframe src="<?php echo $dashboard_url; ?>" style="width: 100%; height: 750px; border: none; background: #ffffff;"></iframe>
        </div>

    <?php elseif ($active_tab === 'logs'): ?>
        <!-- System Logs Tab -->
        <div class="lox-card">
            <div class="lox-card-header">
                <div>
                    <h3 class="lox-card-title">📋 Prohlížeč Logů (smtp2mqtt.log)</h3>
                    <p style="margin: 4px 0 0 0; font-size: 0.85rem; color: #64748b;">Živý log z adresáře pluginu pro ladění a diagnostiku</p>
                </div>
                <div style="display: flex; gap: 10px;">
                    <a href="?tab=logs" class="lox-btn-secondary">🔄 Obnovit</a>
                    <a href="?action=restart_daemon" class="lox-btn-secondary" style="color: #0284c7;">🚀 Spustit Službu</a>
                    <?php if (file_exists($log_file)): ?>
                        <a href="?action=download_log" class="lox-btn-secondary">📥 Stáhnout Log</a>
                        <a href="?action=clear_log" onclick="return confirm('Opravdu chcete vyčistit soubor logů?');" class="lox-btn-secondary" style="color: #dc2626;">🧹 Vyčistit</a>
                    <?php endif; ?>
                </div>
            </div>
            <div class="lox-card-body">
                <?php
                $has_file_log = file_exists($log_file) && filesize($log_file) > 0;
                if ($has_file_log) {
                    $log_lines = file($log_file);
                    echo '<div class="log-viewer-box" id="log-box">';
                    foreach ($log_lines as $line) {
                        $escaped_line = htmlspecialchars($line);
                        $class = '';
                        if (strpos($line, 'ERROR') !== false || strpos($line, 'CRITICAL') !== false) {
                            $class = 'log-line-error';
                        } elseif (strpos($line, 'WARNING') !== false) {
                            $class = 'log-line-warn';
                        } elseif (strpos($line, 'INFO') !== false) {
                            $class = 'log-line-info';
                        } elseif (strpos($line, 'DEBUG') !== false) {
                            $class = 'log-line-debug';
                        }
                        echo '<span class="' . $class . '">' . $escaped_line . '</span>';
                    }
                    echo '</div>';
                } else {
                    unset($py_err);
                    exec("python3 " . escapeshellarg($daemon_script) . " 2>&1", $py_err);
                    echo '<div style="margin-bottom: 12px; font-weight: 600; color: #d97706; background: #fffbebf; padding: 12px 16px; border-radius: 6px; border: 1px solid #fef3c7;">⚠️ Soubor logů smtp2mqtt.log zatím neobsahuje žádná data.<br><br><a href="?action=restart_daemon" class="lox-btn-primary">🚀 Spustit / Restartovat Službu smtp2mqtt</a></div>';
                    if (!empty($py_err)) {
                        echo '<div class="log-viewer-box" id="log-box">';
                        foreach ($py_err as $line) {
                            echo htmlspecialchars($line) . "\n";
                        }
                        echo '</div>';
                    }
                }
                ?>
            </div>
        </div>

        <script>
            const logBox = document.getElementById('log-box');
            if (logBox) {
                logBox.scrollTop = logBox.scrollHeight;
            }
        </script>
    <?php endif; ?>

</div>

<?php
LBWeb::lbfooter();
?>
