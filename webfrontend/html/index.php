<?php
require_once "loxberry_web.php";
require_once "loxberry_system.php";

// Start session if not started for CSRF security
if (session_status() === PHP_SESSION_NONE) {
    @session_start();
}
if (empty($_SESSION['csrf_token'])) {
    $_SESSION['csrf_token'] = bin2hex(random_bytes(16));
}
$csrf_token = $_SESSION['csrf_token'];

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

// Plugin version dynamically from LoxBerry config
$plugin_version = $lbpconfig['PLUGIN']['VERSION'] ?? '1.8.26';

// Define paths safely with fallbacks for LoxBerry environment
$lbpconfigdir = !empty($lbpconfigdir) ? $lbpconfigdir : (defined('LBPCONFIGDIR') ? LBPCONFIGDIR : "/opt/loxberry/config/plugins/smtp2mqtt");
$lbplogdir = !empty($lbplogdir) ? $lbplogdir : (defined('LBPLOGDIR') ? LBPLOGDIR : "/opt/loxberry/log/plugins/smtp2mqtt");
$lbpbindir = !empty($lbpbindir) ? $lbpbindir : (defined('LBPBINDIR') ? LBPBINDIR : "/opt/loxberry/bin/plugins/smtp2mqtt");
$lbpdatadir = !empty($lbpdatadir) ? $lbpdatadir : (defined('LBPDATADIR') ? LBPDATADIR : "/opt/loxberry/data/plugins/smtp2mqtt");
$lbsysconfigdir = !empty($lbsysconfigdir) ? $lbsysconfigdir : (defined('LBSYSCONFIGDIR') ? LBSYSCONFIGDIR : "/opt/loxberry/config/system");

