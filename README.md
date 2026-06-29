# smtp2mqtt

A lightweight, high-performance, and fully asynchronous SMTP-to-MQTT bridge. It runs an unthreaded SMTP gateway, receives emails (e.g., motion detection trigger emails from Hikvision cameras), and publishes trigger payloads directly to an MQTT broker.

This is a modernized version of `wicol/emqtt` redesigned for modern Python (3.10+ / 3.12+), resolving event loop issues and utilizing non-blocking asynchronous IO. It is specifically designed to integrate camera motion detection triggers with automation systems like **Loxberry (MQTT Gateway) and Loxone**.

---

## Features

- **Fully Asynchronous Architecture**: Rewritten using Python's modern `async/await` and `aiosmtpd.controller.UnthreadedController` for non-blocking network and email processing.
- **Non-blocking IO Execution**: Blocking synchronous operations (such as MQTT publishing and file saving) are executed on a separate thread pool using `asyncio.to_thread` to maintain loop performance.
- **Graceful Shutdown**: Properly handles termination signals (`SIGINT`, `SIGTERM`) to clean up connections, stop the SMTP server, and cancel active reset timers.
- **Automatic Topic Resets**: Automatically schedules a reset payload (e.g., `OFF`) after a configurable delay when a trigger payload (e.g., `ON`) is sent.
- **Optional Image Attachment Saving**: Extracts and saves image attachments (e.g., snapshots from cameras) to a persistent folder.
- **Robust Configuration**: Robust, case-insensitive parsing of boolean parameters from environment variables.

---

## How It Works

1. The gateway listens on a configured SMTP port (default: `1025`).
2. When an email is received from `camera1@home.com`, it parses the sender and converts it to an MQTT topic:  
   `smtp2mqtt/camera1-home.com`
3. It publishes a trigger payload (`ON`) to the topic.
4. If image attachments are present and `SAVE_ATTACHMENTS` is enabled, it stores them under the `attachments/` folder.
5. If `MQTT_RESET_TIME` is set (e.g., `10` seconds), it schedules a task that will automatically publish a reset payload (`OFF`) to the same topic after the timer expires, resetting the Loxone input.

---

## Configuration (Environment Variables)

| Variable | Description | Default |
| :--- | :--- | :--- |
| `SMTP_PORT` | Port the SMTP gateway listens on | `1025` |
| `MQTT_HOST` | Hostname or IP of the MQTT broker (e.g., Loxberry) | `localhost` |
| `MQTT_PORT` | Port of the MQTT broker | `1883` |
| `MQTT_USERNAME` | Username for the MQTT broker (optional) | `""` |
| `MQTT_PASSWORD` | Password for the MQTT broker (optional) | `""` |
| `MQTT_TOPIC` | Root prefix for published MQTT topics | `smtp2mqtt` |
| `MQTT_PAYLOAD` | Payload published when an email is received (Trigger) | `ON` |
| `MQTT_RESET_TIME` | Delay in seconds before resetting the topic (`0` to disable) | `10` |
| `MQTT_RESET_PAYLOAD` | Payload published when the reset timer expires | `OFF` |
| `SAVE_ATTACHMENTS` | Whether to extract and save attached image snapshots | `False` |
| `SAVE_ATTACHMENTS_DURING_RESET_TIME` | Save images from emails arriving while reset timer is active | `False` |
| `DEBUG` | Enable verbose debug logging | `False` |

---

## Running with Docker

The container is built on top of the official, ultra-lightweight `python:3.12-slim` image and runs inside `/app`.

### 1. Build the Docker Image
```bash
docker build -t smtp2mqtt .
```

### 2. Run the Container
Run the container on your host machine or server (e.g., Loxberry/Synology/RPi). Make sure to bind your ports and map volumes to persist logs and attachments.

```bash
docker run -d \
    --name smtp2mqtt \
    --net host \
    --restart always \
    -e "SMTP_PORT=1025" \
    -e "MQTT_HOST=192.168.1.50" \
    -e "MQTT_USERNAME=my_mqtt_user" \
    -e "MQTT_PASSWORD=my_mqtt_password" \
    -e "SAVE_ATTACHMENTS=True" \
    -e "DEBUG=False" \
    -v /etc/localtime:/etc/localtime:ro \
    -v $PWD/log:/app/log \
    -v $PWD/attachments:/app/attachments \
    smtp2mqtt
```

> [!NOTE]
> Ensure your volume directories are mapped to `/app/log` and `/app/attachments` inside the container to match the unified workspace of the modern image.

### 3. Docker Healthcheck

The Docker container now includes a built-in `HEALTHCHECK` directive that runs a lightweight, zero-dependency Python script (`healthcheck.py`) every 30 seconds.

The healthcheck connects to the SMTP port, validates that the SMTP server is active, and verifies that it is returning a healthy SMTP banner (`220`). If the container ever freezes, Docker will automatically flag it as `unhealthy`. When run with `--restart always`, Docker will automatically reboot the container to restore your smart home automation flows instantly.

---

## Maintenance & Housekeeping

If you are saving attachments, you can set up a simple cron job to clean up older snapshots periodically:

```bash
# Deletes snapshot files older than 20 days inside the container
docker exec smtp2mqtt find attachments -type f -ctime +20 -delete
```

---

## Development & Testing

This project contains a comprehensive automated test suite to ensure robustness, compatibility, and prevent regressions.

### Running Tests Locally

1. Create and activate a Python virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies (including testing tools):
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

3. Run the test suite:
   ```bash
   pytest tests/ -v
   ```

The test suite includes both mock-based unit tests (testing attachment parsing and MQTT publishing logic without needing an active broker) and a full, end-to-end integration test (which spins up the real SMTP server on a random high port, initiates a real SMTP transaction using `smtplib`, and gracefully shuts down, confirming logs match expected behaviors).

### Automated Testing (CI)

Every code push or Pull Request to the repository triggers a GitHub Actions workflow (`.github/workflows/test.yml`). It sets up a clean environment, installs all dependencies, and runs the entire `pytest` suite. This gives you a clear visual indicator of code health directly on GitHub.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
