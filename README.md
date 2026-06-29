# smtp2mqtt

A lightweight, high-performance, and fully asynchronous SMTP-to-MQTT bridge. It runs an unthreaded SMTP gateway, receives emails (e.g., motion detection trigger emails from Hikvision cameras), and publishes trigger payloads directly to an MQTT broker.

This is a modernized version of `wicol/emqtt` redesigned for modern Python (3.10+ / 3.13+), resolving event loop issues and utilizing non-blocking asynchronous IO. It is specifically designed to integrate camera motion detection triggers with automation systems like **Loxberry (MQTT Gateway) and Loxone**.


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
| `ENABLE_WEB` | Enable the built-in zero-dependency HTTP server for stats/dashboard | `True` |
| `WEB_PORT` | Port the built-in HTTP server listens on | `8080` |
| `DEBUG` | Enable verbose debug logging | `False` |

---

## Web Status Dashboard & JSON API

The gateway features a built-in, lightweight async HTTP server. When `ENABLE_WEB=True` (enabled by default), you can access:
- **Status Dashboard (`http://localhost:8080/`)**: A premium dark-mode dashboard showing uptime, message count, connection statuses for the MQTT broker and SMTP monitor, and a real-time log of recent email triggers and publish actions.
- **JSON Status API (`http://localhost:8080/api`)**: Returns dynamic status JSON including helper fields tailored for external dashboards.

---

## Homepage Integration (gethomepage.dev)

You can easily integrate `smtp2mqtt` with your Homepage dashboard using the pre-configured [homepage_widget.yaml](homepage_widget.yaml) configuration. It utilizes Homepage's `customapi` widget to map dynamic stats from the `/api` status endpoint.

### Example Widget Configuration

Add the following to your `services.yaml` or `widgets.yaml`:

```yaml
- customapi:
    name: smtp2mqtt Gateway
    icon: mdi-email-sync-outline
    url: http://<smtp2mqtt-ip>:8080/api/status
    method: GET
    headers:
      Accept: application/json
    mappings:
      - title: Messages
        value: "{{processed_messages_count}}"
        format: number
      - title: Uptime
        value: "{{uptime_formatted}}"
      - title: SMTP
        value: "{{smtp_status_text}}"
        color: "{{#if (eq smtp_status_text 'Active')}}green{{else}}red{{/if}}"
      - title: MQTT
        value: "{{mqtt_status_text}}"
        color: "{{#if (eq mqtt_status_text 'Connected')}}green{{else}}red{{/if}}"
```


---

## Running with Docker

The container is built on top of the official, ultra-lightweight `python:3.13-slim` image and runs inside `/app`.


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

### Local Simulation & Interactive Testing

For interactive local testing without needing a real MQTT broker or external SMTP servers, a comprehensive simulation tool is provided under `scratch/simulate.py`. This script spins up a mock MQTT broker on port `1883` and allows you to trigger mock email events instantly to verify parsing, attachment handling, and UI updates.

#### 1. Start the Simulation Environment

Run the simulation script with no arguments. This starts a mock MQTT broker in a background thread and opens an interactive console:
```bash
python scratch/simulate.py
```

#### 2. Run the smtp2mqtt Gateway

In a separate terminal tab or window, run the main gateway application (ensuring you are in your virtual environment):
```bash
python smtp2mqtt.py
```
This automatically connects to the mock MQTT broker on `localhost:1883`, starts the SMTP receiver on port `1025`, and serves the live Web Status Dashboard on `http://localhost:8080`.

#### 3. Trigger Mock Email Alerts

Go back to the simulation terminal window. You can interact with the environment using simple keyboard commands:
* Press **`E`** to send a mock security alert email to the SMTP server (listening on port `1025`). This email contains a sample camera JPEG snapshot.
  * The gateway will receive the email, parse the attachment, save it in the `attachments/` directory, and publish a triggered state (`ON`) to the MQTT broker.
  * After 10 seconds (default `MQTT_RESET_TIME`), the gateway automatically schedules and publishes a reset state (`OFF`) to the broker.
* Press **`Q`** to shut down the simulation and stop the background mock broker cleanly.

#### 4. Monitor Real-Time Status

Open **`http://localhost:8080`** in your browser to view the dynamic dashboard. You will see:
* Real-time pulsating status indicators showing that both the **SMTP Server** and **MQTT Broker** are healthy/online.
* An interactive **Recent Actions** table listing all email transactions, their sender details, mapped MQTT topics, and payloads, fully protected from XSS.
* Dynamic counts of processed messages and uptime tracking.

### Automated Testing (CI)

Every code push or Pull Request to the repository triggers a GitHub Actions workflow (`.github/workflows/test.yml`). It sets up a clean environment, installs all dependencies, and runs the entire `pytest` suite. This gives you a clear visual indicator of code health directly on GitHub.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
