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
$plugin_version = '2.0.0';

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
    "MQTT_PAYLOAD" => "1",
    "MQTT_RESET_TIME" => 10,
    "MQTT_RESET_PAYLOAD" => "0",
    "SAVE_ATTACHMENTS" => "True",
    "CLEANUP_ATTACHMENTS_DAYS" => 30,
    "CLEANUP_LOGS_DAYS" => 30,
    "DEBUG" => "False",
    "ENABLE_ISAPI" => "False",
    "ISAPI_CAMERAS" => "",
    "ISAPI_USER" => "admin",
    "ISAPI_PASSWORD" => ""
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

$isapi_cameras_list = [];
if (!empty($config['ISAPI_CAMERAS'])) {
    $raw_cams = $config['ISAPI_CAMERAS'];
    if (is_array($raw_cams)) {
        $isapi_cameras_list = $raw_cams;
    } else {
        $str_val = strval($raw_cams);
        if (substr($str_val, 0, 1) === '"' && substr($str_val, -1) === '"') {
            $str_val = stripslashes(substr($str_val, 1, -1));
        }
        $decoded = json_decode($str_val, true);
        if (is_string($decoded)) {
            $decoded = json_decode($decoded, true);
        }
        if (is_array($decoded)) {
            $isapi_cameras_list = $decoded;
        } else {
            foreach (explode(',', $str_val) as $entry) {
                $entry = trim($entry);
                if (empty($entry)) continue;
                $parts = explode(':', $entry);
                if (count($parts) === 1) {
                    $isapi_cameras_list[] = ['ip' => $parts[0], 'port' => 80, 'sender' => 'cam_' . $parts[0]];
                } else if (count($parts) === 2) {
                    if (is_numeric($parts[1])) {
                        $isapi_cameras_list[] = ['ip' => $parts[0], 'port' => intval($parts[1]), 'sender' => 'cam_' . $parts[0]];
                    } else {
                        $isapi_cameras_list[] = ['ip' => $parts[0], 'port' => 80, 'sender' => $parts[1]];
                    }
                } else {
                    $isapi_cameras_list[] = ['ip' => $parts[0], 'port' => intval($parts[1]), 'sender' => $parts[2]];
                }
            }
        }
    }
}

