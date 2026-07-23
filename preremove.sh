#!/bin/bash
# LoxBerry Pre-Remove Script for smtp2mqtt

SUDO_CMD=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
    SUDO_CMD="sudo"
fi

echo "<INFO> Stopping and disabling smtp2mqtt service..."
$SUDO_CMD systemctl stop smtp2mqtt.service 2>/dev/null || true
$SUDO_CMD systemctl disable smtp2mqtt.service 2>/dev/null || true
$SUDO_CMD rm -f /etc/systemd/system/smtp2mqtt.service 2>/dev/null || true
$SUDO_CMD systemctl daemon-reload 2>/dev/null || true

exit 0

