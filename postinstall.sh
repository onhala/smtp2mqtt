#!/bin/bash
# LoxBerry Post-Installation Script for smtp2mqtt

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

if [ -n "$LBPBIN" ]; then
    LBPBIN_DIR="$LBPBIN"
else
    LBPBIN_DIR="${LB_HOME}/bin/plugins/$PDIR"
fi

if [ -n "$LBPLOG" ]; then
    LBPLOG_DIR="$LBPLOG"
else
    LBPLOG_DIR="${LB_HOME}/log/plugins/$PDIR"
fi

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
perl -MLoxBerry::Log -e '$log = LoxBerry::Log->new(name => "daemon", package => "smtp2mqtt", filename => "'"$LBPLOG_DIR/smtp2mqtt.log"'", append => 1, addtime => 1); $log->LOGSTART("smtp2mqtt session");' 2>/dev/null || true

echo "<OK> smtp2mqtt installation completed successfully."
exit 0
