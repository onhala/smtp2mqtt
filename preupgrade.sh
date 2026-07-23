#!/bin/bash
# LoxBerry Pre-Upgrade Script for smtp2mqtt

SUDO_CMD=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
    SUDO_CMD="sudo"
fi

echo "<INFO> Stopping smtp2mqtt service before upgrade..."
$SUDO_CMD systemctl stop smtp2mqtt.service 2>/dev/null || true

exit 0

