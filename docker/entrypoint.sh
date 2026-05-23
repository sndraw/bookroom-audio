#!/bin/bash
set -e

cd /app

if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting bookroom-audio server..."
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Environment:"
echo "  - MODEL: ${MODEL:-medium}"
echo "  - DEVICE: ${DEVICE:-auto}"
echo "  - COMPUTE_TYPE: ${COMPUTE_TYPE:-float16}"
echo "  - NUM_WORKERS: ${NUM_WORKERS:-2}"

.venv/bin/python -m bookroom_audio.server