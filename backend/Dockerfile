FROM python:3.11-bookworm

# Install git and ssh
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git \
    openssh-client \
    ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Create data directory
RUN mkdir -p /data

# Environment variables
ENV DATA_DIR=/data
ENV WORK_DIR=/tmp/git-mirror

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
