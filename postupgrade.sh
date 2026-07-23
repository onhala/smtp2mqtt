#!/bin/bash
# LoxBerry Post-Upgrade Script for smtp2mqtt

PLUGIN_DIR="${5:-/opt/loxberry/bin/plugins/smtp2mqtt}"

echo "<INFO> Re-installing dependencies and restarting service after upgrade..."
if [ -f "$PLUGIN_DIR/postinstall.sh" ]; then
    bash "$PLUGIN_DIR/postinstall.sh" "$1" "$2" "$3" "$4" "$5"
else
    systemctl daemon-reload 2>/dev/null || true
    systemctl restart smtp2mqtt.service 2>/dev/null || true
fi

exit 0

