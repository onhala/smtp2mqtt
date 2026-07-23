#!/bin/bash
# LoxBerry Post-Upgrade Script for smtp2mqtt
PLUGIN_DIR="${5:-/opt/loxberry/bin/plugins/smtp2mqtt}"

echo "<INFO> Restarting smtp2mqtt daemon process after upgrade..."
pkill -f "smtp2mqtt.py" 2>/dev/null || true
sleep 1
nohup python3 "$PLUGIN_DIR/smtp2mqtt.py" > /dev/null 2>&1 &

echo "<OK> smtp2mqtt upgrade completed successfully."
exit 0
