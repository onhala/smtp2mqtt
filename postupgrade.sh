#!/bin/bash
# LoxBerry Post-Upgrade Script for smtp2mqtt

if [ -f /etc/environment ]; then
    . /etc/environment
fi

LB_HOME="${LBHOMEDIR:-$HOME}"
PDIR="${3:-smtp2mqtt}"
LBPBIN_DIR="${LBPBIN:-$LB_HOME/bin/plugins}/$PDIR"
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
