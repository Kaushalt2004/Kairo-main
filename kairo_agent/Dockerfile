FROM python:3.12-slim

WORKDIR /app

# Install system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . /app/kairo_agent

ENV PYTHONPATH=/app
ENV KAIRO_CLOUD_WS_URL=ws://kairo-cloud:8000
ENV KAIRO_VEHICLE_ID=KAIRO-001
ENV KAIRO_API_KEY=kairo_live_vehicle_kairo_001_key_secret_123
ENV KAIRO_ADAPTER_TYPE=mock
ENV KAIRO_TELEMETRY_RATE_HZ=10.0

CMD ["python", "-m", "kairo_agent.agent"]
