#!/bin/bash
# LoxBerry Pre-Upgrade Script for smtp2mqtt
# Arguments passed by LoxBerry plugininstall.pl:
# $1: Temp folder during installation
# $2: Plugin Name
# $3: Plugin Installation Folder
# $4: Plugin Version
# $5: Base folder of LoxBerry (/opt/loxberry)

if [ -f /etc/environment ]; then
    . /etc/environment
fi

ARGV1="${1}"
ARGV2="${2:-smtp2mqtt}"
ARGV3="${3:-smtp2mqtt}"
ARGV4="${4}"
ARGV5="${5:-${LBHOMEDIR:-/opt/loxberry}}"

echo "<INFO> Stopping smtp2mqtt service before upgrade..."
pkill -f "smtp2mqtt.py" 2>/dev/null || true

echo "<INFO> Creating temporary folder for config backup: /tmp/${ARGV1}_upgrade/config"
mkdir -p "/tmp/${ARGV1}_upgrade/config"
mkdir -p "${ARGV5}/data/plugins/${ARGV3}"

# Dual-layer backup: /tmp upgrade folder + data folder fallback
if [ -d "${ARGV5}/config/plugins/${ARGV3}" ]; then
    echo "<INFO> Backing up existing config files to /tmp/${ARGV1}_upgrade/config"
    cp -p -v -r "${ARGV5}/config/plugins/${ARGV3}/"* "/tmp/${ARGV1}_upgrade/config/" 2>/dev/null || true
fi

if [ -f "${ARGV5}/config/plugins/${ARGV3}/config.json" ]; then
    echo "<INFO> Backing up user config.json to data folder: ${ARGV5}/data/plugins/${ARGV3}/config.json.bak"
    cp "${ARGV5}/config/plugins/${ARGV3}/config.json" "${ARGV5}/data/plugins/${ARGV3}/config.json.bak" 2>/dev/null || true
fi

exit 0
