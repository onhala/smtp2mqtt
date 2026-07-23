<?php
require_once "loxberry_web.php";
require_once "loxberry_system.php";

// Read LoxBerry language file if present
$L = LBSystem::readlanguage("language.ini");

// Define paths
$config_dir = $lbpconfigdir;
$config_file = $config_dir . "/config.json";

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
if (file_exists($lb_mqtt_file)) {
    $mqtt_data = json_decode(file_get_contents($lb_mqtt_file), true);
    $main = $mqtt_data['Main'] ?? $mqtt_data['Credentials'] ?? $mqtt_data ?? [];
    if (!empty($main['brokeraddress']) || !empty($main['mqttserver'])) {
        $defaults['MQTT_HOST'] = $main['brokeraddress'] ?? $main['mqttserver'] ?? "localhost";
        $defaults['MQTT_PORT'] = intval($main['brokerport'] ?? $main['mqttport'] ?? 1883);
        $defaults['MQTT_USERNAME'] = $main['brokeruser'] ?? $main['mqttuser'] ?? "";
        $defaults['MQTT_PASSWORD'] = $main['brokerpass'] ?? $main['mqttpass'] ?? "";
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
    $config['USE_LOXBERRY_MQTT'] = isset($_POST['use_loxberry_mqtt']) ? "True" : "False";
    $config['MQTT_HOST'] = trim($_POST['mqtt_host'] ?? 'localhost');
    $config['MQTT_PORT'] = intval($_POST['mqtt_port'] ?? 1883);
    $config['MQTT_USERNAME'] = trim($_POST['mqtt_username'] ?? '');
    $config['MQTT_PASSWORD'] = $_POST['mqtt_password'] ?? '';
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
        // Restart systemd service
        exec("sudo systemctl restart smtp2mqtt.service 2>&1", $output, $return_var);
    } else {
        $message = "Chyba při zápisu do konfiguračního souboru!";
        $message_type = "danger";
    }
}

// Output LoxBerry Header
LBWeb::lbheader("smtp2mqtt Bridge", "https://github.com/onhala/smtp2mqtt", "smtp2mqtt");

// Determine Dashboard URL dynamically based on configured WEB_PORT
$port = $config['WEB_PORT'];
$host = parse_url("http://" . $_SERVER['HTTP_HOST'], PHP_URL_HOST);
$dashboard_url = "http://" . $host . ":" . $port;

