#!/bin/bash
# LoxBerry Post-Upgrade Script for smtp2mqtt
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

DAEMON="${LBPBIN_DIR}/smtp2mqtt.py"

if [ ! -f "$DAEMON" ]; then
    DAEMON="${LBPBIN_DIR}/bin/smtp2mqtt.py"
fi

if [ -f "${LBPBIN_DIR}/bin/smtp2mqtt.py" ] && [ ! -f "${LBPBIN_DIR}/smtp2mqtt.py" ]; then
    cp "${LBPBIN_DIR}/bin/smtp2mqtt.py" "${LBPBIN_DIR}/smtp2mqtt.py"
fi
if [ -f "${LBPBIN_DIR}/smtp2mqtt.py" ] && [ ! -f "${LBPBIN_DIR}/bin/smtp2mqtt.py" ]; then
    mkdir -p "${LBPBIN_DIR}/bin"
    cp "${LBPBIN_DIR}/smtp2mqtt.py" "${LBPBIN_DIR}/bin/smtp2mqtt.py"
fi

chmod +x "${LBPBIN_DIR}/smtp2mqtt.py" 2>/dev/null || true
chmod +x "${LBPBIN_DIR}/bin/smtp2mqtt.py" 2>/dev/null || true

# Restore user configuration from /tmp upgrade folder first
if [ -d "/tmp/${ARGV1}_upgrade/config" ] && [ "$(ls -A /tmp/${ARGV1}_upgrade/config 2>/dev/null)" ]; then
    echo "<INFO> Restoring user config files from /tmp/${ARGV1}_upgrade/config..."
    mkdir -p "${LBPCONFIG_DIR}"
    cp -p -v -r "/tmp/${ARGV1}_upgrade/config/"* "${LBPCONFIG_DIR}/" 2>/dev/null || true
elif [ -f "${LBPDATA_DIR}/config.json.bak" ]; then
    echo "<INFO> Restoring user config.json from fallback backup: ${LBPDATA_DIR}/config.json.bak..."
    mkdir -p "${LBPCONFIG_DIR}"
    cp "${LBPDATA_DIR}/config.json.bak" "${LBPCONFIG_DIR}/config.json"
fi

if id -u loxberry >/dev/null 2>&1; then
    chown -R loxberry:loxberry "${LBPCONFIG_DIR}" "${LBPDATA_DIR}" "${LBPLOG_DIR}" 2>/dev/null || true
fi
chmod 0666 "${LBPCONFIG_DIR}/config.json" 2>/dev/null || true

echo "<INFO> Removing temporary upgrade folder: /tmp/${ARGV1}_upgrade"
rm -rf "/tmp/${ARGV1}_upgrade" 2>/dev/null || true

echo "<INFO> Registering plugin logfile in LoxBerry Log Database..."
mkdir -p "${LBPLOG_DIR}"
touch "${LBPLOG_DIR}/smtp2mqtt.log"
chmod 0666 "${LBPLOG_DIR}/smtp2mqtt.log" 2>/dev/null || true
perl -MLoxBerry::Log -e '$log = LoxBerry::Log->new(name => "daemon", package => "smtp2mqtt", filename => "'"${LBPLOG_DIR}/smtp2mqtt.log"'", append => 1, addtime => 1); $log->LOGSTART("smtp2mqtt session");' 2>/dev/null || true

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
