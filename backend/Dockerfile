FROM python:3.11-slim

WORKDIR /app

# Copy and install requirements first (for caching)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create Prometheus multiprocess directory
RUN mkdir -p /tmp/prometheus_multiproc && chmod 777 /tmp/prometheus_multiproc

# Copy contracts (shared module)
COPY contracts/ /app/contracts/

# Copy backend code
COPY backend/ .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
