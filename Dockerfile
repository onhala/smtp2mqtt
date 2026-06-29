FROM python:3.12-slim

# Set non-buffered output for real-time logs
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first for better caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application script
COPY smtp2mqtt.py ./

# Expose SMTP port
EXPOSE 1025

# Run the app
CMD ["python", "smtp2mqtt.py"]
