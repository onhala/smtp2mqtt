# Local Development Guide for smtp2mqtt

This guide explains how to set up your local development environment for `smtp2mqtt` without needing a full LoxBerry hardware environment.

## 🚀 Interactive Simulator (Recommended)

The repository includes a standalone simulator (`scratch/simulate.py`) that launches a mock MQTT broker on port `1883` and sends test email triggers on demand.

### 1. Set up Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

### 2. Run Simulator (Terminal 1)
```bash
python scratch/simulate.py
```

### 3. Run Gateway in Debug Mode (Terminal 2)
```bash
source .venv/bin/activate
export DEBUG=True
export MQTT_HOST=localhost
export SMTP_PORT=1025
export WEB_PORT=8080

python smtp2mqtt.py
```

### 4. Trigger Events
Press `E` in the Simulator window to simulate an incoming motion alert email with attachment.

## 🧪 Running Unit Tests

Run the full pytest test suite:

```bash
pytest tests/ -v
```
