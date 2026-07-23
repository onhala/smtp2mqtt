#!/bin/bash
# LoxBerry Pre-Upgrade Script for smtp2mqtt
echo "<INFO> Stopping smtp2mqtt service before upgrade..."
pkill -f "smtp2mqtt.py" 2>/dev/null || true
exit 0
