#!/bin/bash
# LoxBerry Post-Installation Script for smtp2mqtt

# Environment variables supplied by LoxBerry installer:
# $5 ($ARGV5) = Plugin directory path (/opt/loxberry/bin/plugins/smtp2mqtt)

echo "<INFO> Installing Python dependencies for smtp2mqtt..."
if [ -f "$5/requirements.txt" ]; then
    pip3 install -r "$5/requirements.txt" 2>/dev/null || pip install -r "$5/requirements.txt"
fi

echo "<INFO> Setting executable permissions..."
chmod +x "$5/smtp2mqtt.py" 2>/dev/null || true
chmod +x "$5/bin/smtp2mqtt.py" 2>/dev/null || true

echo "<OK> smtp2mqtt post-installation completed successfully."
exit 0
