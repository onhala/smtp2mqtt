#!/bin/bash
# LoxBerry Post-Installation Script for smtp2mqtt

# Environment variables supplied by LoxBerry installer:
# $5 ($ARGV5) = Plugin directory path (/opt/loxberry/bin/plugins/smtp2mqtt)
PLUGIN_DIR="${5:-/opt/loxberry/bin/plugins/smtp2mqtt}"

echo "<INFO> Creating plugin directories for logs, data, and config..."
mkdir -p /opt/loxberry/log/plugins/smtp2mqtt
mkdir -p /opt/loxberry/data/plugins/smtp2mqtt
mkdir -p /opt/loxberry/config/plugins/smtp2mqtt
chown -R loxberry:loxberry /opt/loxberry/log/plugins/smtp2mqtt 2>/dev/null || true
chown -R loxberry:loxberry /opt/loxberry/data/plugins/smtp2mqtt 2>/dev/null || true
chown -R loxberry:loxberry /opt/loxberry/config/plugins/smtp2mqtt 2>/dev/null || true

echo "<INFO> Installing Python dependencies for smtp2mqtt..."
if [ -f "$PLUGIN_DIR/requirements.txt" ]; then
    pip3 install --break-system-packages -r "$PLUGIN_DIR/requirements.txt" || \
    pip3 install -r "$PLUGIN_DIR/requirements.txt" || \
    python3 -m pip install --break-system-packages -r "$PLUGIN_DIR/requirements.txt" || \
    python3 -m pip install -r "$PLUGIN_DIR/requirements.txt" || true
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

echo "<INFO> Configuring sudoers NOPASSWD permissions for LoxBerry user..."
SUDOERS_FILE="/etc/sudoers.d/smtp2mqtt"
$SUDO_CMD tee "$SUDOERS_FILE" > /dev/null << EOF
loxberry ALL=(ALL) NOPASSWD: /bin/systemctl restart smtp2mqtt.service, /bin/systemctl start smtp2mqtt.service, /bin/systemctl stop smtp2mqtt.service, /bin/systemctl status smtp2mqtt.service, /usr/bin/systemctl restart smtp2mqtt.service, /usr/bin/systemctl start smtp2mqtt.service, /usr/bin/systemctl stop smtp2mqtt.service, /usr/bin/systemctl status smtp2mqtt.service, /bin/journalctl, /usr/bin/journalctl
EOF
$SUDO_CMD chmod 0440 "$SUDOERS_FILE" 2>/dev/null || true

$SUDO_CMD systemctl daemon-reload 2>/dev/null || true
$SUDO_CMD systemctl enable smtp2mqtt.service 2>/dev/null || true
$SUDO_CMD systemctl restart smtp2mqtt.service 2>/dev/null || true

echo "<OK> smtp2mqtt post-installation completed successfully."
exit 0

