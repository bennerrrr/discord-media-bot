# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Install FFmpeg and build deps for discord.py[voice] (libopus)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    libopus-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user for basic hardening
RUN useradd -m botuser
USER botuser

CMD ["python", "-m", "bot.main"]
