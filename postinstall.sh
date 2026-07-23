#!/bin/bash
# LoxBerry Post-Installation Script for smtp2mqtt

if [ -f /etc/environment ]; then
    . /etc/environment
fi

LBHOMEDIR="${LBHOMEDIR:-/opt/loxberry}"
PDIR="${3:-smtp2mqtt}"
LBPBIN_DIR="${LBPBIN:-$LBHOMEDIR/bin/plugins}/$PDIR"
LBPCONFIG_DIR="${LBPCONFIG:-$LBHOMEDIR/config/plugins}/$PDIR"
LBPDATA_DIR="${LBPDATA:-$LBHOMEDIR/data/plugins}/$PDIR"
LBPLOG_DIR="${LBPLOG:-$LBHOMEDIR/log/plugins}/$PDIR"

echo "<INFO> Creating plugin directories for logs, data, and config..."
mkdir -p "$LBPLOG_DIR"
mkdir -p "$LBPDATA_DIR"
mkdir -p "$LBPCONFIG_DIR"

if id -u loxberry >/dev/null 2>&1; then
    chown -R loxberry:loxberry "$LBPLOG_DIR" "$LBPDATA_DIR" "$LBPCONFIG_DIR" 2>/dev/null || true
fi

echo "<INFO> Installing Python dependencies for smtp2mqtt via pip..."
if [ -f "$LBPBIN_DIR/requirements.txt" ]; then
    pip3 install --break-system-packages -r "$LBPBIN_DIR/requirements.txt" 2>/dev/null || \
    python3 -m pip install --break-system-packages -r "$LBPBIN_DIR/requirements.txt" 2>/dev/null || true
fi

echo "<INFO> Ensuring executable script structure exists..."
if [ -f "$LBPBIN_DIR/bin/smtp2mqtt.py" ] && [ ! -f "$LBPBIN_DIR/smtp2mqtt.py" ]; then
    cp "$LBPBIN_DIR/bin/smtp2mqtt.py" "$LBPBIN_DIR/smtp2mqtt.py"
fi
if [ -f "$LBPBIN_DIR/smtp2mqtt.py" ] && [ ! -f "$LBPBIN_DIR/bin/smtp2mqtt.py" ]; then
    mkdir -p "$LBPBIN_DIR/bin"
    cp "$LBPBIN_DIR/smtp2mqtt.py" "$LBPBIN_DIR/bin/smtp2mqtt.py"
fi

echo "<INFO> Setting executable permissions..."
chmod +x "$LBPBIN_DIR/smtp2mqtt.py" 2>/dev/null || true
chmod +x "$LBPBIN_DIR/bin/smtp2mqtt.py" 2>/dev/null || true

echo "<INFO> Starting smtp2mqtt daemon process..."
DAEMON="$LBPBIN_DIR/smtp2mqtt.py"
if [ ! -f "$DAEMON" ]; then
    DAEMON="$LBPBIN_DIR/bin/smtp2mqtt.py"
fi

pkill -f "smtp2mqtt.py" 2>/dev/null || true
sleep 1

if id -u loxberry >/dev/null 2>&1; then
    su - loxberry -c "nohup python3 '$DAEMON' > /dev/null 2>&1 &" || nohup python3 "$DAEMON" > /dev/null 2>&1 &
else
    nohup python3 "$DAEMON" > /dev/null 2>&1 &
fi

echo "<OK> smtp2mqtt post-installation completed successfully."
exit 0
