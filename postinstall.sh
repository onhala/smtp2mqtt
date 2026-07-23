#!/bin/bash
# LoxBerry Post-Installation Script for smtp2mqtt

PLUGIN_DIR="${5:-/opt/loxberry/bin/plugins/smtp2mqtt}"

echo "<INFO> Creating plugin directories for logs, data, and config..."
mkdir -p /opt/loxberry/log/plugins/smtp2mqtt
mkdir -p /opt/loxberry/data/plugins/smtp2mqtt
mkdir -p /opt/loxberry/config/plugins/smtp2mqtt

echo "<INFO> Installing system dependencies via APT..."
apt-get update -q || true
apt-get install -y python3-pip python3-aiosmtpd python3-paho-mqtt python3-pil 2>/dev/null || true

echo "<INFO> Installing Python dependencies for smtp2mqtt via pip..."
if [ -f "$PLUGIN_DIR/requirements.txt" ]; then
    pip3 install --break-system-packages -r "$PLUGIN_DIR/requirements.txt" 2>/dev/null || \
    python3 -m pip install --break-system-packages -r "$PLUGIN_DIR/requirements.txt" 2>/dev/null || true
fi

echo "<INFO> Ensuring executable script exists in plugin directory..."
if [ -f "$PLUGIN_DIR/bin/smtp2mqtt.py" ] && [ ! -f "$PLUGIN_DIR/smtp2mqtt.py" ]; then
    cp "$PLUGIN_DIR/bin/smtp2mqtt.py" "$PLUGIN_DIR/smtp2mqtt.py"
fi
if [ -f "$PLUGIN_DIR/smtp2mqtt.py" ] && [ ! -f "$PLUGIN_DIR/bin/smtp2mqtt.py" ]; then
    mkdir -p "$PLUGIN_DIR/bin"
    cp "$PLUGIN_DIR/smtp2mqtt.py" "$PLUGIN_DIR/bin/smtp2mqtt.py"
fi

echo "<INFO> Setting executable permissions..."
chmod +x "$PLUGIN_DIR/smtp2mqtt.py" 2>/dev/null || true
chmod +x "$PLUGIN_DIR/bin/smtp2mqtt.py" 2>/dev/null || true

echo "<INFO> Starting smtp2mqtt daemon process..."
DAEMON="$PLUGIN_DIR/smtp2mqtt.py"
if [ ! -f "$DAEMON" ]; then
    DAEMON="$PLUGIN_DIR/bin/smtp2mqtt.py"
fi
pkill -f "smtp2mqtt.py" 2>/dev/null || true
sleep 1
nohup python3 "$DAEMON" > /dev/null 2>&1 &

echo "<OK> smtp2mqtt post-installation completed successfully."
exit 0
