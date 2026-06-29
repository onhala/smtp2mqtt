#!/usr/bin/env python3
import socket
import sys
import os

def check_health() -> bool:
    """
    Checks the health of the smtp2mqtt gateway by attempting to connect
    to the SMTP port and reading the initial server banner.
    """
    # Read the SMTP port from env, falling back to the default of 1025
    try:
        port = int(os.environ.get("SMTP_PORT", 1025))
    except ValueError:
        port = 1025

    host = "127.0.0.1"
    timeout = 5

    try:
        # Connect to the local SMTP server
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            # Read the initial greeting banner from the SMTP server
            banner = sock.recv(1024)
            if banner.startswith(b"220"):
                print(f"Healthy: SMTP server is responding on {host}:{port} ({banner.decode('utf-8', errors='replace').strip()})")
                return True
            else:
                print(f"Unhealthy: Unexpected SMTP banner on {host}:{port}: {banner!r}", file=sys.stderr)
                return False
    except Exception as e:
        print(f"Unhealthy: Failed to connect to SMTP server on {host}:{port} - {e}", file=sys.stderr)
        return False

if __name__ == "__main__":
    if check_health():
        sys.exit(0)
    else:
        sys.exit(1)
