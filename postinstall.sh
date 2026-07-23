#!/bin/bash
# LoxBerry Post-Installation Script for smtp2mqtt

# Environment variables supplied by LoxBerry installer:
# $5 ($ARGV5) = Plugin directory path (/opt/loxberry/bin/plugins/smtp2mqtt)
PLUGIN_DIR="${5:-/opt/loxberry/bin/plugins/smtp2mqtt}"

echo "<INFO> Installing Python dependencies for smtp2mqtt..."
if [ -f "$PLUGIN_DIR/requirements.txt" ]; then
    pip3 install -r "$PLUGIN_DIR/requirements.txt" 2>/dev/null || pip install -r "$PLUGIN_DIR/requirements.txt"
fi

echo "<INFO> Setting executable permissions..."
chmod +x "$PLUGIN_DIR/smtp2mqtt.py" 2>/dev/null || true

echo "<INFO> Configuring systemd daemon for smtp2mqtt..."
SERVICE_FILE="/etc/systemd/system/smtp2mqtt.service"

SUDO_CMD=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
    SUDO_CMD="sudo"
fi

$SUDO_CMD tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=smtp2mqtt Bridge Daemon for LoxBerry
After=network.target

[Service]
Type=simple
User=loxberry
WorkingDirectory=$PLUGIN_DIR
ExecStart=/usr/bin/python3 $PLUGIN_DIR/smtp2mqtt.py
Restart=always
RestartSec=10
Environment=LBHOME=/opt/loxberry
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

$SUDO_CMD chmod 644 "$SERVICE_FILE" 2>/dev/null || true
$SUDO_CMD systemctl daemon-reload 2>/dev/null || true
$SUDO_CMD systemctl enable smtp2mqtt.service 2>/dev/null || true
$SUDO_CMD systemctl restart smtp2mqtt.service 2>/dev/null || true

echo "<OK> smtp2mqtt post-installation completed successfully."
exit 0

