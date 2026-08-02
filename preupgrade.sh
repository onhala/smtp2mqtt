#!/bin/bash
# LoxBerry Pre-Upgrade Script for smtp2mqtt

if [ -f /etc/environment ]; then
    . /etc/environment
fi

LB_HOME="${LBHOMEDIR:-$HOME}"
PDIR="${3:-smtp2mqtt}"
LBPCONFIG_DIR="${LBPCONFIG:-$LB_HOME/config/plugins}/$PDIR"
LBPDATA_DIR="${LBPDATA:-$LB_HOME/data/plugins}/$PDIR"

echo "<INFO> Stopping smtp2mqtt service before upgrade..."
pkill -f "smtp2mqtt.py" 2>/dev/null || true

# Back up user configuration to preserve settings across upgrades
mkdir -p "$LBPDATA_DIR"
if [ -f "$LBPCONFIG_DIR/config.json" ]; then
    echo "<INFO> Backing up user config.json to $LBPDATA_DIR/config.json.bak"
    cp "$LBPCONFIG_DIR/config.json" "$LBPDATA_DIR/config.json.bak"
fi

exit 0
