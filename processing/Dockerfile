FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY processing/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create Prometheus multiprocess directory
RUN mkdir -p /tmp/prometheus_multiproc && chmod 777 /tmp/prometheus_multiproc

# Copy contracts (shared module)
COPY contracts/ /app/contracts/

# Copy processing code
COPY processing/ .

# Run Bytewax
CMD ["python", "run.py"]
