#!/bin/bash
# LoxBerry Pre-Remove Script for smtp2mqtt
echo "<INFO> Stopping smtp2mqtt service before removal..."
pkill -f "smtp2mqtt.py" 2>/dev/null || true
exit 0
