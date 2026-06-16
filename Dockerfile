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

# CPU 兼容性环境变量：
# - PYTORCH_DISABLE_AVX2 / PYTORCH_DISABLE_AVX512_F:
#   告诉 torch 在运行时动态选择 CPU 指令集，避免在无 AVX2 的机器
#   上因执行 AVX2 指令而触发 "Illegal instruction" 崩溃。
# - MAX_ISA / CTRANSLATE2_DISABLE_AVX2: 让 ctranslate2 (faster-whisper)
#   在不支持 AVX2 的 CPU 上降级到 SSE4 指令集。
ENV PYTORCH_DISABLE_AVX2=1 \
    PYTORCH_DISABLE_AVX512_F=1 \
    MAX_ISA=SSE4 \
    CTRANSLATE2_DISABLE_AVX2=1 \
    UV_PYTHON=python

# Install uv
RUN pip install uv

# Copy only dependency files first to leverage Docker layer caching
COPY ./pyproject.toml ./pyproject.toml
COPY ./uv.lock ./uv.lock

# Sync dependencies - packages will be installed in the virtual environment
RUN uv sync --frozen

# Copy application code
COPY ./bookroom_audio ./bookroom_audio
COPY ./docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

EXPOSE 15231

ENTRYPOINT [ "/bin/bash","/entrypoint.sh" ]