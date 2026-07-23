<?php
require_once "loxberry_web.php";
require_once "loxberry_system.php";

// Read LoxBerry language dictionary with fallback
$sys_lang = strtolower(substr($lbpconfig['BASE']['LANG'] ?? 'cs', 0, 2));
$lang_code = in_array($sys_lang, ['cs', 'en']) ? $sys_lang : 'cs';
$lang_file = __DIR__ . "/../../templates/lang/language_" . $lang_code . ".json";
if (!file_exists($lang_file)) {
    $lang_file = "/opt/loxberry/templates/plugins/smtp2mqtt/lang/language_" . $lang_code . ".json";
}
$L_json = file_exists($lang_file) ? (json_decode(file_get_contents($lang_file), true) ?? []) : [];
$L_ini = LBSystem::readlanguage("language.ini");
$L = array_merge(is_array($L_ini) ? $L_ini : [], $L_json);

// Define paths
$config_dir = $lbpconfigdir;
$config_file = $config_dir . "/config.json";
$log_candidates = [
    $lbplogdir . "/smtp2mqtt.log",
    "/opt/loxberry/log/plugins/smtp2mqtt.log",
    "/opt/loxberry/log/plugins/smtp2mqtt/smtp2mqtt.log"
];
$log_file = $lbplogdir . "/smtp2mqtt.log";
foreach ($log_candidates as $l_cand) {
    if (file_exists($l_cand) && filesize($l_cand) > 0) {
        $log_file = $l_cand;
        break;
    }
}
$daemon_candidates = [
    $lbpbindir . "/smtp2mqtt.py",
    $lbpbindir . "/bin/smtp2mqtt.py",
    "/opt/loxberry/bin/plugins/smtp2mqtt/smtp2mqtt.py",
    "/opt/loxberry/bin/plugins/smtp2mqtt/bin/smtp2mqtt.py"
];
$daemon_script = $lbpbindir . "/smtp2mqtt.py";
foreach ($daemon_candidates as $cand) {
    if (file_exists($cand)) {
        $daemon_script = $cand;
        break;
    }
}

