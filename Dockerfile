FROM python:3.13-slim


# Set non-buffered output for real-time logs
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first for better caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application script and healthcheck
COPY smtp2mqtt.py healthcheck.py ./

# Expose SMTP port
EXPOSE 1025

# Healthcheck configuration
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD ["python", "healthcheck.py"]

# Run the app
CMD ["python", "smtp2mqtt.py"]
