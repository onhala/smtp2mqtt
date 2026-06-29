# smtp2mqtt Backlog & Feature Requests

This document tracks planned features, enhancements, and backlog items for future releases of `smtp2mqtt`.

---

## 1. Automated Attachments Retention Policy & Cleanup

### Description
Currently, when `SAVE_ATTACHMENTS` is enabled, email attachments (e.g., camera motion captures) are saved to the `attachments` directory. Over time, this can lead to disk space exhaustion on host machines or inside Docker volumes.

### Proposed Solution
Implement an automated retention policy background worker that:
1. Runs periodically (e.g., once a day or every hour).
2. Cleans up files in the `attachments/` folder that are older than a configurable threshold (e.g., `ATTACHMENTS_RETENTION_DAYS`, defaulting to `7` days).
3. Allows disabling the cleaner by setting the value to `0`.

---

## 2. Real-time Dashboard UI Updates via Server-Sent Events (SSE)

### Description
The web status dashboard currently renders static values which require a browser page reload to update.

### Proposed Solution
Add support for Server-Sent Events (SSE) on the async web server:
1. Add an `/api/events` endpoint that streams connection status updates, message processing counts, and recent actions to the client.
2. Update the web UI (`index.html` generation) to listen to this endpoint and dynamically refresh the dashboard elements without requiring a manual page reload.

---

## 3. Advanced SMTP-to-MQTT Topic Routing Rules

### Description
All processed emails are currently published to a single flat MQTT topic configured inside env/YAML variables.

### Proposed Solution
Introduce advanced routing rules in the YAML configuration. This would allow users to define routing blocks:
```yaml
routing_rules:
  - from: "camera1@local.lan"
    topic: "smtp2mqtt/camera/driveway"
  - subject_contains: "garden"
    topic: "smtp2mqtt/camera/garden"
```
This enables multi-camera systems to route notifications and trigger distinct automations based on the source camera.
