#!/bin/bash
# LoxBerry Post-Installation Script for smtp2mqtt
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

LBPBIN_DIR="${ARGV5}/bin/plugins/${ARGV3}"
LBPCONFIG_DIR="${ARGV5}/config/plugins/${ARGV3}"
LBPDATA_DIR="${ARGV5}/data/plugins/${ARGV3}"
LBPLOG_DIR="${ARGV5}/log/plugins/${ARGV3}"

echo "<INFO> Creating plugin directories for logs, data, and config..."
mkdir -p "$LBPLOG_DIR" "$LBPDATA_DIR" "$LBPCONFIG_DIR"

if id -u loxberry >/dev/null 2>&1; then
    chown -R loxberry:loxberry "$LBPLOG_DIR" "$LBPDATA_DIR" "$LBPCONFIG_DIR" 2>/dev/null || true
fi

echo "<INFO> Installing Python dependencies for smtp2mqtt via pip..."
if [ -f "$LBPBIN_DIR/requirements.txt" ]; then
    pip3 install --break-system-packages -r "$LBPBIN_DIR/requirements.txt" 2>/dev/null || \
    python3 -m pip install --break-system-packages -r "$LBPBIN_DIR/requirements.txt" 2>/dev/null || true
fi

chmod +x "$LBPBIN_DIR/smtp2mqtt.py" 2>/dev/null || true
chmod +x "$LBPBIN_DIR/bin/smtp2mqtt.py" 2>/dev/null || true

echo "<INFO> Registering plugin logfile in LoxBerry Log Database..."
mkdir -p "$LBPLOG_DIR"
touch "$LBPLOG_DIR/smtp2mqtt.log"
chmod 0666 "$LBPLOG_DIR/smtp2mqtt.log" 2>/dev/null || true
perl -MLoxBerry::Log -e '$log = LoxBerry::Log->new(name => "daemon", package => "smtp2mqtt", filename => "'"$LBPLOG_DIR/smtp2mqtt.log"'", append => 1, addtime => 1); $log->LOGSTART("smtp2mqtt session");' 2>/dev/null || true

echo "<OK> smtp2mqtt installation completed successfully."
exit 0
