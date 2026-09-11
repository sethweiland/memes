# Production Dockerfile for meme-ops Flask web UI
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create output directory for generated memes
RUN mkdir -p output/memes

# Expose port 8080 (configurable via $PORT)
EXPOSE 8080

# Run with gunicorn
CMD gunicorn -b 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120 wsgi:app
