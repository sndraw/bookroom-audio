
# Build stage
FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu20.04 AS builder

WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y python3-pip

COPY ./pyproject.toml ./pyproject.toml
COPY ./uv.lock ./uv.lock

# Install dependencies
RUN pip install uv
RUN uv venv .venv --python=3.10
RUN . .venv/bin/activate
RUN uv pip install -e .

COPY ./bookroom_audio ./
COPY ./docker/entrypoint.sh /entrypoint.sh

# Expose the default port
EXPOSE 15231

# Set entrypoint
ENTRYPOINT [ "/bin/bash","/entrypoint.sh" ]