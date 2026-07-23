#!/bin/bash
# LoxBerry Pre-Remove Script for smtp2mqtt

echo "<INFO> Stopping and disabling smtp2mqtt service..."
systemctl stop smtp2mqtt.service 2>/dev/null || true
systemctl disable smtp2mqtt.service 2>/dev/null || true
rm -f /etc/systemd/system/smtp2mqtt.service 2>/dev/null || true
systemctl daemon-reload 2>/dev/null || true

exit 0

