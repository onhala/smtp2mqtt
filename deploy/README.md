# Secure Deployment with HTTPS Reverse Proxy (Caddy / Portainer)

This directory contains template configurations for running `smtp2mqtt` securely behind the **Caddy** reverse proxy. This setup ensures that your web status dashboard and JSON API are fully encrypted over HTTPS, while managing Let's Encrypt certificates automatically.

---

## Architecture Overview

```
                        +---------------------------------------+
                        |             Docker Host               |
                        |                                       |
  [ Camera ] (SMTP) ----|---> Port 1025 -------------------+    |
                        |                                  |    |
                        |     (proxy-net private network)  |    |
                        |                                  v    |
                        |                            [ smtp2mqtt ]
                        |                                  ^    |
                        |                                  |    |
  [ Browser ] (HTTPS) --|---> Port 443 -> [ Caddy ] -------+    |
                        |                                (HTTP:8080)
                        +---------------------------------------+
```

1. **SMTP (Port `1025`)**: Exposed directly to your local network so cameras or other devices can send triggers via unencrypted or encrypted SMTP.
2. **Web Dashboard & API (Port `443` / `80`)**: Handled by **Caddy**, which automatically provisions a Let's Encrypt SSL/TLS certificate for your domain name and proxies requests securely to `smtp2mqtt` on port `8080` over a private Docker bridge network.

---

## Deployment Steps

### 1. Prerequisites
- A registered domain or subdomain pointing to your Docker host's public/local IP (e.g. `smtp.yourdomain.com`).
- Ports `80` and `443` forwarded from your router to your Docker host (if accessing over the internet) or a local CA/DNS setup.

### 2. Configuration
Clone or copy the files in this directory to a folder on your server:

1. **Edit `docker-compose.yml`**:
   - Set `MQTT_HOST` to your MQTT broker's IP address (e.g. your Loxberry server).
   - Set `DOMAIN_NAME` in the `caddy` service environment to your domain (e.g. `smtp.yourdomain.com`).

2. **Edit `Caddyfile`**:
   - The default `Caddyfile` uses the `$DOMAIN_NAME` environment variable configured in `docker-compose.yml`. You generally do not need to modify this file.

### 3. Deploy as a Portainer Stack (or CLI)
- **Portainer**: Go to **Stacks** > **Add stack**, paste the contents of `docker-compose.yml`, upload the `Caddyfile` to the same folder on your host, and deploy.
- **Docker Compose CLI**:
  ```bash
  docker compose up -d
  ```

Caddy will automatically fetch and manage SSL certificates. Your dashboard will be safely accessible at `https://smtp.yourdomain.com`.
