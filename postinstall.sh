#!/bin/bash
# LoxBerry Post-Installation Script for smtp2mqtt

PLUGIN_DIR="${5:-/opt/loxberry/bin/plugins/smtp2mqtt}"

echo "<INFO> Creating plugin directories for logs, data, and config..."
mkdir -p /opt/loxberry/log/plugins/smtp2mqtt
mkdir -p /opt/loxberry/data/plugins/smtp2mqtt
mkdir -p /opt/loxberry/config/plugins/smtp2mqtt

echo "<INFO> Installing Python dependencies for smtp2mqtt..."
if [ -f "$PLUGIN_DIR/requirements.txt" ]; then
    pip3 install --user --break-system-packages -r "$PLUGIN_DIR/requirements.txt" || \
    pip3 install --user -r "$PLUGIN_DIR/requirements.txt" || \
    pip3 install --break-system-packages -r "$PLUGIN_DIR/requirements.txt" || \
    pip3 install -r "$PLUGIN_DIR/requirements.txt" || \
    python3 -m pip install --user --break-system-packages -r "$PLUGIN_DIR/requirements.txt" || \
    python3 -m pip install --break-system-packages -r "$PLUGIN_DIR/requirements.txt" || true
fi

echo "<INFO> Setting executable permissions..."
chmod +x "$PLUGIN_DIR/smtp2mqtt.py" 2>/dev/null || true

echo "<INFO> Starting smtp2mqtt daemon process..."
pkill -f "smtp2mqtt.py" 2>/dev/null || true
sleep 1
nohup python3 "$PLUGIN_DIR/smtp2mqtt.py" > /dev/null 2>&1 &

echo "<OK> smtp2mqtt post-installation completed successfully."
exit 0
