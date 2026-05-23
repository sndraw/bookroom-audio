# Build stage
FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu20.04 AS builder

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3-pip \
    espeak-ng \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

COPY ./pyproject.toml ./pyproject.toml
COPY ./uv.lock ./uv.lock

RUN pip install uv
RUN uv venv .venv --python=3.11
RUN uv pip install -e . --no-cache

COPY ./bookroom_audio ./bookroom_audio

# Runtime stage
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu20.04

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 \
    espeak-ng \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/bookroom_audio /app/bookroom_audio
COPY ./docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

EXPOSE 15231

ENTRYPOINT [ "/bin/bash","/entrypoint.sh" ]