// Default settings
$defaults = [
    "WEB_PORT" => 8080,
    "SMTP_PORT" => 1025,
    "SMTP_HOST" => "0.0.0.0",
    "ALLOWED_IPS" => "192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12, 127.0.0.1",
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
        exec("pkill -9 -f smtp2mqtt.py 2>&1");
        sleep(2);
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
    $config['SMTP_HOST'] = trim($_POST['smtp_host'] ?? '0.0.0.0');
    $config['ALLOWED_IPS'] = trim($_POST['allowed_ips'] ?? '192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12, 127.0.0.1');

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
        exec("pkill -9 -f smtp2mqtt.py 2>&1");
        sleep(2);
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
LBWeb::lbheader("smtp2mqtt Bridge", "http://" . $_SERVER['HTTP_HOST'] . "/admin/plugins/smtp2mqtt/?tab=help", "smtp2mqtt");

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
        margin-bottom: 20px;
        border-bottom: 2px solid #e2e8f0;
        padding-bottom: 2px;
    }
    .lox-tab-btn {
        padding: 10px 18px;
        font-weight: 600;
        color: #64748b;
        text-decoration: none;
        border-radius: 6px 6px 0 0;
        transition: all 0.2s ease;
        background: #f1f5f9;
        font-size: 0.95rem;
    }
    .lox-tab-btn:hover {
        color: #0f172a;
        background: #e2e8f0;
    }
    .lox-tab-btn.active {
        color: #ffffff;
        background: #6fb738;
        font-weight: 700;
    }
    .lox-btn-primary {
        background: #6fb738;
        color: #ffffff;
        border: none;
        padding: 10px 20px;
        border-radius: 6px;
        font-weight: 700;
        cursor: pointer;
        transition: background 0.2s ease;
    }
    .lox-btn-primary:hover {
        background: #5ea42e;
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
            <?php echo htmlspecialchars($L['TAB_SETTINGS'] ?? '⚙️ Nastavení Pluginu'); ?>
        </a>
        <a href="?tab=dashboard" class="lox-tab-btn <?php echo $active_tab === 'dashboard' ? 'active' : ''; ?>">
            <?php echo htmlspecialchars($L['TAB_DASHBOARD'] ?? '📊 Živý Dashboard'); ?>
        </a>
        <a href="?tab=logs" class="lox-tab-btn <?php echo $active_tab === 'logs' ? 'active' : ''; ?>">
            <?php echo htmlspecialchars($L['TAB_LOGS'] ?? '📋 Prohlížeč Logů'); ?>
        </a>
        <a href="?tab=help" class="lox-tab-btn <?php echo $active_tab === 'help' ? 'active' : ''; ?>">
            <?php echo htmlspecialchars($L['TAB_HELP'] ?? '📖 Nápověda & Průvodce'); ?>
        </a>
    </div>

    <?php if ($active_tab === 'settings'): ?>
        <!-- Settings Form Tab -->
        <div class="lox-card">
            <div class="lox-card-header">
                <div style="display: flex; align-items: center; gap: 12px;">
                    <h3 class="lox-card-title"><?php echo htmlspecialchars($L['TITLE'] ?? 'SMTP to MQTT Bridge'); ?></h3>
                    <?php if ($is_running): ?>
                        <span class="lox-badge-success">🟢 Služba Běží</span>
                    <?php else: ?>
                        <span class="lox-badge-danger">🔴 Služba Zastavena</span>
                    <?php endif; ?>
                </div>
                <span class="lox-badge-info">v1.8.17</span>
            </div>
            <div class="lox-card-body">
                <form method="post" action="?tab=settings" id="config-form">
                    
                    <!-- Network Ports & Binding -->
                    <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 1rem; border-bottom: 2px solid #f1f8e9; padding-bottom: 6px;"><?php echo htmlspecialchars($L['SEC_SERVERS'] ?? '🌐 Nastavení Serverů (SMTP & Web)'); ?></h4>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 20px;">
                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;"><?php echo htmlspecialchars($L['LABEL_SMTP_PORT'] ?? 'SMTP Server Port'); ?>:</label>
                            <input type="number" name="smtp_port" value="<?php echo htmlspecialchars($config['SMTP_PORT']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                            <span style="font-size: 0.78rem; color: #64748b; display: block; margin-top: 3px;"><?php echo htmlspecialchars($L['HELP_SMTP_PORT'] ?? 'Port, na kterém naslouchá vestavěný SMTP server.'); ?></span>
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;"><?php echo htmlspecialchars($L['LABEL_BIND_HOST'] ?? 'Vazební rozhraní (BIND_HOST)'); ?>:</label>
                            <select name="smtp_host" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px; background: white;">
                                <option value="0.0.0.0" <?php echo ($config['SMTP_HOST'] === '0.0.0.0') ? 'selected' : ''; ?>>0.0.0.0 (Všechna síťová rozhraní / LAN)</option>
                                <option value="127.0.0.1" <?php echo ($config['SMTP_HOST'] === '127.0.0.1') ? 'selected' : ''; ?>>127.0.0.1 (Pouze Localhost)</option>
                            </select>
                            <span style="font-size: 0.78rem; color: #64748b; display: block; margin-top: 3px;"><?php echo htmlspecialchars($L['HELP_BIND_HOST'] ?? '0.0.0.0 = Všechna rozhraní, 127.0.0.1 = Localhost.'); ?></span>
                        </div>
                        
                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;"><?php echo htmlspecialchars($L['LABEL_WEB_PORT'] ?? 'Web Admin Port'); ?>:</label>
                            <input type="number" name="web_port" value="<?php echo htmlspecialchars($config['WEB_PORT']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                            <span style="font-size: 0.78rem; color: #64748b; display: block; margin-top: 3px;"><?php echo htmlspecialchars($L['HELP_WEB_PORT'] ?? 'Port pro vestavěný Dashboard.'); ?></span>
                        </div>
                    </div>

                    <!-- Security & Firewall Settings -->
                    <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 1rem; border-bottom: 2px solid #f1f8e9; padding-bottom: 6px;"><?php echo htmlspecialchars($L['SEC_FIREWALL'] ?? '🔒 Bezpečnost & IP Firewall'); ?></h4>
                    <div style="margin-bottom: 25px;">
                        <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;"><?php echo htmlspecialchars($L['LABEL_ALLOWED_IPS'] ?? 'Povolené IP adresy a podsítě (ALLOWED_IPS)'); ?>:</label>
                        <input type="text" name="allowed_ips" value="<?php echo htmlspecialchars($config['ALLOWED_IPS']); ?>" placeholder="192.168.1.0/24, 10.0.0.5, 127.0.0.1" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        <span style="font-size: 0.8rem; color: #64748b; display: block; margin-top: 4px;"><?php echo htmlspecialchars($L['HELP_ALLOWED_IPS'] ?? 'Čárkou oddělený seznam povolených IP/CIDR. Ponechte prázdné nebo * pro povolené vše.'); ?></span>
                        <?php if (trim($config['ALLOWED_IPS']) === '*' || trim($config['ALLOWED_IPS']) === ''): ?>
                            <div style="margin-top: 8px; font-size: 0.82rem; color: #b45309; background: #fffbebf; padding: 8px 12px; border-radius: 4px; border: 1px solid #fef3c7;">
                                <?php echo htmlspecialchars($L['WARN_ALLOWED_IPS_ALL'] ?? '⚠️ Pozor: Zadáno * nebo prázdné pole. SMTP server přijme e-maily z jakékoliv IP adresy.'); ?>
                            </div>
                        <?php endif; ?>
                    </div>

                    <!-- MQTT Broker Settings -->
                    <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 1rem; border-bottom: 2px solid #f1f8e9; padding-bottom: 6px;"><?php echo htmlspecialchars($L['SEC_MQTT'] ?? '📡 Nastavení MQTT Brokeru'); ?></h4>
                    
                    <div style="margin-bottom: 15px; background: #f8fafc; padding: 12px 15px; border-radius: 6px; border: 1px solid #e2e8f0;">
                        <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                            <input type="checkbox" name="use_loxberry_mqtt" id="use_loxberry_mqtt" onchange="toggleMqttFields()" <?php echo ($config['USE_LOXBERRY_MQTT'] === "True" || $config['USE_LOXBERRY_MQTT'] === true) ? 'checked' : ''; ?>>
                            <span style="font-weight: 700; color: #2e7d32;"><?php echo htmlspecialchars($L['LABEL_USE_LOXBERRY_MQTT'] ?? 'Použít automatickou detekci z LoxBerry MQTT Gateway V2'); ?></span>
                        </label>
                        <div id="mqtt-auto-badge" style="margin-top: 6px; font-size: 0.85rem; color: #0284c7; display: none;">
                            ℹ️ Přihlašovací údaje jsou automaticky přebírány ze systému LoxBerry a pole níže jsou uzamčena.
                        </div>
                    </div>

                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 25px;">
                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;"><?php echo htmlspecialchars($L['LABEL_MQTT_HOST'] ?? 'MQTT Server Host'); ?>:</label>
                            <input type="text" name="mqtt_host" id="mqtt_host" value="<?php echo htmlspecialchars($config['MQTT_HOST']); ?>" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;"><?php echo htmlspecialchars($L['LABEL_MQTT_PORT'] ?? 'MQTT Server Port'); ?>:</label>
                            <input type="number" name="mqtt_port" id="mqtt_port" value="<?php echo htmlspecialchars($config['MQTT_PORT']); ?>" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;"><?php echo htmlspecialchars($L['LABEL_MQTT_USER'] ?? 'MQTT Uživatel'); ?>:</label>
                            <input type="text" name="mqtt_username" id="mqtt_username" value="<?php echo htmlspecialchars($config['MQTT_USERNAME']); ?>" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;"><?php echo htmlspecialchars($L['LABEL_MQTT_PASS'] ?? 'MQTT Heslo'); ?>:</label>
                            <input type="password" name="mqtt_password" id="mqtt_password" value="<?php echo htmlspecialchars($config['MQTT_PASSWORD']); ?>" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;"><?php echo htmlspecialchars($L['LABEL_MQTT_TOPIC'] ?? 'MQTT Root Topic'); ?>:</label>
                            <input type="text" name="mqtt_topic" value="<?php echo htmlspecialchars($config['MQTT_TOPIC']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                            <span style="font-size: 0.78rem; color: #64748b; display: block; margin-top: 3px;"><?php echo htmlspecialchars($L['HELP_MQTT_TOPIC'] ?? 'E-maily vytvoří pod-topicy, např. smtp2mqtt/kamera_zahrada.'); ?></span>
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;"><?php echo htmlspecialchars($L['LABEL_MQTT_PAYLOAD'] ?? 'MQTT Trigger Payload'); ?>:</label>
                            <input type="text" name="mqtt_payload" value="<?php echo htmlspecialchars($config['MQTT_PAYLOAD']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;"><?php echo htmlspecialchars($L['LABEL_MQTT_RESET_TIME'] ?? 'MQTT Reset Čas (sec)'); ?>:</label>
                            <input type="number" name="mqtt_reset_time" value="<?php echo htmlspecialchars($config['MQTT_RESET_TIME']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                            <span style="font-size: 0.78rem; color: #64748b; display: block; margin-top: 3px;"><?php echo htmlspecialchars($L['HELP_MQTT_RESET_TIME'] ?? 'Sekundy pro auto-reset (0 = nevypínat).'); ?></span>
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;"><?php echo htmlspecialchars($L['LABEL_MQTT_RESET_PAYLOAD'] ?? 'MQTT Reset Payload'); ?>:</label>
                            <input type="text" name="mqtt_reset_payload" value="<?php echo htmlspecialchars($config['MQTT_RESET_PAYLOAD']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>
                    </div>

                    <!-- Maintenance & Retention -->
                    <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 1rem; border-bottom: 2px solid #f1f8e9; padding-bottom: 6px;"><?php echo htmlspecialchars($L['SEC_ATTACHMENTS'] ?? '🖼️ Přílohy & Údržba'); ?></h4>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 20px;">
                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;"><?php echo htmlspecialchars($L['LABEL_CLEANUP_ATTACHMENTS'] ?? 'Retence Příloh (Dní)'); ?>:</label>
                            <input type="number" name="cleanup_attachments_days" value="<?php echo htmlspecialchars($config['CLEANUP_ATTACHMENTS_DAYS']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;"><?php echo htmlspecialchars($L['LABEL_CLEANUP_LOGS'] ?? 'Retence Logů (Dní)'); ?>:</label>
                            <input type="number" name="cleanup_logs_days" value="<?php echo htmlspecialchars($config['CLEANUP_LOGS_DAYS']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>
                    </div>

                    <div style="display: flex; gap: 25px; margin-top: 15px; align-items: center;">
                        <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                            <input type="checkbox" name="save_attachments" <?php echo ($config['SAVE_ATTACHMENTS'] === "True" || $config['SAVE_ATTACHMENTS'] === true) ? 'checked' : ''; ?>>
                            <span style="font-weight: 600; color: #334155;"><?php echo htmlspecialchars($L['LABEL_SAVE_ATTACHMENTS'] ?? 'Ukládat obrázkové přílohy z e-mailů'); ?></span>
                        </label>
                        
                        <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                            <input type="checkbox" name="debug" <?php echo ($config['DEBUG'] === "True" || $config['DEBUG'] === true) ? 'checked' : ''; ?>>
                            <span style="font-weight: 600; color: #334155;"><?php echo htmlspecialchars($L['LABEL_DEBUG'] ?? 'Ladící režim (DEBUG)'); ?></span>
                        </label>
                    </div>

                    <div style="margin-top: 25px; border-top: 1px solid #e2e8f0; padding-top: 15px; display: flex; gap: 15px; align-items: center;">
                        <button type="submit" name="save_settings" class="lox-btn-primary"><?php echo htmlspecialchars($L['BTN_SAVE'] ?? '💾 Uložit Nastavení'); ?></button>
                        <a href="?action=restart_daemon" class="lox-btn-secondary"><?php echo htmlspecialchars($L['BTN_RESTART_DAEMON'] ?? '🚀 Spustit / Restartovat Službu'); ?></a>
                    </div>
                </form>
            </div>
        </div>

        <script>
            const detectedMqtt = <?php echo json_encode($detected_mqtt); ?>;

            function toggleMqttFields() {
                const isAuto = document.getElementById('use_loxberry_mqtt').checked;
                const fields = ['mqtt_host', 'mqtt_port', 'mqtt_username', 'mqtt_password'];
                const badge = document.getElementById('mqtt-auto-badge');

                fields.forEach(id => {
                    const el = document.getElementById(id);
                    if (el) {
                        el.readOnly = isAuto;
                        el.style.backgroundColor = isAuto ? '#f1f5f9' : '#ffffff';
                        el.style.color = isAuto ? '#64748b' : '#0f172a';
                        if (isAuto && id === 'mqtt_host') el.value = detectedMqtt.MQTT_HOST;
                        if (isAuto && id === 'mqtt_port') el.value = detectedMqtt.MQTT_PORT;
                        if (isAuto && id === 'mqtt_username') el.value = detectedMqtt.MQTT_USERNAME;
                        if (isAuto && id === 'mqtt_password') el.value = detectedMqtt.MQTT_PASSWORD;
                    }
                });
                if (badge) badge.style.display = isAuto ? 'block' : 'none';
            }

            document.addEventListener('DOMContentLoaded', toggleMqttFields);
        </script>

    <?php elseif ($active_tab === 'dashboard'): ?>
        <?php
        // Read status.json written by the Python daemon
        $status_file = $lbpdatadir . "/status.json";
        $status = null;
        if (file_exists($status_file)) {
            $status = json_decode(file_get_contents($status_file), true);
        }
        ?>
        <!-- Live Dashboard Tab (Native) -->
        <div class="lox-card">
            <div class="lox-card-header">
                <h3 class="lox-card-title"><?php echo htmlspecialchars($L['TAB_DASHBOARD'] ?? '📊 Živý Dashboard'); ?></h3>
                <div style="display: flex; gap: 10px; align-items: center;">
                    <span id="dash-last-update" style="font-size: 0.82rem; color: #64748b;"></span>
                    <a href="?tab=dashboard" class="lox-btn-secondary">🔄 <?php echo htmlspecialchars($L['BTN_REFRESH'] ?? 'Obnovit'); ?></a>
                </div>
            </div>
            <div class="lox-card-body">
                <?php if (!$status): ?>
                    <div style="padding: 20px; text-align: center; color: #64748b;">
                        <p style="font-size: 1.1rem; font-weight: 600;">⏳ <?php echo htmlspecialchars($L['DASH_NO_DATA'] ?? 'Dashboard zatím nemá data.'); ?></p>
                        <p><?php echo htmlspecialchars($L['DASH_NO_DATA_DESC'] ?? 'Služba smtp2mqtt ještě nebyla spuštěna nebo nezapsala stavový soubor.'); ?></p>
                        <a href="?action=restart_daemon" class="lox-btn-primary" style="margin-top: 12px; display: inline-block;">🚀 <?php echo htmlspecialchars($L['BTN_RESTART_DAEMON'] ?? 'Spustit Službu'); ?></a>
                    </div>
                <?php else: ?>
                    <!-- Status Cards Grid -->
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px;">
                        <!-- SMTP Status -->
                        <div style="background: <?php echo ($status['smtp_connected'] ?? false) ? '#dcfce7' : '#fee2e2'; ?>; border: 1px solid <?php echo ($status['smtp_connected'] ?? false) ? '#bbf7d0' : '#fecaca'; ?>; border-radius: 8px; padding: 16px;">
                            <div style="font-size: 0.85rem; font-weight: 600; color: #64748b; margin-bottom: 4px;">📬 SMTP Server</div>
                            <div style="font-size: 1.4rem; font-weight: 800; color: <?php echo ($status['smtp_connected'] ?? false) ? '#15803d' : '#b91c1c'; ?>;" id="dash-smtp-status">
                                <?php echo ($status['smtp_connected'] ?? false) ? '🟢 Active' : '🔴 Inactive'; ?>
                            </div>
                            <div style="font-size: 0.82rem; color: #64748b; margin-top: 4px;">Port <?php echo htmlspecialchars($status['smtp_port'] ?? $config['SMTP_PORT']); ?></div>
                        </div>
                        <!-- MQTT Status -->
                        <div style="background: <?php echo ($status['mqtt_connected'] ?? false) ? '#dcfce7' : '#fee2e2'; ?>; border: 1px solid <?php echo ($status['mqtt_connected'] ?? false) ? '#bbf7d0' : '#fecaca'; ?>; border-radius: 8px; padding: 16px;">
                            <div style="font-size: 0.85rem; font-weight: 600; color: #64748b; margin-bottom: 4px;">📡 MQTT Broker</div>
                            <div style="font-size: 1.4rem; font-weight: 800; color: <?php echo ($status['mqtt_connected'] ?? false) ? '#15803d' : '#b91c1c'; ?>;" id="dash-mqtt-status">
                                <?php echo ($status['mqtt_connected'] ?? false) ? '🟢 Connected' : '🔴 Disconnected'; ?>
                            </div>
                            <div style="font-size: 0.82rem; color: #64748b; margin-top: 4px;"><?php echo htmlspecialchars(($status['mqtt_host'] ?? 'localhost') . ':' . ($status['mqtt_port'] ?? '1883')); ?></div>
                        </div>
                        <!-- Uptime -->
                        <div style="background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 8px; padding: 16px;">
                            <div style="font-size: 0.85rem; font-weight: 600; color: #64748b; margin-bottom: 4px;">⏱️ Uptime</div>
                            <div style="font-size: 1.4rem; font-weight: 800; color: #0369a1;" id="dash-uptime">
                                <?php echo htmlspecialchars($status['uptime_formatted'] ?? '—'); ?>
                            </div>
                            <div style="font-size: 0.82rem; color: #64748b; margin-top: 4px;">v<?php echo htmlspecialchars($status['version'] ?? VERSION); ?></div>
                        </div>
                        <!-- Messages Processed -->
                        <div style="background: #faf5ff; border: 1px solid #e9d5ff; border-radius: 8px; padding: 16px;">
                            <div style="font-size: 0.85rem; font-weight: 600; color: #64748b; margin-bottom: 4px;">📨 Zpracováno zpráv</div>
                            <div style="font-size: 1.4rem; font-weight: 800; color: #7e22ce;" id="dash-msg-count">
                                <?php echo htmlspecialchars($status['processed_messages_count'] ?? '0'); ?>
                            </div>
                            <div style="font-size: 0.82rem; color: #64748b; margin-top: 4px;">
                                <?php echo ($status['last_publish_time'] ?? null) ? 'Poslední: ' . htmlspecialchars($status['last_publish_time']) : 'Zatím žádné'; ?>
                            </div>
                        </div>
                    </div>

                    <!-- Update Check -->
                    <?php if (!empty($status['update_available']) && $status['update_available']): ?>
                        <div style="background: #fffbeb; border: 1px solid #fef3c7; border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; display: flex; align-items: center; gap: 10px;">
                            <span style="font-size: 1.2rem;">🆕</span>
                            <div>
                                <strong style="color: #b45309;"><?php echo htmlspecialchars($L['DASH_UPDATE_AVAILABLE'] ?? 'Nová verze je dostupná!'); ?></strong>
                                <span style="color: #92400e; font-size: 0.9rem; margin-left: 8px;">v<?php echo htmlspecialchars($status['latest_version'] ?? ''); ?></span>
                            </div>
                        </div>
                    <?php endif; ?>

                    <!-- Recent Actions Table -->
                    <?php if (!empty($status['recent_actions'])): ?>
                        <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 1rem; border-bottom: 2px solid #f1f8e9; padding-bottom: 6px;">📋 <?php echo htmlspecialchars($L['DASH_RECENT_ACTIONS'] ?? 'Poslední události'); ?></h4>
                        <div style="overflow-x: auto;">
                            <table style="width: 100%; border-collapse: collapse; font-size: 0.88rem;">
                                <thead>
                                    <tr style="background: #f8fafc; border-bottom: 2px solid #e2e8f0;">
                                        <th style="text-align: left; padding: 10px 12px; font-weight: 700; color: #475569;">Čas</th>
                                        <th style="text-align: left; padding: 10px 12px; font-weight: 700; color: #475569;">Typ</th>
                                        <th style="text-align: left; padding: 10px 12px; font-weight: 700; color: #475569;">Odesílatel</th>
                                        <th style="text-align: left; padding: 10px 12px; font-weight: 700; color: #475569;">Topic</th>
                                        <th style="text-align: left; padding: 10px 12px; font-weight: 700; color: #475569;">Payload</th>
                                        <th style="text-align: left; padding: 10px 12px; font-weight: 700; color: #475569;">Status</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <?php foreach ($status['recent_actions'] as $action): ?>
                                        <tr style="border-bottom: 1px solid #f1f5f9;">
                                            <td style="padding: 8px 12px; color: #64748b; font-family: monospace; font-size: 0.82rem; white-space: nowrap;"><?php echo htmlspecialchars($action['timestamp'] ?? ''); ?></td>
                                            <td style="padding: 8px 12px;">
                                                <span class="lox-badge-info"><?php echo htmlspecialchars($action['type'] ?? ''); ?></span>
                                            </td>
                                            <td style="padding: 8px 12px; font-family: monospace; font-size: 0.85rem;"><?php echo htmlspecialchars($action['sender'] ?? ''); ?></td>
                                            <td style="padding: 8px 12px; font-family: monospace; font-size: 0.85rem; color: #0369a1;"><?php echo htmlspecialchars($action['topic'] ?? ''); ?></td>
                                            <td style="padding: 8px 12px; font-weight: 600;"><?php echo htmlspecialchars($action['payload'] ?? ''); ?></td>
                                            <td style="padding: 8px 12px;">
                                                <?php
                                                $st = $action['status'] ?? 'UNKNOWN';
                                                $stClass = ($st === 'SUCCESS') ? 'lox-badge-success' : 'lox-badge-danger';
                                                ?>
                                                <span class="<?php echo $stClass; ?>"><?php echo htmlspecialchars($st); ?></span>
                                            </td>
                                        </tr>
                                    <?php endforeach; ?>
                                </tbody>
                            </table>
                        </div>
                    <?php else: ?>
                        <div style="text-align: center; padding: 20px; color: #94a3b8; font-style: italic;">
                            <?php echo htmlspecialchars($L['DASH_NO_EVENTS'] ?? 'Zatím nebyly zaznamenány žádné události.'); ?>
                        </div>
                    <?php endif; ?>
                <?php endif; ?>
            </div>
        </div>

        <script>
            // Auto-refresh dashboard every 5 seconds via AJAX
            function refreshDashboard() {
                fetch('?tab=dashboard&_ajax=1')
                    .then(r => r.text())
                    .then(html => {
                        // Only update if page is still on dashboard tab
                        if (window.location.search.includes('tab=dashboard')) {
                            const parser = new DOMParser();
                            const doc = parser.parseFromString(html, 'text/html');
                            const newContent = doc.querySelector('.lox-card-body');
                            const currentContent = document.querySelector('.lox-card-body');
                            if (newContent && currentContent) {
                                currentContent.innerHTML = newContent.innerHTML;
                            }
                            const updateEl = document.getElementById('dash-last-update');
                            if (updateEl) updateEl.textContent = 'Aktualizováno: ' + new Date().toLocaleTimeString('cs-CZ');
                        }
                    })
                    .catch(() => {});
            }
            setInterval(refreshDashboard, 5000);
            // Show initial timestamp
            const initEl = document.getElementById('dash-last-update');
            if (initEl) initEl.textContent = 'Aktualizováno: ' + new Date().toLocaleTimeString('cs-CZ');
        </script>

    <?php elseif ($active_tab === 'logs'): ?>
        <!-- System Logs Tab -->
        <div class="lox-card">
            <div class="lox-card-header">
                <div>
                    <h3 class="lox-card-title"><?php echo htmlspecialchars($L['TAB_LOGS'] ?? '📋 Prohlížeč Logů (smtp2mqtt.log)'); ?></h3>
                </div>
                <div style="display: flex; gap: 10px;">
                    <a href="?tab=logs" class="lox-btn-secondary"><?php echo htmlspecialchars($L['BTN_REFRESH'] ?? '🔄 Obnovit'); ?></a>
                    <a href="?action=restart_daemon" class="lox-btn-secondary" style="color: #0284c7;"><?php echo htmlspecialchars($L['BTN_RESTART_DAEMON'] ?? '🚀 Spustit Službu'); ?></a>
                    <?php if (file_exists($log_file)): ?>
                        <a href="?action=download_log" class="lox-btn-secondary"><?php echo htmlspecialchars($L['BTN_DOWNLOAD_LOG'] ?? '📥 Stáhnout Log'); ?></a>
                        <a href="?action=clear_log" onclick="return confirm('Opravdu chcete vyčistit soubor logů?');" class="lox-btn-secondary" style="color: #dc2626;"><?php echo htmlspecialchars($L['BTN_CLEAR_LOG'] ?? '🧹 Vyčistit Log'); ?></a>
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
                    echo '<div style="margin-bottom: 12px; font-weight: 600; color: #d97706; background: #fffbebf; padding: 12px 16px; border-radius: 6px; border: 1px solid #fef3c7;">⚠️ Soubor logů smtp2mqtt.log zatím neobsahuje žádná data.<br><br><a href="?action=restart_daemon" class="lox-btn-primary">🚀 Spustit / Restartovat Službu smtp2mqtt</a></div>';
                    echo '<div class="log-viewer-box" id="log-box">Služba se spouští. Po prvním zapsání události se zde zobrazí živé záznamy.</div>';
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

    <?php elseif ($active_tab === 'help'): ?>
        <!-- In-App Help & Guide Tab -->
        <div class="lox-card">
            <div class="lox-card-header">
                <h3 class="lox-card-title"><?php echo htmlspecialchars($L['HELP_TITLE'] ?? '📖 Jak používat smtp2mqtt v LoxBerry'); ?></h3>
            </div>
            <div class="lox-card-body" style="line-height: 1.6; color: #334155; font-size: 0.95rem;">
                <p style="font-size: 1.05rem; margin-top: 0; color: #1e293b; background: #f8fafc; padding: 12px 16px; border-radius: 6px; border-left: 4px solid #6fb738;">
                    <?php echo htmlspecialchars($L['HELP_INTRO'] ?? 'Plugin smtp2mqtt funguje jako lehký SMTP server, který zachytává e-mailové notifikace o detekci pohybu z IP kamer a okamžitě je převádí na MQTT zprávy a triggery pro Loxone / Smart Home.'); ?>
                </p>

                <h4 style="color: #2e7d32; margin-top: 25px; font-size: 1.1rem; border-bottom: 2px solid #e2e8f0; padding-bottom: 6px;">
                    <?php echo htmlspecialchars($L['HELP_CAM_TITLE'] ?? '🎥 Návod k nastavení IP kamer (Hikvision, Dahua, Reolink, Axis)'); ?>
                </h4>
                <ul style="padding-left: 20px; line-height: 1.8;">
                    <li><strong><?php echo htmlspecialchars($L['HELP_CAM_STEP1'] ?? '1. Otevřete webové rozhraní vaší IP kamery v sekci Network -> Email.'); ?></strong></li>
                    <li><strong><?php echo htmlspecialchars($L['HELP_CAM_STEP2'] ?? '2. SMTP Server: Zadejte IP adresu vašeho LoxBerry (např. 192.168.1.100).'); ?></strong></li>
                    <li><strong><?php echo htmlspecialchars($L['HELP_CAM_STEP3'] ?? '3. SMTP Port: Zadejte nastavený SMTP port (výchozí: 1025).'); ?></strong></li>
                    <li><strong><?php echo htmlspecialchars($L['HELP_CAM_STEP4'] ?? '4. Autentizace / SSL / TLS: Vypněte SSL/TLS i autentizaci (login a heslo).'); ?></strong></li>
                    <li><strong><?php echo htmlspecialchars($L['HELP_CAM_STEP5'] ?? '5. Odesílatel (Sender): Zadejte identifikátor kamery, např. kamera.zahrada@domov.local. Z této adresy se automaticky vytvoří MQTT topic: smtp2mqtt/kamera_zahrada-domov_local.'); ?></strong></li>
                </ul>

                <h4 style="color: #2e7d32; margin-top: 25px; font-size: 1.1rem; border-bottom: 2px solid #e2e8f0; padding-bottom: 6px;">
                    <?php echo htmlspecialchars($L['HELP_LOXONE_TITLE'] ?? '🏠 Integrace s Loxone Config'); ?>
                </h4>
                <p><?php echo htmlspecialchars($L['HELP_LOXONE_DESC'] ?? 'V Loxone Config přidejte MQTT Text In Subscriptions pro topic smtp2mqtt/#. Příklad: smtp2mqtt/kamera_zahrada-domov_local změní hodnotu na ON při detekci pohybu a po 10 sekundách se vrátí na OFF.'); ?></p>

                <h4 style="color: #b91c1c; margin-top: 25px; font-size: 1.1rem; border-bottom: 2px solid #e2e8f0; padding-bottom: 6px;">
                    <?php echo htmlspecialchars($L['HELP_SEC_TITLE'] ?? '🛡️ Bezpečnostní doporučení'); ?>
                </h4>
                <p style="background: #fef2f2; padding: 12px 16px; border-radius: 6px; border: 1px solid #fecaca; color: #991b1b;">
                    <?php echo htmlspecialchars($L['HELP_SEC_DESC'] ?? 'Službu SMTP nikdy nevystavujte přímo do veřejného internetu bez VPN. Pro zamezení spamu v lokální síti použijte pole ALLOWED_IPS pro omezení přístupu pouze z IP adres vašich kamer.'); ?>
                </p>
            </div>
        </div>
    <?php endif; ?>

</div>

<?php
LBWeb::lbfooter();
?>
