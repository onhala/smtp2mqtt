#!/bin/bash
# LoxBerry Post-Upgrade Script for smtp2mqtt

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

DAEMON="$LBPBIN_DIR/smtp2mqtt.py"

if [ ! -f "$DAEMON" ]; then
    DAEMON="$LBPBIN_DIR/bin/smtp2mqtt.py"
fi

if [ -f "$LBPBIN_DIR/bin/smtp2mqtt.py" ] && [ ! -f "$LBPBIN_DIR/smtp2mqtt.py" ]; then
    cp "$LBPBIN_DIR/bin/smtp2mqtt.py" "$LBPBIN_DIR/smtp2mqtt.py"
fi
if [ -f "$LBPBIN_DIR/smtp2mqtt.py" ] && [ ! -f "$LBPBIN_DIR/bin/smtp2mqtt.py" ]; then
    mkdir -p "$LBPBIN_DIR/bin"
    cp "$LBPBIN_DIR/smtp2mqtt.py" "$LBPBIN_DIR/bin/smtp2mqtt.py"
fi

chmod +x "$LBPBIN_DIR/smtp2mqtt.py" 2>/dev/null || true
chmod +x "$LBPBIN_DIR/bin/smtp2mqtt.py" 2>/dev/null || true

# Restore user configuration backup if present
if [ -f "$LBPDATA_DIR/config.json.bak" ]; then
    echo "<INFO> Restoring user config.json from $LBPDATA_DIR/config.json.bak..."
    mkdir -p "$LBPCONFIG_DIR"
    cp "$LBPDATA_DIR/config.json.bak" "$LBPCONFIG_DIR/config.json"
    cp "$LBPDATA_DIR/config.json.bak" "/opt/loxberry/config/plugins/smtp2mqtt/config.json" 2>/dev/null || true
    if id -u loxberry >/dev/null 2>&1; then
        chown -R loxberry:loxberry "$LBPCONFIG_DIR" "/opt/loxberry/config/plugins/smtp2mqtt" 2>/dev/null || true
    fi
fi

LBPLOG_DIR="${LBPLOG:-$LB_HOME/log/plugins/$PDIR}"
echo "<INFO> Registering plugin logfile in LoxBerry Log Database..."
mkdir -p "$LBPLOG_DIR"
touch "$LBPLOG_DIR/smtp2mqtt.log"
perl -MLoxBerry::Log -e '$log = LoxBerry::Log->new(name => "daemon", package => "smtp2mqtt", filename => "'"$LBPLOG_DIR/smtp2mqtt.log"'", append => 1, addtime => 1); $log->LOGSTART("smtp2mqtt session");' 2>/dev/null || true

echo "<INFO> Restarting smtp2mqtt daemon process after upgrade..."

pkill -f "smtp2mqtt.py" 2>/dev/null || true
sleep 1

if [ "$(id -un 2>/dev/null)" = "loxberry" ]; then
    nohup python3 "$DAEMON" > /dev/null 2>&1 &
elif command -v runuser >/dev/null 2>&1; then
    runuser -u loxberry -- nohup python3 "$DAEMON" > /dev/null 2>&1 &
elif id -u loxberry >/dev/null 2>&1; then
    su -s /bin/bash loxberry -c "nohup python3 '$DAEMON' > /dev/null 2>&1 &"
else
    nohup python3 "$DAEMON" > /dev/null 2>&1 &
fi

echo "<OK> smtp2mqtt upgrade completed successfully."
exit 0
