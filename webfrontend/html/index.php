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
    "MQTT_TOPIC" => "smtp2mqtt",
    "MQTT_RESET_TIME" => 10,
    "SAVE_ATTACHMENTS" => "True",
    "DEBUG" => "False"
];

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
    $config['MQTT_TOPIC'] = trim($_POST['mqtt_topic'] ?? 'smtp2mqtt');
    $config['MQTT_RESET_TIME'] = intval($_POST['mqtt_reset_time'] ?? 10);
    $config['SAVE_ATTACHMENTS'] = isset($_POST['save_attachments']) ? "True" : "False";
    $config['DEBUG'] = isset($_POST['debug']) ? "True" : "False";

    if (!file_exists($config_dir)) {
        mkdir($config_dir, 0755, true);
    }

    if (file_put_contents($config_file, json_encode($config, JSON_PRETTY_PRINT))) {
        $message = "Konfigurace byla úspěšně uložena. Restartuji službu smtp2mqtt...";
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
        <div style="padding: 12px 16px; margin-bottom: 20px; border-radius: 6px; background-color: <?php echo $message_type === 'success' ? '#d4edda' : '#f8d7da'; ?>; color: <?php echo $message_type === 'success' ? '#155724' : '#721c24'; ?>; border: 1px solid <?php echo $message_type === 'success' ? '#c3e6cb' : '#f5c6cb'; ?>;">
            <?php echo htmlspecialchars($message); ?>
        </div>
    <?php endif; ?>

    <!-- Settings Panel -->
    <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; margin-bottom: 25px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
        <h3 style="margin-top: 0; margin-bottom: 15px; color: #1e293b; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px;">⚙️ Nastavení pluginu smtp2mqtt</h3>
        
        <form method="post" action="">
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px;">
                <div>
                    <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155;">Web UI Port:</label>
                    <input type="number" name="web_port" value="<?php echo htmlspecialchars($config['WEB_PORT']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                </div>
                
                <div>
                    <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155;">SMTP Port:</label>
                    <input type="number" name="smtp_port" value="<?php echo htmlspecialchars($config['SMTP_PORT']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                </div>
                
                <div>
                    <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155;">MQTT Výchozí Téma (Topic):</label>
                    <input type="text" name="mqtt_topic" value="<?php echo htmlspecialchars($config['MQTT_TOPIC']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                </div>

                <div>
                    <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155;">MQTT Reset Čas (sec):</label>
                    <input type="number" name="mqtt_reset_time" value="<?php echo htmlspecialchars($config['MQTT_RESET_TIME']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                </div>
            </div>

            <div style="display: flex; gap: 20px; margin-top: 15px; align-items: center;">
                <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                    <input type="checkbox" name="save_attachments" <?php echo ($config['SAVE_ATTACHMENTS'] === "True" || $config['SAVE_ATTACHMENTS'] === true) ? 'checked' : ''; ?>>
                    <span style="font-weight: 500; color: #334155;">Ukládat přílohy (obrázky)</span>
                </label>
                
                <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                    <input type="checkbox" name="debug" <?php echo ($config['DEBUG'] === "True" || $config['DEBUG'] === true) ? 'checked' : ''; ?>>
                    <span style="font-weight: 500; color: #334155;">Ladící režim (DEBUG)</span>
                </label>
            </div>

            <div style="margin-top: 20px;">
                <button type="submit" name="save_settings" style="background: #2563eb; color: #ffffff; border: none; padding: 10px 20px; border-radius: 5px; font-weight: bold; cursor: pointer;">💾 Uložit & Restartovat Službu</button>
            </div>
        </form>
    </div>

    <!-- Live Dashboard Panel -->
    <div style="display: flex; align-items: center; justify-content: space-between; background: #1a1a2e; color: #fff; padding: 15px 20px; border-radius: 8px 8px 0 0;">
        <div>
            <h2 style="margin: 0; font-size: 1.3rem; color: #e94560;">📧 smtp2mqtt Live Dashboard</h2>
            <p style="margin: 4px 0 0 0; font-size: 0.85rem; color: #a0a0b0;">Živý přehled stavu a přijatých zpráv na portu <?php echo htmlspecialchars($port); ?></p>
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

