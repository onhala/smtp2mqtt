<?php
/**
 * Mock LoxBerry Web SDK for automated testing without real LoxBerry hardware.
 */

if (!class_exists('LBSystem')) {
    class LBSystem {
        public static function readlanguage($file = "language.ini") {
            return [
                'TAB_SETTINGS' => '⚙️ Nastavení Pluginu',
                'TAB_DASHBOARD' => '📊 Živý Dashboard',
                'TAB_LOGS' => '📋 Prohlížeč Logů',
                'TAB_HELP' => '📖 Nápověda & Průvodce',
                'TITLE' => 'SMTP to MQTT Bridge',
                'BTN_SAVE' => '💾 Uložit Nastavení',
                'BTN_RESTART_DAEMON' => '🚀 Spustit / Restartovat Službu'
            ];
        }
    }
}

if (!class_exists('LBWeb')) {
    class LBWeb {
        public static function lbheader($title = "", $helplink = "", $helptemplate = "") {
            echo "<!-- MOCK_LOXBERRY_HEADER title=" . htmlspecialchars($title) . " -->\n";
        }

        public static function lbfooter() {
            echo "<!-- MOCK_LOXBERRY_FOOTER -->\n";
        }
    }
}

// Global LoxBerry path mocks
$lbpconfigdir = getenv('LBPCONFIG_DIR') ?: sys_get_temp_dir() . "/loxberry_config";
$lbpdatadir = getenv('LBPDATA_DIR') ?: sys_get_temp_dir() . "/loxberry_data";
$lbplogdir = getenv('LBPLOG_DIR') ?: sys_get_temp_dir() . "/loxberry_log";
$lbpbindir = getenv('LBPBIN_DIR') ?: sys_get_temp_dir() . "/loxberry_bin";
$lbsysconfigdir = getenv('LBSYSCONFIG_DIR') ?: sys_get_temp_dir() . "/loxberry_sysconfig";

$lbpconfig = [
    'BASE' => ['LANG' => 'cs'],
    'PLUGIN' => [
        'NAME' => 'smtp2mqtt',
        'FOLDER' => 'smtp2mqtt',
        'VERSION' => '1.8.18',
        'TITLE' => 'SMTP to MQTT Bridge'
    ]
];

@mkdir($lbpconfigdir, 0777, true);
@mkdir($lbpdatadir, 0777, true);
@mkdir($lbplogdir, 0777, true);
@mkdir($lbpbindir, 0777, true);
@mkdir($lbsysconfigdir, 0777, true);