?>
<div style="padding: 15px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
    
    <?php if ($message): ?>
        <div style="padding: 12px 16px; margin-bottom: 20px; border-radius: 6px; background-color: <?php echo $message_type === 'success' ? '#d4edda' : '#f8d7da'; ?>; color: <?php echo $message_type === 'success' ? '#155724' : '#721c24'; ?>; border: 1px solid <?php echo $message_type === 'success' ? '#c3e6cb' : '#f5c6cb'; ?>; font-weight: 500;">
            <?php echo htmlspecialchars($message); ?>
        </div>
    <?php endif; ?>

    <!-- Settings Panel -->
    <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; margin-bottom: 25px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
        <h3 style="margin-top: 0; margin-bottom: 15px; color: #1e293b; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px;">⚙️ Nastavení pluginu smtp2mqtt</h3>
        
        <form method="post" action="">
            <!-- Network & Gateway Ports -->
            <h4 style="margin: 15px 0 10px 0; color: #334155; font-size: 1rem;">🌐 Síťová Rozhraní</h4>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 20px;">
                <div>
                    <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #475569; font-size: 0.9rem;">Web Dashboard Port:</label>
                    <input type="number" name="web_port" value="<?php echo htmlspecialchars($config['WEB_PORT']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                </div>
                
                <div>
                    <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #475569; font-size: 0.9rem;">SMTP Server Port:</label>
                    <input type="number" name="smtp_port" value="<?php echo htmlspecialchars($config['SMTP_PORT']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                </div>
            </div>

            <!-- MQTT Broker Settings -->
            <h4 style="margin: 15px 0 10px 0; color: #334155; font-size: 1rem;">📡 MQTT Broker & Témata</h4>
            <div style="margin-bottom: 15px;">
                <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                    <input type="checkbox" name="use_loxberry_mqtt" <?php echo ($config['USE_LOXBERRY_MQTT'] === "True" || $config['USE_LOXBERRY_MQTT'] === true) ? 'checked' : ''; ?>>
                    <span style="font-weight: 600; color: #2563eb;">Auto-detect z LoxBerry MQTT Gateway V2</span>
                </label>
            </div>

            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 20px;">
                <div>
                    <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #475569; font-size: 0.9rem;">MQTT Server Host:</label>
                    <input type="text" name="mqtt_host" value="<?php echo htmlspecialchars($config['MQTT_HOST']); ?>" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                </div>

                <div>
                    <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #475569; font-size: 0.9rem;">MQTT Server Port:</label>
                    <input type="number" name="mqtt_port" value="<?php echo htmlspecialchars($config['MQTT_PORT']); ?>" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                </div>

                <div>
                    <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #475569; font-size: 0.9rem;">MQTT Uživatel:</label>
                    <input type="text" name="mqtt_username" value="<?php echo htmlspecialchars($config['MQTT_USERNAME']); ?>" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                </div>

                <div>
                    <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #475569; font-size: 0.9rem;">MQTT Heslo:</label>
                    <input type="password" name="mqtt_password" value="<?php echo htmlspecialchars($config['MQTT_PASSWORD']); ?>" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                </div>

                <div>
                    <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #475569; font-size: 0.9rem;">MQTT Root Topic:</label>
                    <input type="text" name="mqtt_topic" value="<?php echo htmlspecialchars($config['MQTT_TOPIC']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                </div>

                <div>
                    <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #475569; font-size: 0.9rem;">MQTT Trigger Payload:</label>
                    <input type="text" name="mqtt_payload" value="<?php echo htmlspecialchars($config['MQTT_PAYLOAD']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                </div>

                <div>
                    <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #475569; font-size: 0.9rem;">MQTT Reset Čas (sec):</label>
                    <input type="number" name="mqtt_reset_time" value="<?php echo htmlspecialchars($config['MQTT_RESET_TIME']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                </div>

                <div>
                    <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #475569; font-size: 0.9rem;">MQTT Reset Payload:</label>
                    <input type="text" name="mqtt_reset_payload" value="<?php echo htmlspecialchars($config['MQTT_RESET_PAYLOAD']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                </div>
            </div>

            <!-- Maintenance & Media Retention -->
            <h4 style="margin: 15px 0 10px 0; color: #334155; font-size: 1rem;">🧹 Přílohy & Údržba</h4>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 20px;">
                <div>
                    <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #475569; font-size: 0.9rem;">Retence Příloh (Dní):</label>
                    <input type="number" name="cleanup_attachments_days" value="<?php echo htmlspecialchars($config['CLEANUP_ATTACHMENTS_DAYS']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                </div>

                <div>
                    <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #475569; font-size: 0.9rem;">Retence Logů (Dní):</label>
                    <input type="number" name="cleanup_logs_days" value="<?php echo htmlspecialchars($config['CLEANUP_LOGS_DAYS']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                </div>
            </div>

            <div style="display: flex; gap: 25px; margin-top: 15px; align-items: center;">
                <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                    <input type="checkbox" name="save_attachments" <?php echo ($config['SAVE_ATTACHMENTS'] === "True" || $config['SAVE_ATTACHMENTS'] === true) ? 'checked' : ''; ?>>
                    <span style="font-weight: 500; color: #334155;">Ukládat obrázkové přílohy z e-mailů</span>
                </label>
                
                <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                    <input type="checkbox" name="debug" <?php echo ($config['DEBUG'] === "True" || $config['DEBUG'] === true) ? 'checked' : ''; ?>>
                    <span style="font-weight: 500; color: #334155;">Ladící režim (DEBUG)</span>
                </label>
            </div>

            <div style="margin-top: 25px; border-top: 1px solid #e2e8f0; padding-top: 15px;">
                <button type="submit" name="save_settings" style="background: #2563eb; color: #ffffff; border: none; padding: 12px 24px; border-radius: 6px; font-weight: bold; font-size: 0.95rem; cursor: pointer;">💾 Uložit & Restartovat Službu</button>
            </div>
        </form>
    </div>

    <!-- Live Dashboard Panel -->
    <div style="display: flex; align-items: center; justify-content: space-between; background: #1a1a2e; color: #fff; padding: 15px 20px; border-radius: 8px 8px 0 0;">
        <div>
            <h2 style="margin: 0; font-size: 1.3rem; color: #e94560;">📧 smtp2mqtt Live Dashboard</h2>
            <p style="margin: 4px 0 0 0; font-size: 0.85rem; color: #a0a0b0;">Živý přehled stavu, připojení a přijatých zpráv na portu <?php echo htmlspecialchars($port); ?></p>
        </div>
        <div>
            <a href="<?php echo $dashboard_url; ?>" target="_blank" style="background: #e94560; color: #fff; text-decoration: none; padding: 8px 16px; border-radius: 5px; font-weight: bold; font-size: 0.85rem;">Otevřít samostatně ↗</a>
        </div>
    </div>
    
    <iframe src="<?php echo $dashboard_url; ?>" style="width: 100%; height: 750px; border: 1px solid #1a1a2e; border-top: none; border-radius: 0 0 8px 8px; background: #ffffff;"></iframe>
</div>
<?php
LBWeb::lbfooter();
?>


