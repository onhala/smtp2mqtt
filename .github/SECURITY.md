# Security Policy

## Supported Versions

Only the latest release (the `master`/`main` branch) is actively supported with security updates. We recommend always running the latest version, especially when deploying in automated smart-home environments.

| Version | Supported |
| ------- | --------- |
| 1.x.x   | Yes       |
| < 1.0.0 | No        |

## Reporting a Vulnerability

Please do not open a public GitHub issue to report a security vulnerability. Instead, send an email to **starter.zlobri-2c@icloud.com** with details about the potential issue.  

We will investigate your report and aim to respond within 48 hours to coordinate a security release.

## Built-In Security Features

This modernized version of `smtp2mqtt` has been explicitly designed with production security and compliance in mind:

- **Path-Traversal Prevention**: Explicitly sanitizes and blocks email addresses or sender domains containing path-traversal sequences (e.g., `../`, `..\\`) to ensure image attachments cannot be written outside the designated `attachments/` folder.
- **MQTT Wildcard Mitigation**: Rejects inputs trying to exploit MQTT wildcard topics (e.g., `#` or `+` in sender usernames) to prevent unauthorized publishing and maintain control of your automation flows.
- **Non-Privileged Docker Execution**: The container runs under a dedicated, non-privileged system user (`appuser` with UID `10001`) inside `/app`. It does not require root permissions.
- **XSS and DoS Prevention**: The built-in status web dashboard validates and sanitizes all rendering outputs to avoid cross-site scripting (XSS) and controls memory limits on live logs.