$config_dir = $lbpconfigdir;
$config_file = $config_dir . "/config.json";
$log_candidates = [
    $lbplogdir . "/smtp2mqtt.log",
    "/opt/loxberry/log/plugins/smtp2mqtt/smtp2mqtt.log",
    "/opt/loxberry/log/plugins/smtp2mqtt.log",
    $lbpdatadir . "/smtp2mqtt.log",
    __DIR__ . "/smtp2mqtt.log"
];
$log_file = $lbplogdir . "/smtp2mqtt.log";
foreach ($log_candidates as $l_cand) {
    if (file_exists($l_cand)) {
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
    "MQTT_RESET_TIME" => 200,
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
    if (is_array($mqtt_data)) {
        $main = $mqtt_data['Main'] ?? [];
        $creds = $mqtt_data['Credentials'] ?? [];
        
        $host = $main['brokeraddress'] ?? $main['mqttserver'] ?? $mqtt_data['brokeraddress'] ?? "localhost";
        $port = intval($main['brokerport'] ?? $main['mqttport'] ?? $mqtt_data['brokerport'] ?? 1883);
        $user = $creds['brokeruser'] ?? $main['brokeruser'] ?? $mqtt_data['brokeruser'] ?? "";
        $pass = $creds['brokerpass'] ?? $main['brokerpass'] ?? $mqtt_data['brokerpass'] ?? "";

        $detected_mqtt['MQTT_HOST'] = $host;
        $detected_mqtt['MQTT_PORT'] = $port;
        $detected_mqtt['MQTT_USERNAME'] = $user;
        $detected_mqtt['MQTT_PASSWORD'] = $pass;
    }
}

$lb_mqtt_ini = $lbsysconfigdir . "/mqttgateway.ini";
if ((empty($detected_mqtt['MQTT_USERNAME']) || empty($detected_mqtt['MQTT_PASSWORD'])) && file_exists($lb_mqtt_ini)) {
    $ini_data = @parse_ini_file($lb_mqtt_ini, true);
    if (is_array($ini_data)) {
        $main = $ini_data['Main'] ?? $ini_data['MQTT'] ?? [];
        $creds = $ini_data['Credentials'] ?? $ini_data['Main'] ?? [];
        if (!empty($main['brokeraddress'])) $detected_mqtt['MQTT_HOST'] = $main['brokeraddress'];
        if (!empty($main['brokerport'])) $detected_mqtt['MQTT_PORT'] = intval($main['brokerport']);
        if (!empty($creds['brokeruser'])) $detected_mqtt['MQTT_USERNAME'] = $creds['brokeruser'];
        if (!empty($creds['brokerpass'])) $detected_mqtt['MQTT_PASSWORD'] = $creds['brokerpass'];
    }
}

// Fallback to official LoxBerry IO SDK function if available
if (!function_exists('mqtt_connectiondetails')) {
    @include_once "loxberry_io.php";
}
if (function_exists('mqtt_connectiondetails')) {
    $mcreds = mqtt_connectiondetails();
    if (is_array($mcreds)) {
        if (!empty($mcreds['brokerhost'])) $detected_mqtt['MQTT_HOST'] = $mcreds['brokerhost'];
        if (!empty($mcreds['brokerport'])) $detected_mqtt['MQTT_PORT'] = intval($mcreds['brokerport']);
        if (!empty($mcreds['brokeruser'])) $detected_mqtt['MQTT_USERNAME'] = $mcreds['brokeruser'];
        if (!empty($mcreds['brokerpass'])) $detected_mqtt['MQTT_PASSWORD'] = $mcreds['brokerpass'];
    }
}


$defaults['MQTT_HOST'] = $detected_mqtt['MQTT_HOST'];
$defaults['MQTT_PORT'] = $detected_mqtt['MQTT_PORT'];
$defaults['MQTT_USERNAME'] = $detected_mqtt['MQTT_USERNAME'];
$defaults['MQTT_PASSWORD'] = $detected_mqtt['MQTT_PASSWORD'];

// Read current config
$config = $defaults;
if (file_exists($config_file)) {
    $json_content = file_get_contents($config_file);
    $saved_config = json_decode($json_content, true);
    if (is_array($saved_config)) {
        $config = array_merge($defaults, $saved_config);
    }
}

if (!isset($config['FIREWALL_RULES']) || !is_array($config['FIREWALL_RULES'])) {
    $rules = [];
    $allowed_str = $config['ALLOWED_IPS'] ?? '';
    if (!empty($allowed_str)) {
        $parts = explode(',', $allowed_str);
        foreach ($parts as $p) {
            $p = trim($p);
            if (!empty($p)) {
                $label = '';
                if ($p === '192.168.0.0/16') $label = 'Privátní LAN 192.168.x.x';
                elseif ($p === '10.0.0.0/8') $label = 'Privátní LAN 10.x.x.x';
                elseif ($p === '172.16.0.0/12') $label = 'Privátní LAN 172.16.x.x';
                elseif ($p === '127.0.0.1') $label = 'Localhost';
                elseif ($p === '*') $label = 'Bez omezení (Všechny IP)';
                $rules[] = ['ip' => $p, 'label' => $label];
            }
        }
    }
    $config['FIREWALL_RULES'] = $rules;
}

// Handle Clean AJAX JSON Endpoint
if (isset($_GET['_ajax']) && $_GET['_ajax'] === 'json') {
    header('Content-Type: application/json; charset=utf-8');
    $status_candidates = [
        $lbpdatadir . "/status.json",
        "/opt/loxberry/data/plugins/smtp2mqtt/status.json",
        "/opt/loxberry/data/plugins/smtp2mqtt/data/status.json",
        $lbpconfigdir . "/status.json",
        __DIR__ . "/status.json",
        "./status.json"
    ];
    $status_file = $lbpdatadir . "/status.json";
    foreach ($status_candidates as $s_cand) {
        if (file_exists($s_cand) && filesize($s_cand) > 0) {
            $status_file = $s_cand;
            break;
        }
    }
    $status_data = file_exists($status_file) ? json_decode(file_get_contents($status_file), true) : null;
    
    $is_running = false;
    unset($pgrep_out);
    exec("pgrep -f smtp2mqtt.py", $pgrep_out);
    if (!empty($pgrep_out)) {
        $is_running = true;
    }
    
    echo json_encode([
        'is_running' => $is_running,
        'version' => $plugin_version,
        'config' => $config,
        'status' => $status_data
    ]);
    exit;
}

// Handle Actions (Start / Stop / Restart / Download / Clear / Diagnostics)
if (isset($_GET['action'])) {
    $act = $_GET['action'];

    if ($act === 'test_email') {
        header('Content-Type: application/json; charset=utf-8');
        $smtp_target_host = ($config['SMTP_HOST'] === '0.0.0.0' || empty($config['SMTP_HOST'])) ? '127.0.0.1' : $config['SMTP_HOST'];
        $smtp_target_port = intval($config['SMTP_PORT'] ?? 1025);

        $fp = @fsockopen($smtp_target_host, $smtp_target_port, $errno, $errstr, 3);
        if (!$fp) {
            echo json_encode([
                'success' => false,
                'message' => "Chyba spojení: Nelze se připojit k SMTP serveru na {$smtp_target_host}:{$smtp_target_port} ($errstr)"
            ]);
        } else {
            fgets($fp, 512);
            fputs($fp, "HELO loxberry.local\r\n");
            fgets($fp, 512);
            fputs($fp, "MAIL FROM:<kamera_test@domov.local>\r\n");
            fgets($fp, 512);
            fputs($fp, "RCPT TO:<smtp2mqtt@loxberry.local>\r\n");
            fgets($fp, 512);
            fputs($fp, "DATA\r\n");
            fgets($fp, 512);
            fputs($fp, "Subject: Diagnostic Motion Motion Test Camera\r\n\r\nDiagnostic test message sent from LoxBerry UI.\r\n.\r\n");
            fgets($fp, 512);
            fputs($fp, "QUIT\r\n");
            fclose($fp);
            echo json_encode([
                'success' => true,
                'message' => "✅ Testovací SMTP e-mail úspěšně doručen na {$smtp_target_host}:{$smtp_target_port}! Sledujte Dashboard."
            ]);
        }
        exit;
    }

    if ($act === 'test_mqtt') {
        header('Content-Type: application/json; charset=utf-8');
        
        $has_req = isset($_REQUEST['use_loxberry_mqtt']) || isset($_REQUEST['mqtt_host']);
        if ($has_req) {
            $use_lb = (($_REQUEST['use_loxberry_mqtt'] ?? '') === 'true' || ($_REQUEST['use_loxberry_mqtt'] ?? '') === '1' || ($_REQUEST['use_loxberry_mqtt'] ?? '') === 'on');
        } else {
            $use_lb = ($config['USE_LOXBERRY_MQTT'] === "True" || $config['USE_LOXBERRY_MQTT'] === true);
        }

        if ($use_lb && !empty($detected_mqtt['MQTT_HOST']) && !empty($detected_mqtt['MQTT_USERNAME'])) {
            $mqtt_host = $detected_mqtt['MQTT_HOST'];
            $mqtt_port = $detected_mqtt['MQTT_PORT'];
            $mqtt_user = $detected_mqtt['MQTT_USERNAME'];
            $mqtt_pass = $detected_mqtt['MQTT_PASSWORD'];
        } else {
            if ($has_req) {
                $mqtt_host = !empty($_REQUEST['mqtt_host']) ? trim($_REQUEST['mqtt_host']) : 'localhost';
                $mqtt_port = !empty($_REQUEST['mqtt_port']) ? intval($_REQUEST['mqtt_port']) : 1883;
                $mqtt_user = isset($_REQUEST['mqtt_username']) ? trim($_REQUEST['mqtt_username']) : '';
                $mqtt_pass = $_REQUEST['mqtt_password'] ?? '';
            } else {
                $mqtt_host = !empty($config['MQTT_HOST']) ? $config['MQTT_HOST'] : ($detected_mqtt['MQTT_HOST'] ?? 'localhost');
                $mqtt_port = intval(!empty($config['MQTT_PORT']) ? $config['MQTT_PORT'] : ($detected_mqtt['MQTT_PORT'] ?? 1883));
                $mqtt_user = $config['MQTT_USERNAME'] ?? '';
                $mqtt_pass = $config['MQTT_PASSWORD'] ?? '';
            }
        }


        $fp = @fsockopen($mqtt_host, $mqtt_port, $errno, $errstr, 3);
        if (!$fp) {
            echo json_encode([
                'success' => false,
                'message' => "Chyba TCP spojení: MQTT broker na {$mqtt_host}:{$mqtt_port} neodpovídá ($errstr)"
            ]);
            exit;
        }
        stream_set_timeout($fp, 3);

        $client_id = "smtp2mqtt_test_" . rand(1000, 9999);
        $flags = 0x02; // Clean session
        if (!empty($mqtt_user)) $flags |= 0x80;
        if (!empty($mqtt_pass)) $flags |= 0x40;

        $payload = pack('n', strlen($client_id)) . $client_id;
        if (!empty($mqtt_user)) {
            $payload .= pack('n', strlen($mqtt_user)) . $mqtt_user;
        }
        if (!empty($mqtt_pass)) {
            $payload .= pack('n', strlen($mqtt_pass)) . $mqtt_pass;
        }

        $variable_header = pack('n', 4) . "MQTT" . pack('C', 4) . pack('C', $flags) . pack('n', 60);
        $connect_data = $variable_header . $payload;
        
        $rem_len = strlen($connect_data);
        $header = pack('C', 0x10);
        do {
            $digit = $rem_len % 128;
            $rem_len = (int)($rem_len / 128);
            if ($rem_len > 0) $digit |= 0x80;
            $header .= pack('C', $digit);
        } while ($rem_len > 0);

        fwrite($fp, $header . $connect_data);
        $response = fread($fp, 4);
        fclose($fp);

        if (strlen($response) < 4 || ord($response[0]) !== 0x20) {
            echo json_encode([
                'success' => false,
                'message' => "⚠️ MQTT Broker na {$mqtt_host}:{$mqtt_port} neodpověděl platným CONNACK paketem."
            ]);
            exit;
        }

        $rc = ord($response[3]);
        if ($rc === 0) {
            $user_info = !empty($mqtt_user) ? " s uživatelem '{$mqtt_user}'" : " (bez autentizace)";
            echo json_encode([
                'success' => true,
                'message' => "✅ Spojení s MQTT brokerem na {$mqtt_host}:{$mqtt_port}{$user_info} je plně funkční! Autentizace byla přijata."
            ]);
        } elseif ($rc === 4 || $rc === 5) {
            echo json_encode([
                'success' => false,
                'message' => "❌ MQTT Broker na {$mqtt_host}:{$mqtt_port} odmítl přihlašovací údaje (Kód {$rc}: Not Authorized). Zkontrolujte jméno a heslo v nastavení."
            ]);
        } else {
            echo json_encode([
                'success' => false,
                'message' => "❌ MQTT Broker na {$mqtt_host}:{$mqtt_port} odmítl spojení (Kód odmítnutí: {$rc})."
            ]);
        }
        exit;
    }

    if ($act === 'restart_daemon') {
        $daemon_runner = $lbpbindir . "/daemon/daemon";
        if (file_exists($daemon_runner)) {
            exec(escapeshellcmd($daemon_runner) . " restart > /dev/null 2>&1 &");
        } else {
            exec("pkill -f smtp2mqtt.py 2>&1");
            sleep(1);
            exec("nohup python3 " . escapeshellarg($daemon_script) . " > /dev/null 2>&1 &");
        }
        header('Location: index.php?tab=logs&started=1');
        exit;
    }

    if ($act === 'download_log' && file_exists($log_file)) {
        header('Content-Type: text/plain');
        header('Content-Disposition: attachment; filename="smtp2mqtt.log"');
        readfile($log_file);
        exit;
    }

    if ($act === 'clear_log' && file_exists($log_file)) {
        file_put_contents($log_file, "");
        header('Location: index.php?tab=logs&cleared=1');
        exit;
    }
}

// Handle Form Submission with CSRF check
$message = "";
$message_type = "success";
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['save_settings'])) {
    if (!isset($_POST['csrf_token']) || $_POST['csrf_token'] !== $_SESSION['csrf_token']) {
        $message = "Chyba zabezpečení: Neplatný CSRF token!";
        $message_type = "danger";
    } else {
        $config['WEB_PORT'] = intval($_POST['web_port'] ?? 8080);
        $config['SMTP_PORT'] = intval($_POST['smtp_port'] ?? 1025);
        $config['SMTP_HOST'] = trim($_POST['smtp_host'] ?? '0.0.0.0');
        if (isset($_POST['rule_ip']) && is_array($_POST['rule_ip'])) {
            $rules = [];
            $ip_list = [];
            $rule_ips = $_POST['rule_ip'];
            $rule_labels = $_POST['rule_label'] ?? [];
            for ($i = 0; $i < count($rule_ips); $i++) {
                $rip = trim($rule_ips[$i]);
                $rlabel = trim($rule_labels[$i] ?? '');
                if (!empty($rip)) {
                    $rules[] = ['ip' => $rip, 'label' => $rlabel];
                    $ip_list[] = $rip;
                }
            }
            $config['FIREWALL_RULES'] = $rules;
            $config['ALLOWED_IPS'] = implode(', ', $ip_list);
        } else {
            $raw_allowed = trim($_POST['allowed_ips'] ?? '192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12, 127.0.0.1');
            $config['ALLOWED_IPS'] = $raw_allowed;
            $rules = [];
            if (!empty($raw_allowed)) {
                $parts = explode(',', $raw_allowed);
                foreach ($parts as $p) {
                    $p = trim($p);
                    if (!empty($p)) {
                        $rules[] = ['ip' => $p, 'label' => ''];
                    }
                }
            }
            $config['FIREWALL_RULES'] = $rules;
        }

        $use_auto = isset($_POST['use_loxberry_mqtt']);
        $config['USE_LOXBERRY_MQTT'] = $use_auto ? "True" : "False";

        if ($use_auto) {
            $config['MQTT_HOST'] = !empty($detected_mqtt['MQTT_HOST']) ? $detected_mqtt['MQTT_HOST'] : trim($_POST['mqtt_host'] ?? 'localhost');
            $config['MQTT_PORT'] = !empty($detected_mqtt['MQTT_PORT']) ? $detected_mqtt['MQTT_PORT'] : intval($_POST['mqtt_port'] ?? 1883);
            $config['MQTT_USERNAME'] = !empty($detected_mqtt['MQTT_USERNAME']) ? $detected_mqtt['MQTT_USERNAME'] : trim($_POST['mqtt_username'] ?? '');
            $config['MQTT_PASSWORD'] = !empty($detected_mqtt['MQTT_PASSWORD']) ? $detected_mqtt['MQTT_PASSWORD'] : ($_POST['mqtt_password'] ?? '');
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

        $new_loglevel = intval($_POST['plugin_loglevel'] ?? 4);
        $config['DEBUG'] = ($new_loglevel >= 7 || isset($_POST['debug'])) ? "True" : "False";

        // Update LOGLEVEL in LoxBerry plugin.cfg
        $pcfg_file = $config_dir . "/plugin.cfg";
        if (file_exists($pcfg_file)) {
            $pcfg_content = file_get_contents($pcfg_file);
            if (preg_match('/LOGLEVEL\s*=\s*\d+/', $pcfg_content)) {
                $pcfg_content = preg_replace('/LOGLEVEL\s*=\s*\d+/', "LOGLEVEL={$new_loglevel}", $pcfg_content);
            } else if (preg_match('/\[PLUGIN\]/i', $pcfg_content)) {
                $pcfg_content = preg_replace('/\[PLUGIN\]/i', "[PLUGIN]\nLOGLEVEL={$new_loglevel}", $pcfg_content);
            }
            file_put_contents($pcfg_file, $pcfg_content);
        }


        if (!file_exists($config_dir)) {
            mkdir($config_dir, 0755, true);
        }

        if (file_put_contents($config_file, json_encode($config, JSON_PRETTY_PRINT))) {
            @chmod($config_file, 0666);
            $message = "Konfigurace uložena. Restartuji službu smtp2mqtt...";
            $daemon_runner = $lbpbindir . "/daemon/daemon";
            if (file_exists($daemon_runner)) {
                exec(escapeshellcmd($daemon_runner) . " restart > /dev/null 2>&1 &");
            } else {
                exec("pkill -f smtp2mqtt.py 2>&1");
                sleep(1);
                exec("nohup python3 " . escapeshellarg($daemon_script) . " > /dev/null 2>&1 &");
            }
        } else {
            $message = "Chyba při zápisu do konfiguračního souboru!";
            $message_type = "danger";
        }
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
LBWeb::lbheader("smtp2mqtt Bridge", "index.php?tab=help", "smtp2mqtt");


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
    .lox-btn-test {
        background: #0284c7;
        color: #ffffff;
        border: none;
        padding: 8px 14px;
        border-radius: 6px;
        font-weight: 600;
        cursor: pointer;
    }
    .lox-btn-test:hover { background: #0369a1; }
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
    .field-hint {
        font-size: 0.78rem;
        color: #64748b;
        display: block;
        margin-top: 3px;
    }
    .accordion-item {
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        margin-bottom: 10px;
        overflow: hidden;
    }
    .accordion-header {
        background: #f8fafc;
        padding: 12px 16px;
        font-weight: 700;
        cursor: pointer;
        display: flex;
        justify-content: space-between;
        align-items: center;
        color: #1e293b;
    }
    .accordion-body {
        padding: 16px;
        background: #ffffff;
        border-top: 1px solid #cbd5e1;
        display: none;
    }
    .toast-msg {
        position: fixed;
        bottom: 20px;
        right: 20px;
        z-index: 9999;
        padding: 14px 20px;
        border-radius: 8px;
        box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1);
        font-weight: 600;
        color: white;
        transition: all 0.3s ease;
    }
</style>

<div style="padding: 10px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">

    <div id="toast-container"></div>

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
            <?php echo htmlspecialchars($L['TAB_DASHBOARD'] ?? '📊 Živý Dashboard & Inspector'); ?>
        </a>
        <a href="?tab=logs" class="lox-tab-btn <?php echo $active_tab === 'logs' ? 'active' : ''; ?>">
            <?php echo htmlspecialchars($L['TAB_LOGS'] ?? '📋 Prohlížeč Logů'); ?>
        </a>
        <a href="?tab=help" class="lox-tab-btn <?php echo $active_tab === 'help' ? 'active' : ''; ?>">
            <?php echo htmlspecialchars($L['TAB_HELP'] ?? '📖 Nápověda & Kamery'); ?>
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
                <span class="lox-badge-info">v<?php echo htmlspecialchars($plugin_version); ?></span>
            </div>
            <div class="lox-card-body">
                <form method="post" action="?tab=settings" id="config-form" onsubmit="return validateConfigForm();">
                    <input type="hidden" name="csrf_token" value="<?php echo htmlspecialchars($csrf_token); ?>">

                    <!-- Network Ports & Binding -->
                    <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 1rem; border-bottom: 2px solid #f1f8e9; padding-bottom: 6px;">🌐 Nastavení Serverů (SMTP & Web)</h4>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 20px;">
                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">SMTP Server Port:</label>
                            <input type="number" name="smtp_port" id="smtp_port" value="<?php echo htmlspecialchars($config['SMTP_PORT']); ?>" required min="1" max="65535" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                            <span class="field-hint">Port pro e-mailové notifikace z kamer (výchozí: 1025).</span>
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">Vazební rozhraní (BIND_HOST):</label>
                            <select name="smtp_host" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px; background: white;">
                                <option value="0.0.0.0" <?php echo ($config['SMTP_HOST'] === '0.0.0.0') ? 'selected' : ''; ?>>0.0.0.0 (Všechna síťová rozhraní / LAN)</option>
                                <option value="127.0.0.1" <?php echo ($config['SMTP_HOST'] === '127.0.0.1') ? 'selected' : ''; ?>>127.0.0.1 (Pouze Localhost)</option>
                            </select>
                            <span class="field-hint">0.0.0.0 = Přijímá e-maily ze všech IP kamer v síti.</span>
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">Web Admin Port:</label>
                            <input type="number" name="web_port" id="web_port" value="<?php echo htmlspecialchars($config['WEB_PORT']); ?>" required min="1" max="65535" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                            <span class="field-hint">Port vestavěného stavového API a Dashboardu.</span>
                        </div>
                    </div>

                    <!-- Security & Firewall Settings -->
                    <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 1rem; border-bottom: 2px solid #f1f8e9; padding-bottom: 6px;">🔒 Bezpečnost & IP Firewall</h4>
                    <div style="margin-bottom: 25px;">
                        <?php 
                        $status_candidates = [
                            $lbpdatadir . "/status.json",
                            "/opt/loxberry/data/plugins/smtp2mqtt/status.json",
                            "/opt/loxberry/data/plugins/smtp2mqtt/data/status.json",
                            $lbpconfigdir . "/status.json",
                            __DIR__ . "/status.json",
                            "./status.json"
                        ];
                        $status_file = $lbpdatadir . "/status.json";
                        foreach ($status_candidates as $s_cand) {
                            if (file_exists($s_cand) && filesize($s_cand) > 0) {
                                $status_file = $s_cand;
                                break;
                            }
                        }
                        $status_data = file_exists($status_file) ? json_decode(file_get_contents($status_file), true) : null;
                        $recent_blocked = $status_data['recent_blocked_attempts'] ?? [];
                        if (!empty($recent_blocked)): 
                        ?>
                        <!-- Blocked Attempts Scanner Alert -->
                        <div id="blocked-attempts-alert" style="margin-bottom: 18px; padding: 14px; background: #fffbebf5; border: 1px solid #fcd34d; border-left: 4px solid #f59e0b; border-radius: 8px;">
                            <div style="font-weight: 700; color: #92400e; font-size: 0.92rem; margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                                <span>⚠️ Detekována odmítnutá SMTP spojení z neoprávněných IP adres:</span>
                            </div>
                            <div style="display: flex; flex-wrap: wrap; gap: 10px; align-items: center;">
                                <?php foreach ($recent_blocked as $blocked): ?>
                                    <div style="display: flex; align-items: center; gap: 8px; background: white; border: 1px solid #fde68a; padding: 6px 12px; border-radius: 6px; font-size: 0.88rem;">
                                        <span style="font-family: monospace; font-weight: 700; color: #b45309;"><?php echo htmlspecialchars($blocked['ip']); ?></span>
                                        <span style="color: #92400e; font-size: 0.8rem;">(<?php echo intval($blocked['count']); ?>× pokus, <?php echo htmlspecialchars($blocked['timestamp']); ?>)</span>
                                        <button type="button" onclick="allowBlockedIp('<?php echo htmlspecialchars($blocked['ip']); ?>')" style="background: #10b981; color: white; border: none; border-radius: 4px; padding: 4px 10px; cursor: pointer; font-size: 0.8rem; font-weight: 600; transition: background 0.2s;" onmouseover="this.style.background='#059669'" onmouseout="this.style.background='#10b981'">
                                            + Povolit zařízení
                                        </button>
                                    </div>
                                <?php endforeach; ?>
                            </div>
                        </div>
                        <?php endif; ?>

                        <!-- Quick Presets -->
                        <div style="display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; align-items: center;">
                            <span style="font-weight: 600; font-size: 0.85rem; color: #475569;">Rychlé šablony:</span>
                            <button type="button" onclick="addPresetRule('192.168.0.0/16', 'Privátní síť 192.168.x.x')" style="background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; border-radius: 4px; padding: 4px 10px; font-size: 0.82rem; font-weight: 600; cursor: pointer;">+ Celá LAN (192.168.0.0/16)</button>
                            <button type="button" onclick="addPresetRule('10.0.0.0/8', 'Privátní síť 10.x.x.x')" style="background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; border-radius: 4px; padding: 4px 10px; font-size: 0.82rem; font-weight: 600; cursor: pointer;">+ Celá LAN (10.0.0.0/8)</button>
                            <button type="button" onclick="addPresetRule('127.0.0.1', 'Localhost')" style="background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; border-radius: 4px; padding: 4px 10px; font-size: 0.82rem; font-weight: 600; cursor: pointer;">+ Localhost (127.0.0.1)</button>
                            <button type="button" onclick="addPresetRule('*', 'Bez omezení (Všechny IP)')" style="background: #e0f2fe; color: #0369a1; border: 1px solid #7dd3fc; border-radius: 4px; padding: 4px 10px; font-size: 0.82rem; font-weight: 600; cursor: pointer;">+ Povolit Vše (*)</button>
                        </div>

                        <!-- Table Rules Manager Mode -->
                        <div id="firewall-table-mode">
                            <table id="firewall-rules-table" style="width: 100%; border-collapse: collapse; background: white; border: 1px solid #cbd5e1; border-radius: 6px; overflow: hidden; margin-bottom: 10px;">
                                <thead>
                                    <tr style="background: #f8fafc; text-align: left; border-bottom: 1px solid #cbd5e1; font-size: 0.85rem; color: #475569;">
                                        <th style="padding: 10px 12px; width: 42%;">IP adresa / CIDR rozsah</th>
                                        <th style="padding: 10px 12px; width: 43%;">Název zařízení / Poznámka</th>
                                        <th style="padding: 10px 12px; width: 15%; text-align: center;">Akce</th>
                                    </tr>
                                </thead>
                                <tbody id="firewall-rules-tbody">
                                    <!-- Dynamic rows -->
                                </tbody>
                            </table>

                            <div style="display: flex; gap: 10px; margin-bottom: 10px; align-items: center; flex-wrap: wrap;">
                                <input type="text" id="new-rule-ip" placeholder="IP adresa nebo CIDR rozsah (např. 10.0.40.103 nebo 192.168.1.0/24)" style="flex: 1; min-width: 220px; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px; font-size: 0.88rem;">
                                <input type="text" id="new-rule-label" placeholder="Poznámka (např. Vchodová kamera)" style="flex: 1; min-width: 180px; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px; font-size: 0.88rem;">
                                <button type="button" onclick="addCustomRuleFromInput()" style="background: #2e7d32; color: white; border: none; padding: 8px 16px; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 0.88rem;">+ Přidat pravidlo</button>
                            </div>
                        </div>

                        <!-- Expert Raw Text Mode Toggle -->
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px;">
                            <a href="javascript:void(0)" onclick="toggleFirewallExpertMode()" id="firewall-expert-toggle" style="font-size: 0.85rem; color: #0284c7; text-decoration: underline; font-weight: 600;">⚙️ Přepnout na Expertní surový text (ALLOWED_IPS)</a>
                        </div>
                        <div id="firewall-expert-mode" style="display: none; margin-top: 10px;">
                            <input type="text" name="allowed_ips" id="allowed_ips" value="<?php echo htmlspecialchars($config['ALLOWED_IPS']); ?>" placeholder="192.168.1.0/24, 10.0.0.5, 127.0.0.1" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px; font-family: monospace;">
                            <span class="field-hint">Čárkou oddělené IP/CIDR adresy kamer. V expertním režimu můžete upravovat celý řetězec přímo.</span>
                        </div>
                    </div>

                    <!-- MQTT Broker Settings -->
                    <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 1rem; border-bottom: 2px solid #f1f8e9; padding-bottom: 6px;">📡 Nastavení MQTT Brokeru</h4>

                    <div style="margin-bottom: 15px; background: #f8fafc; padding: 12px 15px; border-radius: 6px; border: 1px solid #e2e8f0;">
                        <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                            <input type="checkbox" name="use_loxberry_mqtt" id="use_loxberry_mqtt" onchange="toggleMqttFields()" <?php echo ($config['USE_LOXBERRY_MQTT'] === "True" || $config['USE_LOXBERRY_MQTT'] === true) ? 'checked' : ''; ?>>
                            <span style="font-weight: 700; color: #2e7d32;">Použít automatickou detekci z LoxBerry MQTT Gateway V2</span>
                        </label>
                        <div id="mqtt-auto-badge" style="margin-top: 6px; font-size: 0.85rem; color: #0284c7; display: none;">
                            ℹ️ Přihlašovací údaje jsou automaticky přebrány ze systému LoxBerry.
                        </div>
                    </div>

                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 25px;">
                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">MQTT Host:</label>
                            <input type="text" name="mqtt_host" id="mqtt_host" value="<?php echo htmlspecialchars($config['MQTT_HOST']); ?>" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">MQTT Port:</label>
                            <input type="number" name="mqtt_port" id="mqtt_port" value="<?php echo htmlspecialchars($config['MQTT_PORT']); ?>" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">MQTT Uživatel:</label>
                            <input type="text" name="mqtt_username" id="mqtt_username" value="<?php echo htmlspecialchars($config['MQTT_USERNAME']); ?>" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">MQTT Heslo:</label>
                            <div style="position: relative;">
                                <input type="password" name="mqtt_password" id="mqtt_password" value="<?php echo htmlspecialchars($config['MQTT_PASSWORD']); ?>" style="width: 100%; padding: 8px 36px 8px 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                                <button type="button" onclick="togglePasswordVisibility('mqtt_password')" style="position: absolute; right: 8px; top: 50%; transform: translateY(-50%); border: none; background: transparent; cursor: pointer; font-size: 1.1rem;">👁️</button>
                            </div>
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">MQTT Root Topic:</label>
                            <input type="text" name="mqtt_topic" value="<?php echo htmlspecialchars($config['MQTT_TOPIC']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                            <span class="field-hint">Např. smtp2mqtt -> vytvoří topic smtp2mqtt/kamera_zahrada.</span>
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">MQTT Trigger Payload:</label>
                            <input type="text" name="mqtt_payload" value="<?php echo htmlspecialchars($config['MQTT_PAYLOAD']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">MQTT Auto-Reset Čas (sekundy):</label>
                            <input type="number" name="mqtt_reset_time" value="<?php echo htmlspecialchars($config['MQTT_RESET_TIME']); ?>" required min="0" step="1" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                            <span class="field-hint">Po kolika sekundách se stav automaticky vrátí na OFF (výchozí 10 s pro Loxone Mo vstup, 0 = bez auto-resetu).</span>
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">MQTT Reset Payload:</label>
                            <input type="text" name="mqtt_reset_payload" value="<?php echo htmlspecialchars($config['MQTT_RESET_PAYLOAD']); ?>" required style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                        </div>
                    </div>

                    <!-- Hikvision Latency & Optimization Card -->
                    <div style="margin-bottom: 25px; padding: 16px; background: #0f172a; color: #f8fafc; border-radius: 8px; border-left: 4px solid #38bdf8; font-size: 0.9rem;">
                        <h4 style="margin: 0 0 10px 0; color: #38bdf8; font-size: 1rem;"><i class="fa fa-tachometer"></i> Doporučené nastavení Hikvision kamer pro minimální latenci (&lt; 10 ms)</h4>
                        <ul style="margin: 0; padding-left: 20px; line-height: 1.6; color: #cbd5e1;">
                            <li><b>Pevná IP adresa LoxBerry:</b> V nastavení SMTP v kameře zadejte přímou IP adresu LoxBerry (např. <code>10.0.20.100</code>) místo názvu domény. Zabráníte zpoždění z DNS dotazů.</li>
                            <li><b>Vypnutí přílohy fotek (Attached Image):</b> Pokud nepotřebujete fotky v e-mailu, vypněte v kameře volbu <i>Attached Image</i>. Zkrátíte čas odeslání z 3 sekund na 10 ms.</li>
                            <li><b>Minimální e-mailový interval:</b> V nastavení e-mailu v kameře nastavte <i>Interval</i> na minimum (0–2 s).</li>
                            <li><b>Vstup Mo v Loxone (Osvětlení):</b> Pro přímé zapojení do vstupu <code>Mo</code> bloku Automatické osvětlení je ideální <b>Auto-reset 10 s</b>. Ponechá světlo sepnuté po dobu pohybu a po odchodu korektně zhasne.</li>
                        </ul>
                    </div>

                    <!-- Diagnostics & Fast Actions Bar -->
                    <h4 style="margin: 0 0 12px 0; color: #0284c7; font-size: 1rem; border-bottom: 2px solid #e0f2fe; padding-bottom: 6px;">🧪 Rychlá Diagnostika Spojení</h4>
                    <div style="display: flex; gap: 12px; margin-bottom: 25px; flex-wrap: wrap;">
                        <button type="button" onclick="runDiagnosticTest('email')" class="lox-btn-test">✉️ Odeslat Testovací E-mail</button>
                        <button type="button" onclick="runDiagnosticTest('mqtt')" class="lox-btn-test" style="background: #0d9488;">📡 Test Spojení k MQTT Brokeru</button>
                    </div>

                    <!-- Advanced Maintenance & Attachments -->
                    <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 1rem; border-bottom: 2px solid #f1f8e9; padding-bottom: 6px;">🖼️ Správa Příloh & Čištění</h4>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 25px;">
                        <div style="grid-column: 1 / -1;">
                            <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                                <input type="checkbox" name="save_attachments" <?php echo ($config['SAVE_ATTACHMENTS'] === "True" || $config['SAVE_ATTACHMENTS'] === true) ? 'checked' : ''; ?>>
                                <span style="font-weight: 600; color: #334155;">Ukládat snímky detekce pohybu (obrázkové přílohy z kamer) do adresáře attachments</span>
                            </label>
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">Auto-mazání starých příloh (dny):</label>
                            <input type="number" name="cleanup_attachments_days" value="<?php echo htmlspecialchars($config['CLEANUP_ATTACHMENTS_DAYS']); ?>" required min="0" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                            <span class="field-hint">0 = nikdy nemazat. Výchozí: 30 dní.</span>
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">Auto-mazání logů (dny):</label>
                            <input type="number" name="cleanup_logs_days" value="<?php echo htmlspecialchars($config['CLEANUP_LOGS_DAYS']); ?>" required min="0" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                            <span class="field-hint">0 = nikdy nemazat. Výchozí: 30 dní.</span>
                        </div>

                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">Úroveň Logování (LoxBerry System LogLevel):</label>
                            <?php $curr_ll = intval($lbpconfig['PLUGIN']['LOGLEVEL'] ?? 4); ?>
                            <select name="plugin_loglevel" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px; background: white;">
                                <option value="7" <?php echo $curr_ll >= 7 ? 'selected' : ''; ?>>7 - DEBUG (Podrobné logování všeho)</option>
                                <option value="6" <?php echo $curr_ll == 6 ? 'selected' : ''; ?>>6 - INFO (Běžné provozní události)</option>
                                <option value="4" <?php echo $curr_ll == 4 ? 'selected' : ''; ?>>4 - WARNING (Pouze varování a chyby)</option>
                                <option value="3" <?php echo $curr_ll <= 3 ? 'selected' : ''; ?>>3 - ERROR (Pouze kritické chyby)</option>
                            </select>
                        </div>
                    </div>

                    <!-- Submit Button Footer -->
                    <div style="margin-top: 30px; padding-top: 15px; border-top: 1px solid #e2e8f0; display: flex; gap: 15px; align-items: center;">
                        <button type="submit" name="save_settings" class="lox-btn-primary">
                            <?php echo htmlspecialchars($L['BTN_SAVE'] ?? '💾 Uložit Nastavení & Restartovat Službu'); ?>
                        </button>
                        <a href="?action=restart_daemon" class="lox-btn-secondary">
                            <?php echo htmlspecialchars($L['BTN_RESTART_DAEMON'] ?? '🚀 Vynutit Restart Služby'); ?>
                        </a>
                    </div>
                </form>
            </div>
        </div>

    <?php elseif ($active_tab === 'dashboard'): ?>
        <!-- Live Dashboard Tab -->
        <div class="lox-card">
            <div class="lox-card-header">
                <h3 class="lox-card-title">📊 Live Inspektor SMTP relací & MQTT Zpráv</h3>
                <div style="display: flex; gap: 10px; align-items: center;">
                    <span id="dash-last-update" style="font-size: 0.8rem; color: #64748b;">Není aktualizováno</span>
                    <button type="button" onclick="refreshDashboardJSON()" class="lox-btn-secondary" style="padding: 4px 10px; font-size: 0.82rem;">🔄 Obnovit</button>
                </div>
            </div>
            <div class="lox-card-body">
                <!-- Live Status Cards -->
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 25px;">
                    <div style="background: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 8px;">
                        <span style="color: #64748b; font-size: 0.85rem; font-weight: 600;">Stav SMTP Serveru</span>
                        <div id="dash-smtp-status" style="font-size: 1.2rem; font-weight: 700; color: #0284c7; margin-top: 4px;">Načítám...</div>
                    </div>
                    <div style="background: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 8px;">
                        <span style="color: #64748b; font-size: 0.85rem; font-weight: 600;">Stav MQTT Brokeru</span>
                        <div id="dash-mqtt-status" style="font-size: 1.2rem; font-weight: 700; color: #0284c7; margin-top: 4px;">Načítám...</div>
                    </div>
                    <div style="background: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 8px;">
                        <span style="color: #64748b; font-size: 0.85rem; font-weight: 600;">Zpracováno Zpráv</span>
                        <div id="dash-msg-count" style="font-size: 1.2rem; font-weight: 700; color: #166534; margin-top: 4px;">0</div>
                    </div>
                    <div style="background: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 8px;">
                        <span style="color: #64748b; font-size: 0.85rem; font-weight: 600;">Doba Běhu (Uptime)</span>
                        <div id="dash-uptime" style="font-size: 1.2rem; font-weight: 700; color: #334155; margin-top: 4px;">0s</div>
                    </div>
                </div>

                <!-- Recent Actions Table -->
                <h4 style="margin: 0 0 12px 0; color: #1e293b;">📋 Poslední Zachycené Detekce & Triggery (Live)</h4>
                <div style="overflow-x: auto;">
                    <table style="width: 100%; border-collapse: collapse; background: white; border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden;">
                        <thead>
                            <tr style="background: #f8fafc; text-align: left; font-size: 0.85rem; color: #475569; border-bottom: 1px solid #e2e8f0;">
                                <th style="padding: 10px 12px;">Čas</th>
                                <th style="padding: 10px 12px;">Odesílatel (Kamera)</th>
                                <th style="padding: 10px 12px;">MQTT Topic</th>
                                <th style="padding: 10px 12px;">Payload</th>
                                <th style="padding: 10px 12px;">Příloha / Stav</th>
                            </tr>
                        </thead>
                        <tbody id="dash-actions-tbody">
                            <tr><td colspan="5" style="padding: 20px; text-align: center; color: #94a3b8;">Načítám data z daemonu...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

    <?php elseif ($active_tab === 'logs'): ?>
        <!-- Log Viewer Tab -->
        <div class="lox-card">
            <div class="lox-card-header">
                <h3 class="lox-card-title">📋 Prohlížeč systémového logu smtp2mqtt</h3>
                <div style="display: flex; gap: 10px;">
                    <a href="?action=download_log" class="lox-btn-secondary" style="padding: 4px 10px; font-size: 0.82rem;">📥 Stáhnout Soubor Logu</a>
                    <a href="?action=clear_log" onclick="return confirm('Opravdu chcete vyčistit obsah logu?');" class="lox-btn-secondary" style="padding: 4px 10px; font-size: 0.82rem; color: #b91c1c;">🧹 Vyčistit Log</a>
                </div>
            </div>
            <div class="lox-card-body">
                <div style="margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
                    <span style="font-size: 0.85rem; color: #64748b;">Zobrazen aktuální soubor: <code><?php echo htmlspecialchars($log_file); ?></code></span>
                    <div style="display: flex; gap: 8px;">
                        <button type="button" onclick="copyLogToClipboard()" class="lox-btn-secondary" style="padding: 4px 10px; font-size: 0.82rem;">📋 Zkopírovat Log</button>
                        <a href="/admin/system/logmanager.php?package=smtp2mqtt" target="_blank" class="lox-btn-secondary" style="padding: 4px 10px; font-size: 0.82rem; background: #e0f2fe; color: #0369a1; border-color: #7dd3fc; text-decoration: none;">🔍 Otevřít v LoxBerry Log Manageru</a>
                    </div>
                </div>
                <div id="log-box" class="log-viewer-box"><?php
                    if (file_exists($log_file) && filesize($log_file) > 0) {
                        $lines = file($log_file);
                        $recent_lines = array_slice($lines, -300);
                        foreach ($recent_lines as $line) {
                            $escaped = htmlspecialchars($line);
                            if (strpos($line, 'ERROR') !== false || strpos($line, 'CRITICAL') !== false) {
                                echo "<span class='log-line-error'>{$escaped}</span>";
                            } elseif (strpos($line, 'WARNING') !== false) {
                                echo "<span class='log-line-warn'>{$escaped}</span>";
                            } elseif (strpos($line, 'DEBUG') !== false) {
                                echo "<span class='log-line-debug'>{$escaped}</span>";
                            } else {
                                echo "<span class='log-line-info'>{$escaped}</span>";
                            }
                        }
                    } else {
                        echo "Soubor logu je zatím prázdný nebo nebyl vytvořen. Cesta: " . htmlspecialchars($log_file);
                    }
                ?></div>
            </div>
        </div>

    <?php elseif ($active_tab === 'help'): ?>
        <!-- Help Tab -->
        <div class="lox-card">
            <div class="lox-card-header">
                <h3 class="lox-card-title">📖 Nápověda & Nastavení Kamer pro minimální latenci</h3>
            </div>
            <div class="lox-card-body" style="color: #334155; line-height: 1.6;">
                <p>Plugin <strong>smtp2mqtt</strong> přijímá e-mailové notifikace o detekci pohybu z IP kamer a okamžitě posílá MQTT zprávy do Loxone.</p>
                
                <h4 style="color: #2e7d32; margin-top: 20px;">🎥 Nastavení jednotlivých značek kamer</h4>
                
                <div class="accordion-item">
                    <div class="accordion-header" onclick="toggleAccordion('acc-hik')">
                        <span>🔴 Hikvision / HiLook / Ezviz (Doporučeno)</span> <span>▼</span>
                    </div>
                    <div class="accordion-body" id="acc-hik" style="display: block;">
                        <ol style="padding-left: 20px; line-height: 1.8;">
                            <li>Přihlaste se do kamery: <strong>Configuration -> Network -> Advanced Settings -> Email</strong>.</li>
                            <li><strong>Server Authentication:</strong> Vypnout (OFF).</li>
                            <li><strong>SMTP Server:</strong> Zadejte přímo IP adresu LoxBerry (např. <code>10.0.20.100</code>). <em>Nepoužívejte doménový název.</em></li>
                            <li><strong>SMTP Port:</strong> <code>1025</code>.</li>
                            <li><strong>Sender / Sender Address:</strong> <code>kamera.vchod@domov.local</code>. Z této adresy vznikne MQTT topic <code>smtp2mqtt/kamera_vchod-domov_local</code>.</li>
                            <li><strong>Attached Image (Fotka v příloze):</strong> Vypněte pro dosažení nejvyšší rychlosti (&lt; 10 ms).</li>
                        </ol>
                    </div>
                </div>

                <div class="accordion-item">
                    <div class="accordion-header" onclick="toggleAccordion('acc-dahua')">
                        <span>🟠 Dahua / CP PLUS / Imou</span> <span>▼</span>
                    </div>
                    <div class="accordion-body" id="acc-dahua">
                        <ol style="padding-left: 20px; line-height: 1.8;">
                            <li>Otevřete: <strong>Setting -> Network -> SMTP (Email)</strong>.</li>
                            <li>Zaškrtněte <strong>Enable</strong>. Server IP: IP vašeho LoxBerry, Port: <code>1025</code>.</li>
                            <li>Anonymní odesílání / Encryption: <strong>None / None</strong>.</li>
                            <li>Sender: <code>kamera.garaz@domov.local</code>. Zkontrolujte Test v kamery.</li>
                        </ol>
                    </div>
                </div>

                <div class="accordion-item">
                    <div class="accordion-header" onclick="toggleAccordion('acc-reolink')">
                        <span>🔵 Reolink / Axis / Vivotek</span> <span>▼</span>
                    </div>
                    <div class="accordion-body" id="acc-reolink">
                        <p>V nastavení e-mailu kamery zvolte custom SMTP server bez šifrování, zadejte IP adresu LoxBerry a port 1025. E-mail odesílatele nastavte jako unifikovaný název kamery.</p>
                    </div>
                </div>

                <!-- Loxone Config Subscription Generator -->
                <h4 style="color: #2e7d32; margin-top: 25px;">🏠 Interaktivní Loxone Config Generator</h4>
                <div style="background: #f8fafc; border: 1px solid #e2e8f0; padding: 16px; border-radius: 6px;">
                    <label style="font-weight: 600; display: block; margin-bottom: 6px;">Zadejte e-mail odesílatele kamery:</label>
                    <input type="text" id="gen-email-input" value="kamera.zahrada@domov.local" oninput="generateLoxoneConfigTopic()" style="width: 100%; max-width: 400px; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                    
                    <div style="margin-top: 12px;">
                        <span style="font-size: 0.85rem; color: #64748b; font-weight: 600;">Výsledný MQTT Subscriptions Topic pro Loxone Config:</span>
                        <div id="gen-topic-result" style="font-family: monospace; font-size: 1.1rem; font-weight: 700; color: #0284c7; margin-top: 4px; background: white; padding: 8px 12px; border: 1px solid #cbd5e1; border-radius: 4px; display: inline-block;">
                            smtp2mqtt/kamera_zahrada-domov_local
                        </div>
                    </div>
                </div>
            </div>
        </div>
    <?php endif; ?>

</div>

<script>
    const detectedMqtt = <?php echo json_encode($detected_mqtt); ?>;

    // Firewall Rules Table Management
    let firewallRules = <?php echo json_encode($config['FIREWALL_RULES'] ?? []); ?>;

    function renderFirewallTable() {
        const tbody = document.getElementById('firewall-rules-tbody');
        if (!tbody) return;
        tbody.innerHTML = '';

        if (firewallRules.length === 0) {
            tbody.innerHTML = `<tr><td colspan="3" style="text-align: center; color: #94a3b8; padding: 15px; font-style: italic;">Žádná aktivní pravidla. SMTP server je přístupný ze všech IP adres (*).</td></tr>`;
            syncAllowedIpsFromTable();
            return;
        }

        firewallRules.forEach((rule, idx) => {
            const tr = document.createElement('tr');
            tr.style.borderBottom = '1px solid #e2e8f0';
            tr.innerHTML = `
                <td style="padding: 8px 12px; font-family: monospace; font-weight: 600; color: #1e293b;">
                    <input type="text" name="rule_ip[]" value="${escapeHtml(rule.ip)}" required oninput="syncAllowedIpsFromTable()" style="width: 100%; border: 1px solid #cbd5e1; padding: 6px; border-radius: 4px; font-family: monospace; font-size: 0.88rem;">
                </td>
                <td style="padding: 8px 12px;">
                    <input type="text" name="rule_label[]" value="${escapeHtml(rule.label || '')}" placeholder="Komentář / Název zařízení" style="width: 100%; border: 1px solid #cbd5e1; padding: 6px; border-radius: 4px; font-size: 0.88rem;">
                </td>
                <td style="padding: 8px 12px; text-align: center;">
                    <button type="button" onclick="removeFirewallRule(${idx})" style="background: #ef4444; color: white; border: none; border-radius: 4px; padding: 5px 10px; cursor: pointer; font-size: 0.85rem;" title="Smazat pravidlo">🗑️ Smazat</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
        syncAllowedIpsFromTable();
    }

    function escapeHtml(str) {
        return (str || '').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    }

    function addFirewallRule(ip, label = '') {
        ip = (ip || '').trim();
        if (!ip) return;
        const existing = firewallRules.find(r => r.ip === ip);
        if (existing) {
            showToast('⚠️ Pravidlo pro IP ' + ip + ' již v seznamu existuje.', false);
            return;
        }
        firewallRules.push({ ip: ip, label: label });
        renderFirewallTable();
        showToast('✅ Pravidlo ' + ip + ' bylo přidáno do seznamu.', true);
    }

    function removeFirewallRule(idx) {
        if (idx >= 0 && idx < firewallRules.length) {
            firewallRules.splice(idx, 1);
            renderFirewallTable();
        }
    }

    function addPresetRule(ip, label) {
        addFirewallRule(ip, label);
    }

    function addCustomRuleFromInput() {
        const ipInput = document.getElementById('new-rule-ip');
        const labelInput = document.getElementById('new-rule-label');
        if (!ipInput) return;
        const ip = ipInput.value.trim();
        const label = labelInput ? labelInput.value.trim() : '';
        if (!ip) {
            showToast('Zadejte prosím platnou IP adresu nebo CIDR rozsah.', false);
            return;
        }
        addFirewallRule(ip, label);
        ipInput.value = '';
        if (labelInput) labelInput.value = '';
    }

    function allowBlockedIp(ip) {
        addFirewallRule(ip, 'Kamera (z neoprávněného pokusu)');
    }

    function syncAllowedIpsFromTable() {
        const inputs = document.querySelectorAll('input[name="rule_ip[]"]');
        let ips = [];
        if (inputs && inputs.length > 0) {
            inputs.forEach(inp => { if (inp.value.trim()) ips.push(inp.value.trim()); });
        } else {
            ips = firewallRules.map(r => r.ip).filter(ip => ip.length > 0);
        }
        const allowedInput = document.getElementById('allowed_ips');
        if (allowedInput) {
            allowedInput.value = ips.join(', ');
        }
    }

    function toggleFirewallExpertMode() {
        const tableMode = document.getElementById('firewall-table-mode');
        const expertMode = document.getElementById('firewall-expert-mode');
        const toggleBtn = document.getElementById('firewall-expert-toggle');
        if (!tableMode || !expertMode) return;

        if (expertMode.style.display === 'none' || expertMode.style.display === '') {
            syncAllowedIpsFromTable();
            tableMode.style.display = 'none';
            expertMode.style.display = 'block';
            if (toggleBtn) toggleBtn.textContent = '📋 Přepnout na Vizuální Tabulkový Manažer';
        } else {
            const rawVal = document.getElementById('allowed_ips')?.value || '';
            const parts = rawVal.split(',').map(p => p.trim()).filter(p => p.length > 0);
            firewallRules = parts.map(p => {
                const existing = firewallRules.find(r => r.ip === p);
                return { ip: p, label: existing ? existing.label : '' };
            });
            renderFirewallTable();
            expertMode.style.display = 'none';
            tableMode.style.display = 'block';
            if (toggleBtn) toggleBtn.textContent = '⚙️ Přepnout na Expertní surový text (ALLOWED_IPS)';
        }
    }

    function toggleMqttFields() {
        const isAuto = document.getElementById('use_loxberry_mqtt')?.checked;
        const fields = ['mqtt_host', 'mqtt_port', 'mqtt_username', 'mqtt_password'];
        const badge = document.getElementById('mqtt-auto-badge');

        fields.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.readOnly = isAuto;
                el.style.backgroundColor = isAuto ? '#f1f5f9' : '#ffffff';
                if (isAuto && id === 'mqtt_host') el.value = detectedMqtt.MQTT_HOST;
                if (isAuto && id === 'mqtt_port') el.value = detectedMqtt.MQTT_PORT;
                if (isAuto && id === 'mqtt_username') el.value = detectedMqtt.MQTT_USERNAME;
                if (isAuto && id === 'mqtt_password') el.value = detectedMqtt.MQTT_PASSWORD;
            }
        });
        if (badge) badge.style.display = isAuto ? 'block' : 'none';
    }

    function togglePasswordVisibility(fieldId) {
        const input = document.getElementById(fieldId);
        if (input) {
            input.type = input.type === 'password' ? 'text' : 'password';
        }
    }

    function showToast(msg, isSuccess = true) {
        const container = document.getElementById('toast-container');
        if (!container) return;
        const toast = document.createElement('div');
        toast.className = 'toast-msg';
        toast.style.background = isSuccess ? '#15803d' : '#b91c1c';
        toast.textContent = msg;
        container.appendChild(toast);
        setTimeout(() => { toast.remove(); }, 4000);
    }

    function runDiagnosticTest(type) {
        showToast('⏳ Spouštím diagnostický test...', true);
        let url = '?action=test_' + type;
        if (type === 'mqtt') {
            const useLb = document.getElementById('use_loxberry_mqtt')?.checked ? 'true' : 'false';
            const host = encodeURIComponent(document.getElementById('mqtt_host')?.value || '');
            const port = encodeURIComponent(document.getElementById('mqtt_port')?.value || '');
            const user = encodeURIComponent(document.getElementById('mqtt_username')?.value || '');
            const pass = encodeURIComponent(document.getElementById('mqtt_password')?.value || '');
            url += `&use_loxberry_mqtt=${useLb}&mqtt_host=${host}&mqtt_port=${port}&mqtt_username=${user}&mqtt_password=${pass}`;
        }
        fetch(url)
            .then(r => r.json())
            .then(data => {
                showToast(data.message, data.success);
                if (window.location.search.includes('tab=dashboard')) {
                    refreshDashboardJSON();
                }
            })
            .catch(() => { showToast('Chyba při komunikaci se serverem', false); });
    }


    function validateConfigForm() {
        const smtpPort = parseInt(document.getElementById('smtp_port')?.value);
        const webPort = parseInt(document.getElementById('web_port')?.value);
        if (isNaN(smtpPort) || smtpPort < 1 || smtpPort > 65535) {
            alert('Neplatný SMTP Port! Zadejte číslo 1–65535.');
            return false;
        }
        if (isNaN(webPort) || webPort < 1 || webPort > 65535) {
            alert('Neplatný Web Port! Zadejte číslo 1–65535.');
            return false;
        }
        return true;
    }

    function refreshDashboardJSON() {
        fetch('?tab=dashboard&_ajax=json')
            .then(r => r.json())
            .then(data => {
                const updateEl = document.getElementById('dash-last-update');
                if (updateEl) updateEl.textContent = 'Aktualizováno: ' + new Date().toLocaleTimeString('cs-CZ');

                if (data.status) {
                    const smtpEl = document.getElementById('dash-smtp-status');
                    if (smtpEl) {
                        smtpEl.textContent = data.status.smtp_connected ? '🟢 Aktivní (port ' + data.status.smtp_port + ')' : '🔴 Neaktivní';
                        smtpEl.style.color = data.status.smtp_connected ? '#166534' : '#b91c1c';
                    }
                    const mqttEl = document.getElementById('dash-mqtt-status');
                    if (mqttEl) {
                        mqttEl.textContent = data.status.mqtt_connected ? '🟢 Připojeno' : '🔴 Odpojeno';
                        mqttEl.style.color = data.status.mqtt_connected ? '#166534' : '#b91c1c';
                    }
                    const cntEl = document.getElementById('dash-msg-count');
                    if (cntEl) cntEl.textContent = data.status.processed_messages_count || 0;

                    const uptEl = document.getElementById('dash-uptime');
                    if (uptEl) uptEl.textContent = data.status.uptime_formatted || '0s';

                    // Actions table rendering
                    const tbody = document.getElementById('dash-actions-tbody');
                    if (tbody && data.status.recent_actions) {
                        if (data.status.recent_actions.length === 0) {
                            tbody.innerHTML = '<tr><td colspan="5" style="padding: 20px; text-align: center; color: #94a3b8;">Zatím nebyly zaznamenány žádné detekce.</td></tr>';
                        } else {
                            tbody.innerHTML = '';
                            data.status.recent_actions.forEach(act => {
                                const tr = document.createElement('tr');
                                tr.style.borderBottom = '1px solid #f1f5f9';
                                let badge = act.status === 'SUCCESS' 
                                    ? '<span class="lox-badge-success">OK / Triggery</span>' 
                                    : (act.status === 'BLOCKED' ? '<span class="lox-badge-danger">🔒 BLOCKED (Odmítnuto)</span>' : '<span class="lox-badge-danger">CHYBA</span>');
                                
                                let attHtml = '';
                                if (act.attachments && act.attachments.length > 0) {
                                    attHtml = `<div style="margin-top: 4px;"><span class="lox-badge-info">📸 ${act.attachments.length} snímky</span></div>`;
                                }

                                tr.innerHTML = `
                                    <td style="padding: 10px 12px; font-size: 0.85rem; color: #64748b;">${escapeHtml(act.timestamp)}</td>
                                    <td style="padding: 10px 12px; font-weight: 600; color: #1e293b;">${escapeHtml(act.sender)}</td>
                                    <td style="padding: 10px 12px; font-family: monospace; font-size: 0.85rem; color: #0284c7;">${escapeHtml(act.topic)}</td>
                                    <td style="padding: 10px 12px; font-weight: 700;"><code>${escapeHtml(act.payload)}</code></td>
                                    <td style="padding: 10px 12px;">${badge}${attHtml}</td>
                                `;
                                tbody.appendChild(tr);
                            });
                        }
                    }
                }
            })
            .catch(() => {});
    }

    function filterLogViewer(level) {
        const lines = document.querySelectorAll('#log-box span');
        lines.forEach(item => {
            if (level === 'ALL') {
                item.style.display = 'block';
            } else {
                item.style.display = item.classList.contains('log-line-' + level.toLowerCase()) ? 'block' : 'none';
            }
        });
    }

    function copyLogToClipboard() {
        const box = document.getElementById('log-box');
        if (box) {
            navigator.clipboard.writeText(box.textContent).then(() => {
                showToast('📋 Log zkopírován do schránky!');
            });
        }
    }

    function toggleAccordion(id) {
        const el = document.getElementById(id);
        if (el) {
            el.style.display = el.style.display === 'block' ? 'none' : 'block';
        }
    }

    function generateLoxoneConfigTopic() {
        const input = document.getElementById('gen-email-input')?.value || '';
        const cleaned = input.trim().toLowerCase().replace(/[^a-z0-9]/g, '_');
        const res = document.getElementById('gen-topic-result');
        if (res) res.textContent = 'smtp2mqtt/' + (cleaned || 'kamera');
    }

    document.addEventListener('DOMContentLoaded', () => {
        toggleMqttFields();
        renderFirewallTable();
        const logBox = document.getElementById('log-box');
        if (logBox) {
            logBox.scrollTop = logBox.scrollHeight;
        }
        if (window.location.search.includes('tab=dashboard')) {
            refreshDashboardJSON();
            setInterval(refreshDashboardJSON, 5000);
        }
    });

</script>
<?php LBWeb::lbfooter(); ?>
