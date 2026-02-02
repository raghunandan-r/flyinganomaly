FROM python:3.11-slim

WORKDIR /app

# Copy and install requirements first (for caching)
COPY ingestion/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create Prometheus multiprocess directory
RUN mkdir -p /tmp/prometheus_multiproc && chmod 777 /tmp/prometheus_multiproc

# Copy contracts (shared module)
COPY contracts/ /app/contracts/

# Copy ingestion code
COPY ingestion/ .

CMD ["python", "-u", "producer_flight.py"]
