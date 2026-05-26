# Use NVIDIA CUDA base image
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu20.04

WORKDIR /app

# Install system dependencies including ffmpeg for video processing
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    espeak-ng \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip3 install --upgrade pip

# Install uv
RUN pip install uv

# Copy project files
COPY ./pyproject.toml ./pyproject.toml
COPY ./uv.lock ./uv.lock

# Let uv handle the Python version and create the environment
RUN uv sync --no-cache

# Install Linux-specific NVIDIA dependencies
RUN uv pip install nvidia-cusparselt-cu13==0.8.0

# Copy application code
COPY ./bookroom_audio ./bookroom_audio
COPY ./docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

EXPOSE 15231

ENTRYPOINT [ "/bin/bash","/entrypoint.sh" ]