#!/bin/bash
# LoxBerry Post-Upgrade Script for smtp2mqtt
PLUGIN_DIR="${5:-/opt/loxberry/bin/plugins/smtp2mqtt}"

if [ -f "$PLUGIN_DIR/bin/smtp2mqtt.py" ] && [ ! -f "$PLUGIN_DIR/smtp2mqtt.py" ]; then
    cp "$PLUGIN_DIR/bin/smtp2mqtt.py" "$PLUGIN_DIR/smtp2mqtt.py"
fi
if [ -f "$PLUGIN_DIR/smtp2mqtt.py" ] && [ ! -f "$PLUGIN_DIR/bin/smtp2mqtt.py" ]; then
    mkdir -p "$PLUGIN_DIR/bin"
    cp "$PLUGIN_DIR/smtp2mqtt.py" "$PLUGIN_DIR/bin/smtp2mqtt.py"
fi
chmod +x "$PLUGIN_DIR/smtp2mqtt.py" 2>/dev/null || true
chmod +x "$PLUGIN_DIR/bin/smtp2mqtt.py" 2>/dev/null || true

echo "<INFO> Restarting smtp2mqtt daemon process after upgrade..."
DAEMON="$PLUGIN_DIR/smtp2mqtt.py"
if [ ! -f "$DAEMON" ]; then
    DAEMON="$PLUGIN_DIR/bin/smtp2mqtt.py"
fi
pkill -f "smtp2mqtt.py" 2>/dev/null || true
sleep 1
nohup python3 "$DAEMON" > /dev/null 2>&1 &

echo "<OK> smtp2mqtt upgrade completed successfully."
exit 0
