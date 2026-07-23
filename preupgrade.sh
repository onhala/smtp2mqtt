#!/bin/bash
# LoxBerry Pre-Upgrade Script for smtp2mqtt

echo "<INFO> Stopping smtp2mqtt service before upgrade..."
systemctl stop smtp2mqtt.service 2>/dev/null || true

exit 0

