<?php
require_once "loxberry_web.php";

// Read LoxBerry language file if present
$L = LBSystem::readlanguage("language.ini");

// Output LoxBerry Header
LBWeb::lbheader("smtp2mqtt Bridge", "https://github.com/onhala/smtp2mqtt", "smtp2mqtt");

// Determine Dashboard URL (defaults to port 8080 or custom env)
$port = getenv("SMTP2MQTT_WEB_PORT") ?: "8080";
$host = parse_url("http://" . $_SERVER['HTTP_HOST'], PHP_URL_HOST);
$dashboard_url = "http://" . $host . ":" . $port;

?>
<div style="padding: 15px; font-family: sans-serif;">
    <div style="display: flex; align-items: center; justify-content: space-between; background: #1a1a2e; color: #fff; padding: 15px 20px; border-radius: 8px; margin-bottom: 20px;">
        <div>
            <h2 style="margin: 0; font-size: 1.5rem; color: #e94560;">📧 smtp2mqtt Live Dashboard</h2>
            <p style="margin: 5px 0 0 0; font-size: 0.9rem; color: #a0a0b0;">SMTP-to-MQTT Bridge & LoxBerry Integration</p>
        </div>
        <div>
            <a href="<?php echo $dashboard_url; ?>" target="_blank" style="background: #e94560; color: #fff; text-decoration: none; padding: 8px 16px; border-radius: 5px; font-weight: bold; font-size: 0.85rem;">Otevřít v novém okno ↗</a>
        </div>
    </div>
    
    <iframe src="<?php echo $dashboard_url; ?>" style="width: 100%; height: 750px; border: 1px solid #ddd; border-radius: 8px; background: #ffffff;"></iframe>
</div>
<?php
LBWeb::lbfooter();
?>
