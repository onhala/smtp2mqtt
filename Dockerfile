FROM python:3.13-slim


# Set non-buffered output for real-time logs
ENV PYTHONUNBUFFERED=1

# Version and metadata labels for Portainer/Docker
ENV VERSION=1.7.0
LABEL version="1.7.0"
LABEL org.opencontainers.image.version="1.7.0"
LABEL org.opencontainers.image.source="https://github.com/onhala/smtp2mqtt"

WORKDIR /app

# Create a non-privileged system user first and set up directories
RUN useradd -u 10001 -U -M -s /bin/false appuser && \
    mkdir -p log attachments && \
    chown -R appuser:appuser /app

# Install dependencies first for better caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application script, healthcheck, and static assets
COPY smtp2mqtt.py healthcheck.py logo.svg favicon.svg ./
RUN chmod +x smtp2mqtt.py && chown -R appuser:appuser /app

# Switch to non-privileged user
USER appuser

# Expose SMTP and Web Dashboard ports
EXPOSE 1025 8080

# Healthcheck configuration
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD ["python", "healthcheck.py"]

# Run the app
ENTRYPOINT ["/app/smtp2mqtt.py"]