// Handle Clean AJAX Probe Camera Endpoint
if (isset($_GET['_ajax']) && $_GET['_ajax'] === 'probe_camera') {
    header('Content-Type: application/json; charset=utf-8');
    $ip = trim($_GET['ip'] ?? '');
    $port = intval($_GET['port'] ?? 80);
    $user = trim($_GET['user'] ?? ($config['ISAPI_USER'] ?? 'admin'));
    $pass = $_GET['password'] ?? ($_GET['pwd'] ?? ($config['ISAPI_PASSWORD'] ?? ''));

    if (empty($ip)) {
        echo json_encode(['success' => false, 'error' => 'Chybí IP adresa']);
        exit;
    }

    if (function_exists('curl_init')) {
        $ch = curl_init();
        curl_setopt($ch, CURLOPT_URL, "http://{$ip}:{$port}/ISAPI/System/deviceInfo");
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_HTTPAUTH, CURLAUTH_DIGEST);
        curl_setopt($ch, CURLOPT_USERPWD, "{$user}:{$pass}");
        curl_setopt($ch, CURLOPT_TIMEOUT, 4);
        curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 3);
        
        $start_t = microtime(true);
        $response = curl_exec($ch);
        $lat_ms = intval((microtime(true) - $start_t) * 1000);
        $http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $curl_err = curl_error($ch);
        curl_close($ch);

        if ($http_code === 200 && !empty($response)) {
            $dev_name = "";
            $model = "";
            $fw = "";
            if (preg_match('/<deviceName>([^<]+)<\/deviceName>/i', $response, $m)) $dev_name = trim($m[1]);
            if (preg_match('/<model>([^<]+)<\/model>/i', $response, $m)) $model = trim($m[1]);
            if (preg_match('/<firmwareVersion>([^<]+)<\/firmwareVersion>/i', $response, $m)) $fw = trim($m[1]);

            echo json_encode([
                'success' => true,
                'status_code' => 200,
                'latency_ms' => $lat_ms,
                'device_name' => $dev_name,
                'model' => $model,
                'firmware' => $fw,
                'message' => "Připojeno (" . ($model ?: ($dev_name ?: 'Hikvision')) . ", FW: {$fw}, {$lat_ms}ms)"
            ]);
        } else if ($http_code === 401) {
            echo json_encode([
                'success' => false,
                'status_code' => 401,
                'latency_ms' => $lat_ms,
                'error' => 'Chyba ověření (401 Unauthorized) - Zkontrolujte jméno a heslo'
            ]);
        } else {
            $err = !empty($curl_err) ? $curl_err : "HTTP Chyba {$http_code}";
            echo json_encode([
                'success' => false,
                'status_code' => $http_code,
                'latency_ms' => $lat_ms,
                'error' => $err
            ]);
        }
    } else {
        echo json_encode(['success' => false, 'error' => 'PHP cURL modul není k dispozici']);
    }
    exit;
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
        $config['MQTT_PAYLOAD'] = trim($_POST['mqtt_payload'] ?? '1');
        $config['MQTT_RESET_TIME'] = intval($_POST['mqtt_reset_time'] ?? 10);
        $config['MQTT_RESET_PAYLOAD'] = trim($_POST['mqtt_reset_payload'] ?? '0');
        $config['ENABLE_EVENT_TOPIC'] = isset($_POST['enable_event_topic']) ? "True" : "False";
        $config['ENABLE_METRICS'] = isset($_POST['enable_metrics']) ? "True" : "False";
        $config['SAVE_ATTACHMENTS'] = isset($_POST['save_attachments']) ? "True" : "False";
        $config['CLEANUP_ATTACHMENTS_DAYS'] = intval($_POST['cleanup_attachments_days'] ?? 30);
        $config['CLEANUP_LOGS_DAYS'] = intval($_POST['cleanup_logs_days'] ?? 30);

        $config['ENABLE_ISAPI'] = isset($_POST['enable_isapi']) ? "True" : "False";
        $config['ISAPI_USER'] = trim($_POST['isapi_user'] ?? 'admin');
        if (isset($_POST['isapi_password']) && $_POST['isapi_password'] !== '') {
            $config['ISAPI_PASSWORD'] = $_POST['isapi_password'];
        }

        if (isset($_POST['isapi_cam_ip']) && is_array($_POST['isapi_cam_ip'])) {
            $cam_list = [];
            $cam_ips = $_POST['isapi_cam_ip'];
            $cam_senders = $_POST['isapi_cam_sender'] ?? [];
            $cam_ports = $_POST['isapi_cam_port'] ?? [];
            $cam_users = $_POST['isapi_cam_user'] ?? [];
            $cam_passwords = $_POST['isapi_cam_password'] ?? [];

            for ($i = 0; $i < count($cam_ips); $i++) {
                $cip = trim($cam_ips[$i]);
                $csender = trim($cam_senders[$i] ?? '');
                $cport = intval($cam_ports[$i] ?? 80);
                $cuser = trim($cam_users[$i] ?? '');
                $cpass = $cam_passwords[$i] ?? '';

                if (!empty($cip)) {
                    if (empty($csender)) $csender = "cam_" . $cip;
                    $cam_item = [
                        'ip' => $cip,
                        'port' => ($cport > 0 ? $cport : 80),
                        'sender' => $csender
                    ];
                    if (!empty($cuser)) $cam_item['user'] = $cuser;
                    if (!empty($cpass)) $cam_item['password'] = $cpass;
                    $cam_list[] = $cam_item;
                }
            }
            $config['ISAPI_CAMERAS'] = $cam_list;
        } else {
            $config['ISAPI_CAMERAS'] = trim($_POST['isapi_cameras'] ?? '');
        }

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

                    <div style="margin-bottom: 25px; background: #f8fafc; padding: 12px 15px; border-radius: 6px; border: 1px solid #e2e8f0;">
                        <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                            <input type="checkbox" name="enable_event_topic" id="enable_event_topic" <?php echo ($config['ENABLE_EVENT_TOPIC'] === "True" || $config['ENABLE_EVENT_TOPIC'] === true || !isset($config['ENABLE_EVENT_TOPIC'])) ? 'checked' : ''; ?>>
                            <span style="font-weight: 700; color: #1e293b;">Odesílat rozšířené JSON události (&lt;topic&gt;/event)</span>
                        </label>
                        <div style="margin-top: 4px; font-size: 0.83rem; color: #64748b; margin-left: 28px;">
                            Vypněte, pokud chcete na MQTT posílat pouze čistý trigger/reset stav (1/0) a nepoužívat pod-topic pro detailní telemetry data kamer.
                        </div>
                    </div>

                    <div style="margin-bottom: 25px; background: #f8fafc; padding: 12px 15px; border-radius: 6px; border: 1px solid #e2e8f0;">
                        <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                            <input type="checkbox" name="enable_metrics" id="enable_metrics" <?php echo ($config['ENABLE_METRICS'] === "True" || $config['ENABLE_METRICS'] === true || !isset($config['ENABLE_METRICS'])) ? 'checked' : ''; ?>>
                            <span style="font-weight: 700; color: #2e7d32;">📊 Povolit Prometheus HTTP Exporter (&lt;host&gt;:8080/metrics)</span>
                        </label>
                        <div style="margin-top: 4px; font-size: 0.83rem; color: #64748b; margin-left: 28px;">
                            Aktivuje nativní OpenMetrics endpoint <code>/metrics</code> na portu Web UI (výchozí 8080) pro sběr telemetrie (latence kamer, propustnost zpráv, chyby firewallu) do Promethea a Grafany. Vypněte, pokud observabilitu v síti nevyužíváte.
                        </div>
                    </div>

                    <!-- Hikvision ISAPI AlertStream Panel -->
                    <div style="margin-bottom: 25px; background: #f8fafc; padding: 18px; border-radius: 8px; border: 1px solid #e2e8f0;">
                        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 12px;">
                            <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                                <input type="checkbox" name="enable_isapi" id="enable_isapi" onchange="toggleIsapiPanel()" <?php echo ($config['ENABLE_ISAPI'] === "True" || $config['ENABLE_ISAPI'] === true) ? 'checked' : ''; ?>>
                                <span style="font-weight: 700; color: #0284c7; font-size: 1.05rem;">⚡ Hikvision ISAPI AlertStream (Ultra-Low Latency &lt; 10 ms)</span>
                            </label>
                            <span style="font-size: 0.8rem; background: #e0f2fe; color: #0369a1; padding: 3px 8px; border-radius: 4px; font-weight: 600;">
                                Hybridní režim: ISAPI (&lt;10ms) + SMTP fallback
                            </span>
                        </div>
                        <div style="font-size: 0.85rem; color: #64748b; margin-bottom: 15px; line-height: 1.5;">
                            Aktivuje přímé permanentní HTTP AlertStream spojení z kamer Hikvision do LoxBerry. Události (Line Crossing, Intrusion, Motion) jsou do MQTT doručovány <b>okamžitě (&lt; 10 ms)</b> bez 35s prodlevy SMTP protokolu. Ostatní kamery a záloha fungují nadále přes vestavěný SMTP server.
                        </div>

                        <div id="isapi-panel-body">
                            <!-- Global Default Credentials -->
                            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 20px; background: white; padding: 12px 14px; border-radius: 6px; border: 1px solid #cbd5e1;">
                                <div>
                                    <label style="display: block; font-weight: 600; margin-bottom: 4px; color: #334155; font-size: 0.88rem;">Výchozí ISAPI Uživatel:</label>
                                    <input type="text" name="isapi_user" id="isapi_user" value="<?php echo htmlspecialchars($config['ISAPI_USER'] ?? 'admin'); ?>" style="width: 100%; padding: 7px; border: 1px solid #cbd5e1; border-radius: 4px; font-size: 0.88rem;">
                                </div>
                                <div>
                                    <label style="display: block; font-weight: 600; margin-bottom: 4px; color: #334155; font-size: 0.88rem;">Výchozí ISAPI Heslo (Digest Auth):</label>
                                    <input type="password" name="isapi_password" id="isapi_password" value="<?php echo htmlspecialchars($config['ISAPI_PASSWORD'] ?? ''); ?>" placeholder="••••••••" style="width: 100%; padding: 7px; border: 1px solid #cbd5e1; border-radius: 4px; font-size: 0.88rem;">
                                </div>
                            </div>

                            <!-- Preset quick buttons -->
                            <div style="display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; align-items: center;">
                                <span style="font-weight: 600; font-size: 0.85rem; color: #475569;">Předvolby kamer:</span>
                                <button type="button" onclick="addPresetIsapiCamera('cam3@nm315.cz', '10.0.40.103', 80)" style="background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; border-radius: 4px; padding: 4px 10px; font-size: 0.82rem; font-weight: 600; cursor: pointer;">+ Cam 3 Vchod (10.0.40.103)</button>
                                <button type="button" onclick="addPresetIsapiCamera('cam4@nm315.cz', '10.0.40.104', 80)" style="background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; border-radius: 4px; padding: 4px 10px; font-size: 0.82rem; font-weight: 600; cursor: pointer;">+ Cam 4 Zahrada (10.0.40.104)</button>
                                <button type="button" onclick="addPresetIsapiCamera('cam2@nm315.cz', '10.0.40.102', 80)" style="background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; border-radius: 4px; padding: 4px 10px; font-size: 0.82rem; font-weight: 600; cursor: pointer;">+ Cam 2 Parking (10.0.40.102)</button>
                            </div>

                            <!-- Camera Table Mode -->
                            <div id="isapi-table-mode">
                                <table id="isapi-cameras-table" style="width: 100%; border-collapse: collapse; background: white; border: 1px solid #cbd5e1; border-radius: 6px; overflow: hidden; margin-bottom: 12px;">
                                    <thead>
                                        <tr style="background: #f8fafc; text-align: left; border-bottom: 1px solid #cbd5e1; font-size: 0.85rem; color: #475569;">
                                            <th style="padding: 10px 12px; width: 26%;">Alias / Sender (MQTT topic)</th>
                                            <th style="padding: 10px 12px; width: 20%;">IP adresa</th>
                                            <th style="padding: 10px 12px; width: 10%;">Port</th>
                                            <th style="padding: 10px 12px; width: 26%;">Live Stav &amp; Diagnostika</th>
                                            <th style="padding: 10px 12px; width: 18%; text-align: center;">Akce</th>
                                        </tr>
                                    </thead>
                                    <tbody id="isapi-cameras-tbody">
                                        <?php if (empty($isapi_cameras_list)): ?>
                                            <tr><td colspan="5" style="text-align: center; color: #94a3b8; padding: 15px; font-style: italic;">Žádné kamery pro přímý ISAPI stream. Klikněte na "+ Přidat kameru" nebo předvolbu výše.</td></tr>
                                        <?php else: ?>
                                            <?php foreach ($isapi_cameras_list as $idx => $cam): 
                                                $senderVal = $cam['sender'] ?? ('cam_' . ($cam['ip'] ?? ''));
                                                $ipVal = $cam['ip'] ?? '';
                                                $portVal = intval($cam['port'] ?? 80);
                                            ?>
                                                <tr style="border-bottom: 1px solid #e2e8f0;">
                                                    <td style="padding: 8px 12px; font-family: monospace; font-weight: 600; color: #0284c7;">
                                                        <input type="text" name="isapi_cam_sender[]" value="<?php echo htmlspecialchars($senderVal); ?>" required oninput="syncIsapiCamerasFromTable()" style="width: 100%; border: 1px solid #cbd5e1; padding: 6px; border-radius: 4px; font-family: monospace; font-size: 0.88rem;">
                                                    </td>
                                                    <td style="padding: 8px 12px; font-family: monospace; font-weight: 600; color: #1e293b;">
                                                        <input type="text" name="isapi_cam_ip[]" value="<?php echo htmlspecialchars($ipVal); ?>" required oninput="syncIsapiCamerasFromTable()" style="width: 100%; border: 1px solid #cbd5e1; padding: 6px; border-radius: 4px; font-family: monospace; font-size: 0.88rem;">
                                                    </td>
                                                    <td style="padding: 8px 12px;">
                                                        <input type="number" name="isapi_cam_port[]" value="<?php echo htmlspecialchars($portVal); ?>" min="1" max="65535" oninput="syncIsapiCamerasFromTable()" style="width: 100%; border: 1px solid #cbd5e1; padding: 6px; border-radius: 4px; font-size: 0.88rem;">
                                                    </td>
                                                    <td style="padding: 8px 12px;" id="isapi-status-<?php echo $idx; ?>">
                                                        <span style="color: #64748b; font-size: 0.85rem;">⚪ Neověřeno</span>
                                                    </td>
                                                    <td style="padding: 8px 12px; text-align: center; white-space: nowrap;">
                                                        <button type="button" onclick="testIsapiCameraDirect(<?php echo $idx; ?>)" style="background: #0284c7; color: white; border: none; border-radius: 4px; padding: 5px 10px; cursor: pointer; font-size: 0.82rem; margin-right: 4px;" title="Testovat ISAPI spojení">🧪 Test</button>
                                                        <button type="button" onclick="removeIsapiCamera(<?php echo $idx; ?>)" style="background: #ef4444; color: white; border: none; border-radius: 4px; padding: 5px 8px; cursor: pointer; font-size: 0.82rem;" title="Smazat kameru">🗑️</button>
                                                    </td>
                                                </tr>
                                            <?php endforeach; ?>
                                        <?php endif; ?>
                                    </tbody>
                                </table>

                                <div style="display: flex; gap: 10px; margin-bottom: 10px; align-items: center; flex-wrap: wrap; background: #f1f5f9; padding: 10px; border-radius: 6px; border: 1px solid #e2e8f0;">
                                    <input type="text" id="new-cam-sender" placeholder="Alias (např. cam3@nm315.cz)" style="flex: 1.2; min-width: 160px; padding: 7px; border: 1px solid #cbd5e1; border-radius: 4px; font-size: 0.85rem;">
                                    <input type="text" id="new-cam-ip" placeholder="IP (např. 10.0.40.103)" style="flex: 1; min-width: 130px; padding: 7px; border: 1px solid #cbd5e1; border-radius: 4px; font-size: 0.85rem;">
                                    <input type="number" id="new-cam-port" value="80" placeholder="Port" style="width: 70px; padding: 7px; border: 1px solid #cbd5e1; border-radius: 4px; font-size: 0.85rem;">
                                    <button type="button" onclick="addCustomIsapiCameraFromInput()" style="background: #0284c7; color: white; border: none; padding: 7px 14px; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 0.85rem;">+ Přidat kameru</button>
                                </div>
                            </div>

                            <!-- Expert Raw Text Mode Toggle -->
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px;">
                                <a href="javascript:void(0)" onclick="toggleIsapiExpertMode()" id="isapi-expert-toggle" style="font-size: 0.85rem; color: #0284c7; text-decoration: underline; font-weight: 600;">⚙️ Přepnout na Expertní surový text (ISAPI_CAMERAS)</a>
                            </div>
                            <div id="isapi-expert-mode" style="display: none; margin-top: 10px;">
                                <input type="text" name="isapi_cameras" id="isapi_cameras" value="<?php echo htmlspecialchars(is_array($config['ISAPI_CAMERAS']) ? json_encode($config['ISAPI_CAMERAS']) : strval($config['ISAPI_CAMERAS'])); ?>" placeholder="10.0.40.103:cam3@nm315.cz, 10.0.40.104:cam4@nm315.cz" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px; font-family: monospace;">
                                <span class="field-hint">Zadejte JSON pole nebo čárkou oddělený seznam <code>IP:sender</code>.</span>
                            </div>
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

                    <!-- Maintenance & Retention -->
                    <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 1rem; border-bottom: 2px solid #f1f8e9; padding-bottom: 6px;">🖼️ Úroveň Logování & Údržba</h4>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 20px;">
                        <div>
                            <label style="display: block; font-weight: 600; margin-bottom: 5px; color: #334155; font-size: 0.9rem;">Úroveň Logování (LoxBerry System LogLevel):</label>
                            <?php $current_loglevel = intval($lbpconfig['PLUGIN']['LOGLEVEL'] ?? $lbpconfig['SYSTEM']['LOGLEVEL'] ?? 4); ?>
                            <select name="plugin_loglevel" style="width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px;">
                                <option value="7" <?php echo ($current_loglevel >= 7) ? 'selected' : ''; ?>>7 - DEBUG (Detailní ladicí výpisy)</option>
                                <option value="4" <?php echo ($current_loglevel == 4) ? 'selected' : ''; ?>>4 - INFO (Běžný provoz - výchozí)</option>
                                <option value="1" <?php echo ($current_loglevel == 1) ? 'selected' : ''; ?>>1 - ERROR (Pouze chyby)</option>
                                <option value="0" <?php echo ($current_loglevel == 0) ? 'selected' : ''; ?>>0 - OFF (Vypnuto)</option>
                            </select>
                        </div>

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
                        <button type="submit" name="save_settings" class="lox-btn-primary">💾 Uložit Nastavení</button>
                        <a href="?action=restart_daemon" class="lox-btn-secondary">🚀 Restartovat Službu</a>
                    </div>
                </form>
            </div>
        </div>

    <?php elseif ($active_tab === 'dashboard'): ?>
        <!-- Live Dashboard & Packet Inspector -->
        <div class="lox-card">
            <div class="lox-card-header">
                <h3 class="lox-card-title">📊 Živý Dashboard & Packet Inspector</h3>
                <div style="display: flex; gap: 10px; align-items: center;">
                    <span id="dash-last-update" style="font-size: 0.82rem; color: #64748b;"></span>
                    <button onclick="refreshDashboardJSON()" class="lox-btn-secondary">🔄 Obnovit</button>
                </div>
            </div>
            <div class="lox-card-body" id="dashboard-body">
                <!-- Status Cards Grid -->
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 16px; margin-bottom: 24px;">
                    <div style="background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 16px;">
                        <div style="font-size: 0.85rem; font-weight: 600; color: #64748b;">📬 SMTP Server</div>
                        <div style="font-size: 1.4rem; font-weight: 800;" id="dash-smtp-status">⏳ Načítání...</div>
                    </div>
                    <div style="background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 16px;">
                        <div style="font-size: 0.85rem; font-weight: 600; color: #64748b;">📡 MQTT Broker</div>
                        <div style="font-size: 1.4rem; font-weight: 800;" id="dash-mqtt-status">⏳ Načítání...</div>
                    </div>
                    <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px;">
                        <div style="font-size: 0.85rem; font-weight: 600; color: #166534;">⚡ ISAPI Stream (&lt;10ms)</div>
                        <div style="font-size: 1.4rem; font-weight: 800; color: #15803d;" id="dash-isapi-status">⏳ Načítání...</div>
                    </div>
                    <div style="background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 8px; padding: 16px;">
                        <div style="font-size: 0.85rem; font-weight: 600; color: #64748b;">⏱️ Uptime</div>
                        <div style="font-size: 1.4rem; font-weight: 800; color: #0369a1;" id="dash-uptime">—</div>
                    </div>
                    <div style="background: #faf5ff; border: 1px solid #e9d5ff; border-radius: 8px; padding: 16px;">
                        <div style="font-size: 0.85rem; font-weight: 600; color: #64748b;">📨 Zpracováno zpráv</div>
                        <div style="font-size: 1.4rem; font-weight: 800; color: #7e22ce;" id="dash-msg-count">0</div>
                    </div>
                </div>

                <!-- Recent Events Table -->
                <h4 style="margin: 0 0 12px 0; color: #2e7d32; font-size: 1rem; border-bottom: 2px solid #f1f8e9; padding-bottom: 6px;">📋 Poslední Zachycené Detekce & Paket Inspector</h4>
                <div style="overflow-x: auto;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 0.88rem;">
                        <thead>
                            <tr style="background: #f8fafc; border-bottom: 2px solid #e2e8f0;">
                                <th style="text-align: left; padding: 10px 12px; width: 14%;">Čas</th>
                                <th style="text-align: left; padding: 10px 12px; width: 14%;">Zdroj / Kanál</th>
                                <th style="text-align: left; padding: 10px 12px; width: 22%;">Druh Detekce</th>
                                <th style="text-align: left; padding: 10px 12px; width: 18%;">Odesílatel (Kamera)</th>
                                <th style="text-align: left; padding: 10px 12px; width: 16%;">MQTT Topic</th>
                                <th style="text-align: left; padding: 10px 12px; width: 8%;">Payload</th>
                                <th style="text-align: left; padding: 10px 12px; width: 8%;">Status</th>
                            </tr>
                        </thead>
                        <tbody id="dash-events-tbody">
                            <tr><td colspan="7" style="text-align: center; padding: 20px; color: #94a3b8;">⏳ Načítání stavu zpráv...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

    <?php elseif ($active_tab === 'logs'): ?>
        <!-- Smart Log Viewer -->
        <div class="lox-card">
            <div class="lox-card-header">
                <h3 class="lox-card-title">📋 Prohlížeč Logů</h3>
                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                    <a href="/admin/system/logmanager.cgi?package=smtp2mqtt" target="_blank" class="lox-btn-secondary" style="padding: 5px 10px; font-size: 0.8rem; background: #0284c7; color: #ffffff; text-decoration: none;">📋 LoxBerry Log Manager</a>
                    <a href="/admin/system/tools/logfile.cgi?logfile=plugins/smtp2mqtt/smtp2mqtt.log&header=html&format=template" target="_blank" class="lox-btn-secondary" style="padding: 5px 10px; font-size: 0.8rem; background: #0d9488; color: #ffffff; text-decoration: none;">🔍 LoxBerry Log Viewer</a>
                    <input type="text" id="log-search" oninput="filterLogLines()" placeholder="🔍 Hledat v logu..." style="padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 4px; font-size: 0.85rem;">
                    <button onclick="setLogLevelFilter('ALL')" class="lox-btn-secondary" style="padding: 5px 10px; font-size: 0.8rem;">Vše</button>
                    <button onclick="setLogLevelFilter('ERROR')" class="lox-btn-secondary" style="padding: 5px 10px; font-size: 0.8rem; color: #dc2626;">🔴 Chyby</button>
                    <button onclick="setLogLevelFilter('WARN')" class="lox-btn-secondary" style="padding: 5px 10px; font-size: 0.8rem; color: #d97706;">🟡 Varování</button>
                    <button onclick="copyLogToClipboard()" class="lox-btn-secondary" style="padding: 5px 10px; font-size: 0.8rem;">📋 Kopírovat</button>
                    <a href="/admin/system/logmanager.php?package=smtp2mqtt" target="_blank" class="lox-btn-secondary" style="padding: 5px 10px; font-size: 0.8rem; background: #e0f2fe; color: #0369a1; border-color: #7dd3fc; text-decoration: none;">🔍 Otevřít v LoxBerry Log Manageru</a>
                    <a href="?action=download_log" class="lox-btn-secondary" style="padding: 5px 10px; font-size: 0.8rem;">📥 Stáhnout</a>
                    <a href="?action=clear_log" onclick="return confirm('Opravdu chcete vyčistit soubor logů?');" class="lox-btn-secondary" style="padding: 5px 10px; font-size: 0.8rem; color: #dc2626;">🧹 Vyčistit</a>
                </div>

            </div>
            <div class="lox-card-body">
                <?php
                if (file_exists($log_file) && filesize($log_file) > 0) {
                    $lines = file($log_file);
                    echo '<div class="log-viewer-box" id="log-box">';
                    foreach ($lines as $line) {
                        $cls = 'log-line-info';
                        if (strpos($line, 'ERROR') !== false) $cls = 'log-line-error';
                        elseif (strpos($line, 'WARN') !== false) $cls = 'log-line-warn';
                        elseif (strpos($line, 'DEBUG') !== false) $cls = 'log-line-debug';
                        echo '<div class="log-item ' . $cls . '">' . htmlspecialchars($line) . '</div>';
                    }
                    echo '</div>';
                } else {
                    echo '<div class="log-viewer-box" id="log-box">Log soubor je zatím prázdný.</div>';
                }
                ?>
            </div>
        </div>

    <?php elseif ($active_tab === 'help'): ?>
        <!-- Zero GitHub Dependency - Inline Interactive Help -->
        <div class="lox-card">
            <div class="lox-card-header">
                <h3 class="lox-card-title">📖 Nápověda, Nastavení Kamer & Loxone Generator</h3>
            </div>
            <div class="lox-card-body" style="line-height: 1.6; color: #334155;">
                
                <p style="background: #f0fdf4; border-left: 4px solid #16a34a; padding: 14px 18px; border-radius: 6px; font-size: 0.95rem; margin-top: 0;">
                    <strong>Jak funguje smtp2mqtt:</strong> Plugin spouští na LoxBerry vestavěný SMTP server (port 1025). Jakákoliv IP kamera v LAN mu při detekci pohybu pošle e-mail. Plugin e-mail okamžitě převede na <strong>MQTT zprávu</strong> pro Loxone a automaticky spustí auto-reset časovač.
                </p>

                <!-- Camera Setup Accordion -->
                <h4 style="color: #2e7d32; margin-top: 25px;">🎥 Přesné Návody Nastavení Kamer</h4>
                
                <div class="accordion-item">
                    <div class="accordion-header" onclick="toggleAccordion('acc-hikvision')">
                        <span>🔴 Hikvision / HiLook / Ezviz</span> <span>▼</span>
                    </div>
                    <div class="accordion-body" id="acc-hikvision">
                        <ol style="padding-left: 20px; line-height: 1.8;">
                            <li>Otevřete webové rozhraní kamery: <strong>Configuration -> Network -> Advanced Settings -> Email</strong>.</li>
                            <li><strong>SMTP Server:</strong> Zadejte IP adresu vašeho LoxBerry (např. <code>192.168.1.100</code>).</li>
                            <li><strong>SMTP Port:</strong> Zadejte <code>1025</code> (nebo port dle vašich nastavení).</li>
                            <li><strong>Authentication & SSL:</strong> Vypněte SSL/TLS i autentizaci (login/heslo zůstanou prázdné).</li>
                            <li><strong>Sender Address:</strong> Zadejte např. <code>kamera.zahrada@domov.local</code>. Z této adresy se automaticky vytvoří MQTT topic <code>smtp2mqtt/kamera_zahrada-domov_local</code>.</li>
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
                    
                    <div style="margin-top: 12px; background: #ffffff; padding: 12px; border: 1px dashed #6fb738; border-radius: 4px;">
                        <strong>MQTT Text In Subscription pro Loxone Config:</strong>
                        <div id="gen-topic-result" style="font-family: monospace; color: #15803d; font-weight: 700; margin-top: 4px; font-size: 1.05rem;">smtp2mqtt/kamera_zahrada-domov_local</div>
                    </div>
                </div>

                <!-- Support & Buy Me a Coffee -->
                <div style="margin-top: 30px; background: linear-gradient(135deg, #fef3c7 0%, #fff7ed 100%); border: 1px solid #fde68a; padding: 20px; border-radius: 8px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px;">
                    <div>
                        <h4 style="margin: 0 0 6px 0; color: #78350f;">☕ Podpořte vývoj projektu smtp2mqtt</h4>
                        <p style="margin: 0; color: #92400e; font-size: 0.9rem;">
                            Tento plugin vyvíjí jako volnočasový open-source projekt <strong>Ondřej Hála</strong> (<a href="mailto:ondrejhala@gmail.com" style="color: #b45309; text-decoration: underline;">ondrejhala@gmail.com</a>).
                            Pokud vám plugin šetří čas nebo zjednodušil chytrý domov, můžete vývoj podpořit kávou!
                        </p>
                    </div>
                    <a href="https://buymeacoffee.com/ondrejhala8" target="_blank" style="background: #ffdd00; color: #000000; font-weight: 700; padding: 10px 18px; border-radius: 8px; text-decoration: none; box-shadow: 0 2px 4px rgba(0,0,0,0.1); display: inline-flex; align-items: center; gap: 8px; font-size: 0.95rem;">
                        <span>☕ Buy Me A Coffee</span>
                    </a>
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

    function readCurrentTableState() {
        const ipInputs = document.querySelectorAll('input[name="rule_ip[]"]');
        const labelInputs = document.querySelectorAll('input[name="rule_label[]"]');
        const updated = [];
        if (ipInputs && ipInputs.length > 0) {
            ipInputs.forEach((inp, i) => {
                const ipVal = inp.value.trim();
                const lblVal = labelInputs[i] ? labelInputs[i].value.trim() : '';
                if (ipVal || lblVal) {
                    updated.push({ ip: ipVal, label: lblVal });
                }
            });
            return updated;
        }
        return firewallRules;
    }

    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    }

    function addFirewallRule(ip, label = '') {
        firewallRules = readCurrentTableState();
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
        firewallRules = readCurrentTableState();
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
            firewallRules = readCurrentTableState();
            syncAllowedIpsFromTable();
            tableMode.querySelectorAll('input, select').forEach(el => el.disabled = true);
            tableMode.style.display = 'none';
            expertMode.style.display = 'block';
            if (toggleBtn) toggleBtn.textContent = '📋 Přepnout na Vizuální Tabulkový Manažer';
        } else {
            const rawVal = document.getElementById('allowed_ips')?.value || '';
            const parts = rawVal.split(',').map(p => p.trim()).filter(p => p.length > 0);
            const oldRules = readCurrentTableState();
            firewallRules = parts.map(p => {
                const existing = oldRules.find(r => r.ip === p);
                return { ip: p, label: existing ? existing.label : '' };
            });
            tableMode.querySelectorAll('input, select').forEach(el => el.disabled = false);
            renderFirewallTable();
            expertMode.style.display = 'none';
            tableMode.style.display = 'block';
            if (toggleBtn) toggleBtn.textContent = '⚙️ Přepnout na Expertní surový text (ALLOWED_IPS)';
        }
    }

    // ISAPI Cameras Table Management
    let isapiCameras = <?php echo json_encode(array_values($isapi_cameras_list ?? [])); ?>;
    if (typeof isapiCameras === 'string') {
        try {
            isapiCameras = JSON.parse(isapiCameras);
            if (typeof isapiCameras === 'string') isapiCameras = JSON.parse(isapiCameras);
        } catch(e) {
            isapiCameras = [];
        }
    }
    if (!Array.isArray(isapiCameras)) {
        isapiCameras = [];
    }

    function renderIsapiTable() {
        const tbody = document.getElementById('isapi-cameras-tbody');
        if (!tbody) return;
        tbody.innerHTML = '';

        if (!Array.isArray(isapiCameras) || isapiCameras.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: #94a3b8; padding: 15px; font-style: italic;">Žádné kamery pro přímý ISAPI stream. Klikněte na "+ Přidat kameru" nebo předvolbu výše.</td></tr>`;
            syncIsapiCamerasFromTable();
            return;
        }

        isapiCameras.forEach((cam, idx) => {
            const tr = document.createElement('tr');
            tr.style.borderBottom = '1px solid #e2e8f0';
            const senderVal = cam.sender || ('cam_' + (cam.ip || ''));
            const ipVal = cam.ip || '';
            const portVal = cam.port || 80;

            tr.innerHTML = `
                <td style="padding: 8px 12px; font-family: monospace; font-weight: 600; color: #0284c7;">
                    <input type="text" name="isapi_cam_sender[]" value="${escapeHtml(senderVal)}" required oninput="syncIsapiCamerasFromTable()" style="width: 100%; border: 1px solid #cbd5e1; padding: 6px; border-radius: 4px; font-family: monospace; font-size: 0.88rem;">
                </td>
                <td style="padding: 8px 12px; font-family: monospace; font-weight: 600; color: #1e293b;">
                    <input type="text" name="isapi_cam_ip[]" value="${escapeHtml(ipVal)}" required oninput="syncIsapiCamerasFromTable()" style="width: 100%; border: 1px solid #cbd5e1; padding: 6px; border-radius: 4px; font-family: monospace; font-size: 0.88rem;">
                </td>
                <td style="padding: 8px 12px;">
                    <input type="number" name="isapi_cam_port[]" value="${escapeHtml(portVal)}" min="1" max="65535" oninput="syncIsapiCamerasFromTable()" style="width: 100%; border: 1px solid #cbd5e1; padding: 6px; border-radius: 4px; font-size: 0.88rem;">
                </td>
                <td style="padding: 8px 12px;" id="isapi-status-${idx}">
                    <span style="color: #64748b; font-size: 0.85rem;">⚪ Neověřeno</span>
                </td>
                <td style="padding: 8px 12px; text-align: center; white-space: nowrap;">
                    <button type="button" onclick="testIsapiCameraDirect(${idx})" style="background: #0284c7; color: white; border: none; border-radius: 4px; padding: 5px 10px; cursor: pointer; font-size: 0.82rem; margin-right: 4px;" title="Testovat ISAPI spojení">🧪 Test</button>
                    <button type="button" onclick="removeIsapiCamera(${idx})" style="background: #ef4444; color: white; border: none; border-radius: 4px; padding: 5px 8px; cursor: pointer; font-size: 0.82rem;" title="Smazat kameru">🗑️</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
        syncIsapiCamerasFromTable();
    }

    function readCurrentIsapiTableState() {
        const ipInputs = document.querySelectorAll('input[name="isapi_cam_ip[]"]');
        const senderInputs = document.querySelectorAll('input[name="isapi_cam_sender[]"]');
        const portInputs = document.querySelectorAll('input[name="isapi_cam_port[]"]');
        const updated = [];
        if (ipInputs && ipInputs.length > 0) {
            ipInputs.forEach((inp, i) => {
                const ipVal = inp.value.trim();
                const senderVal = senderInputs[i] ? senderInputs[i].value.trim() : ('cam_' + ipVal);
                const portVal = portInputs[i] ? parseInt(portInputs[i].value.trim()) || 80 : 80;
                if (ipVal) {
                    updated.push({ ip: ipVal, sender: senderVal, port: portVal });
                }
            });
            return updated;
        }
        return isapiCameras;
    }

    function syncIsapiCamerasFromTable() {
        const list = readCurrentIsapiTableState();
        const rawInput = document.getElementById('isapi_cameras');
        if (rawInput) {
            rawInput.value = JSON.stringify(list);
        }
    }

    function addIsapiCamera(sender, ip, port = 80) {
        isapiCameras = readCurrentIsapiTableState();
        ip = (ip || '').trim();
        sender = (sender || '').trim() || ('cam_' + ip);
        if (!ip) return;
        const existing = isapiCameras.find(c => c.ip === ip || c.sender === sender);
        if (existing) {
            showToast('⚠️ Kamera s IP ' + ip + ' nebo aliasem ' + sender + ' již v seznamu existuje.', false);
            return;
        }
        isapiCameras.push({ sender: sender, ip: ip, port: port });
        renderIsapiTable();
        showToast('✅ Kamera ' + sender + ' (' + ip + ') přidána.', true);
    }

    function addPresetIsapiCamera(sender, ip, port = 80) {
        addIsapiCamera(sender, ip, port);
    }

    function removeIsapiCamera(idx) {
        isapiCameras = readCurrentIsapiTableState();
        if (idx >= 0 && idx < isapiCameras.length) {
            isapiCameras.splice(idx, 1);
            renderIsapiTable();
        }
    }

    function addCustomIsapiCameraFromInput() {
        const senderInput = document.getElementById('new-cam-sender');
        const ipInput = document.getElementById('new-cam-ip');
        const portInput = document.getElementById('new-cam-port');
        const ip = ipInput ? ipInput.value.trim() : '';
        const sender = senderInput ? senderInput.value.trim() : '';
        const port = portInput ? parseInt(portInput.value.trim()) || 80 : 80;

        if (!ip) {
            showToast('Zadejte prosím IP adresu kamery.', false);
            return;
        }
        addIsapiCamera(sender, ip, port);
        if (senderInput) senderInput.value = '';
        if (ipInput) ipInput.value = '';
    }

    function testIsapiCameraDirect(idx) {
        const ips = document.querySelectorAll('input[name="isapi_cam_ip[]"]');
        const ports = document.querySelectorAll('input[name="isapi_cam_port[]"]');
        const statusCell = document.getElementById('isapi-status-' + idx);
        if (!ips[idx] || !statusCell) return;

        const ip = ips[idx].value.trim();
        const port = ports[idx] ? parseInt(ports[idx].value.trim()) || 80 : 80;
        const globalUser = document.getElementById('isapi_user')?.value || 'admin';
        const globalPass = document.getElementById('isapi_password')?.value || '';

        statusCell.innerHTML = '<span style="color: #0284c7; font-size: 0.85rem;">⏳ Testuji...</span>';

        fetch(`?_ajax=probe_camera&ip=${encodeURIComponent(ip)}&port=${port}&user=${encodeURIComponent(globalUser)}&password=${encodeURIComponent(globalPass)}`)
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    statusCell.innerHTML = `<span style="color: #15803d; font-size: 0.85rem; font-weight: 600;" title="${escapeHtml(data.message || '')}">🟢 OK (${escapeHtml(data.model || 'Hikvision')}, ${data.latency_ms}ms)</span>`;
                    showToast(`✅ Kamera ${ip} je online (${data.model}, FW: ${data.firmware})`, true);
                } else {
                    statusCell.innerHTML = `<span style="color: #b91c1c; font-size: 0.85rem; font-weight: 600;" title="${escapeHtml(data.error || '')}">🔴 Chyba (${escapeHtml(data.error || 'Nedostupná')})</span>`;
                    showToast(`❌ Test kamery ${ip} selhal: ${data.error}`, false);
                }
            })
            .catch(err => {
                statusCell.innerHTML = `<span style="color: #b91c1c; font-size: 0.85rem;">🔴 Chyba sítě</span>`;
                showToast('Chyba při volání testu kamery', false);
            });
    }

    function toggleIsapiPanel() {
        const isEnabled = document.getElementById('enable_isapi')?.checked;
        const panelBody = document.getElementById('isapi-panel-body');
        if (panelBody) {
            panelBody.style.opacity = isEnabled ? '1' : '0.45';
            panelBody.style.pointerEvents = isEnabled ? 'auto' : 'none';
        }
    }

    function toggleIsapiExpertMode() {
        const tableMode = document.getElementById('isapi-table-mode');
        const expertMode = document.getElementById('isapi-expert-mode');
        const toggleBtn = document.getElementById('isapi-expert-toggle');
        if (!tableMode || !expertMode) return;

        if (expertMode.style.display === 'none' || expertMode.style.display === '') {
            isapiCameras = readCurrentIsapiTableState();
            syncIsapiCamerasFromTable();
            tableMode.querySelectorAll('input, select').forEach(el => el.disabled = true);
            tableMode.style.display = 'none';
            expertMode.style.display = 'block';
            if (toggleBtn) toggleBtn.textContent = '📋 Přepnout na Vizuální Tabulkový Manažer';
        } else {
            const rawVal = document.getElementById('isapi_cameras')?.value || '';
            try {
                let parsed = JSON.parse(rawVal);
                if (typeof parsed === 'string') parsed = JSON.parse(parsed);
                if (Array.isArray(parsed)) isapiCameras = parsed;
            } catch(e) {
                const parts = rawVal.split(',').map(p => p.trim()).filter(p => p.length > 0);
                isapiCameras = parts.map(p => {
                    const sub = p.split(':');
                    return { ip: sub[0], port: sub[1] ? parseInt(sub[1]) : 80, sender: sub[2] || ('cam_' + sub[0]) };
                });
            }
            tableMode.querySelectorAll('input, select').forEach(el => el.disabled = false);
            renderIsapiTable();
            expertMode.style.display = 'none';
            tableMode.style.display = 'block';
            if (toggleBtn) toggleBtn.textContent = '⚙️ Přepnout na Expertní surový text (ISAPI_CAMERAS)';
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

                const smtpEl = document.getElementById('dash-smtp-status');
                if (smtpEl) {
                    smtpEl.textContent = data.status?.smtp_connected ? '🟢 Active' : '🔴 Inactive';
                    smtpEl.style.color = data.status?.smtp_connected ? '#15803d' : '#b91c1c';
                }

                const mqttEl = document.getElementById('dash-mqtt-status');
                if (mqttEl) {
                    mqttEl.textContent = data.status?.mqtt_connected ? '🟢 Connected' : '🔴 Disconnected';
                    mqttEl.style.color = data.status?.mqtt_connected ? '#15803d' : '#b91c1c';
                }

                const isapiEl = document.getElementById('dash-isapi-status');
                if (isapiEl) {
                    if (data.status?.isapi_enabled) {
                        const streams = data.status.isapi_status || {};
                        const total = Object.keys(streams).length;
                        const live = Object.values(streams).filter(s => s.status === 'connected').length;
                        if (total === 0) {
                            isapiEl.textContent = '⚪ Žádné kamery';
                            isapiEl.style.color = '#64748b';
                        } else if (live === total) {
                            isapiEl.textContent = `🟢 ${live}/${total} Live`;
                            isapiEl.style.color = '#15803d';
                        } else {
                            isapiEl.textContent = `🟡 ${live}/${total} Live`;
                            isapiEl.style.color = '#d97706';
                        }
                    } else {
                        isapiEl.textContent = '⚪ Vypnuto';
                        isapiEl.style.color = '#94a3b8';
                    }
                }

                const uptimeEl = document.getElementById('dash-uptime');
                if (uptimeEl) uptimeEl.textContent = data.status?.uptime_formatted || '—';

                const msgEl = document.getElementById('dash-msg-count');
                if (msgEl) msgEl.textContent = data.status?.processed_messages_count || '0';

                const tbody = document.getElementById('dash-events-tbody');
                if (tbody && data.status?.recent_actions) {
                    if (data.status.recent_actions.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 20px; color: #94a3b8;">Zatím nebyly zaznamenány žádné události.</td></tr>';
                    } else {
                        tbody.innerHTML = data.status.recent_actions.map(act => {
                            const icon = act.event_icon || (act.type === 'trigger' ? '⚡' : (act.type === 'reset' ? '🔄' : (act.type === 'system' ? '⚙️' : 'ℹ️')));
                            const label = act.event_label || act.type || '';
                            const senderDisplay = act.sender ? act.sender : 'system';
                            const targetStr = act.event_details && act.event_details.target_type && act.event_details.target_type !== 'unknown' ? ` <span style="font-size: 0.72rem; opacity: 0.85; background: rgba(111,183,56,0.15); color: #15803d; padding: 1px 5px; border-radius: 4px; font-weight: 600;">${act.event_details.target_type}</span>` : '';
                            
                            let sourceBadge = '';
                            const src = act.source || act.event_details?.source || (act.type === 'reset' ? 'reset' : 'smtp');
                            if (src === 'isapi') {
                                sourceBadge = '<span style="background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; padding: 2px 7px; border-radius: 4px; font-weight: 700; font-size: 0.76rem; display: inline-flex; align-items: center; gap: 4px;">⚡ ISAPI (&lt;10ms)</span>';
                            } else if (src === 'smtp') {
                                sourceBadge = '<span style="background: #f8fafc; color: #334155; border: 1px solid #cbd5e1; padding: 2px 7px; border-radius: 4px; font-weight: 600; font-size: 0.76rem; display: inline-flex; align-items: center; gap: 4px;">✉️ SMTP Email</span>';
                            } else if (src === 'reset') {
                                sourceBadge = '<span style="background: #fffbeb; color: #b45309; border: 1px solid #fde68a; padding: 2px 7px; border-radius: 4px; font-weight: 600; font-size: 0.76rem; display: inline-flex; align-items: center; gap: 4px;">🔄 Auto-Reset</span>';
                            } else {
                                sourceBadge = '<span style="background: #f1f5f9; color: #475569; border: 1px solid #e2e8f0; padding: 2px 7px; border-radius: 4px; font-weight: 600; font-size: 0.76rem;">⚙️ Systém</span>';
                            }

                            return `
                            <tr style="border-bottom: 1px solid #f1f5f9;">
                                <td style="padding: 8px 12px; font-family: monospace; font-size: 0.82rem;">${act.timestamp || ''}</td>
                                <td style="padding: 8px 12px;">${sourceBadge}</td>
                                <td style="padding: 8px 12px;"><span class="lox-badge-info" style="display: inline-flex; align-items: center; gap: 5px;"><span>${icon}</span> <strong>${label}</strong>${targetStr}</span></td>
                                <td style="padding: 8px 12px; font-family: monospace; font-size: 0.85rem;">${senderDisplay}</td>
                                <td style="padding: 8px 12px; font-family: monospace; font-size: 0.85rem; color: #0369a1;">${act.topic || ''}</td>
                                <td style="padding: 8px 12px; font-weight: 600;">${act.payload || ''}</td>
                                <td style="padding: 8px 12px;"><span class="${act.status === 'SUCCESS' ? 'lox-badge-success' : 'lox-badge-danger'}">${act.status || ''}</span></td>
                            </tr>
                        `}).join('');
                    }
                }
            })
            .catch(() => {});
    }

    function filterLogLines() {
        const search = document.getElementById('log-search')?.value.toLowerCase();
        const items = document.querySelectorAll('#log-box .log-item');
        items.forEach(item => {
            const txt = item.textContent.toLowerCase();
            item.style.display = txt.includes(search) ? 'block' : 'none';
        });
    }

    function setLogLevelFilter(level) {
        const items = document.querySelectorAll('#log-box .log-item');
        items.forEach(item => {
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
        renderIsapiTable();
        toggleIsapiPanel();
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

<?php
LBWeb::lbfooter();
?>
