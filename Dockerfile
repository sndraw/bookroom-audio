# Use Python base image
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including ffmpeg for video processing
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    espeak-ng \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

# Copy project files
COPY ./pyproject.toml ./pyproject.toml
COPY ./uv.lock ./uv.lock

# Let uv handle the Python version and create the environment
RUN uv sync --no-cache

# Copy application code
COPY ./bookroom_audio ./bookroom_audio
COPY ./docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

EXPOSE 15231

ENTRYPOINT [ "/bin/bash","/entrypoint.sh" ]