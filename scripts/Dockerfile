FROM python:3.11-slim

WORKDIR /app

# Install docker-compose (standalone) for docker compose commands
# We'll use the host's docker socket via volume mount
RUN apt-get update && apt-get install -y \
    curl \
    && curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose \
    && chmod +x /usr/local/bin/docker-compose \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Make scripts executable
RUN chmod +x init_topics.py integration_agent.py

# Default command runs integration agent, but can override for init_topics
# Use -u for unbuffered output so logs appear immediately
CMD ["python3", "-u", "integration_agent.py"]
