#!/bin/bash
# LoxBerry Pre-Upgrade Script for smtp2mqtt

if [ -f /etc/environment ]; then
    . /etc/environment
fi

LB_HOME="${5:-${LBHOMEDIR:-$HOME}}"
PDIR="${3:-${2:-smtp2mqtt}}"

if [ -n "$LBPCONFIG" ]; then
    LBPCONFIG_DIR="$LBPCONFIG"
else
    LBPCONFIG_DIR="${LB_HOME}/config/plugins/$PDIR"
fi

if [ -n "$LBPDATA" ]; then
    LBPDATA_DIR="$LBPDATA"
else
    LBPDATA_DIR="${LB_HOME}/data/plugins/$PDIR"
fi

echo "<INFO> Stopping smtp2mqtt service before upgrade..."
pkill -f "smtp2mqtt.py" 2>/dev/null || true

# Back up user configuration to preserve settings across upgrades
mkdir -p "$LBPDATA_DIR"
if [ -f "$LBPCONFIG_DIR/config.json" ]; then
    echo "<INFO> Backing up user config.json from $LBPCONFIG_DIR/config.json to $LBPDATA_DIR/config.json.bak"
    cp "$LBPCONFIG_DIR/config.json" "$LBPDATA_DIR/config.json.bak"
elif [ -f "/opt/loxberry/config/plugins/smtp2mqtt/config.json" ]; then
    echo "<INFO> Backing up user config.json from /opt/loxberry/config/plugins/smtp2mqtt/config.json to $LBPDATA_DIR/config.json.bak"
    cp "/opt/loxberry/config/plugins/smtp2mqtt/config.json" "$LBPDATA_DIR/config.json.bak"
fi

exit 0
