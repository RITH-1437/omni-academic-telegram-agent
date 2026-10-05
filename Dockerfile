# Multi-stage production Dockerfile for Year 5 CS Telegram Bot
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency specifications
COPY requirements.txt .

# Install dependencies to wheels
RUN pip install --no-cache-dir --user -r requirements.txt


# Final runtime image
FROM python:3.12-slim AS runtime

# Set non-buffered output & Python path
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/home/appuser/.local/bin:$PATH \
    TZ=Asia/Phnom_Penh

WORKDIR /app

# Install runtime utilities & timezone data
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root system user for security
RUN groupadd -r appuser && useradd -r -g appuser -u 1000 -d /home/appuser -m appuser

# Copy installed python wheels from builder
COPY --from=builder /root/.local /home/appuser/.local

# Create data directory with appropriate ownership
RUN mkdir -p /app/data && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Copy application source code
COPY --chown=appuser:appuser . .

# Persistent SQLite database volume
VOLUME ["/app/data"]

# Run the bot
CMD ["python", "bot.py"]
