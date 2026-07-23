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

cat << EOF > "$SERVICE_FILE"
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

chmod 644 "$SERVICE_FILE"
systemctl daemon-reload 2>/dev/null || true
systemctl enable smtp2mqtt.service 2>/dev/null || true
systemctl restart smtp2mqtt.service 2>/dev/null || true

echo "<OK> smtp2mqtt post-installation completed successfully."
exit 0

